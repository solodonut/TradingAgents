"""ETF/fund news aggregation for mainland China products via Tushare.

The regular ``tushare_news.get_news`` path is intentionally stock-centric. ETF
analysis needs fund-level context, benchmark/theme headlines, and top disclosed
holding news in one compact tool response.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated

import pandas as pd
from dateutil.relativedelta import relativedelta

from . import tushare_news
from .akshare_utils import to_bare_code
from .config import get_config
from .errors import NoMarketDataError
from .ticker_name import resolve_ticker_name
from .tushare_utils import (
    cached_call,
    call_tushare,
    display_symbol,
    get_tushare_client,
    is_fund_symbol,
    to_ts_code,
)

_ETF_NEWS_TTL_SECONDS = 24 * 3600
_THEME_PATTERNS = (
    "沪深300",
    "中证A500",
    "中证500",
    "中证1000",
    "科创50",
    "创业板",
    "上证50",
    "半导体",
    "新能源",
    "人工智能",
    "机器人",
    "军工",
    "航空航天",
    "黄金",
    "红利",
    "医药",
    "消费",
    "银行",
    "证券",
    "电力",
    "电网",
)


@dataclass
class Holding:
    symbol: str
    name: str
    weight: float | None
    quarter: str | None


def _fetch_fund_basic(ts_code: str) -> pd.DataFrame:
    return cached_call(
        f"fund_basic_{ts_code}",
        _ETF_NEWS_TTL_SECONDS,
        lambda: call_tushare(lambda: get_tushare_client().fund_basic(ts_code=ts_code)),
    )


def _fetch_fund_portfolio(ts_code: str) -> pd.DataFrame:
    return cached_call(
        f"fund_portfolio_{ts_code}",
        _ETF_NEWS_TTL_SECONDS,
        lambda: call_tushare(lambda: get_tushare_client().fund_portfolio(ts_code=ts_code)),
    )


def _fetch_akshare_holdings(symbol: str, curr_date: str | None) -> list[Holding]:
    try:
        import akshare as ak
    except ModuleNotFoundError:
        return []

    year = (curr_date or datetime.now().strftime("%Y-%m-%d")).split("-")[0]
    code = to_bare_code(symbol)
    try:
        data = ak.fund_portfolio_hold_em(symbol=code, date=year)
    except Exception:
        return []
    if data is None or data.empty:
        return []

    holdings: list[Holding] = []
    for _, row in data.iterrows():
        code_value = row.get("股票代码")
        if pd.isna(code_value):
            continue
        stock_code = str(code_value).split(".")[0].zfill(6)
        # Shanghai uses the yahoo/akshare `.SS` form so downstream name/news
        # lookups (which reject the tushare `.SH` suffix) accept it.
        suffix = ".SS" if stock_code.startswith(("5", "6", "9")) else ".SZ"
        holdings.append(
            Holding(
                symbol=f"{stock_code}{suffix}",
                name=str(row.get("股票名称") or "").strip(),
                weight=_to_float(row.get("占净值比例")),
                quarter=_clean_text(row.get("季度")),
            )
        )
    return holdings


def _clean_text(value) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def _to_float(value) -> float | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip().replace("%", "")
    try:
        return float(text)
    except ValueError:
        return None


def _stock_symbol(value: str) -> str | None:
    if not isinstance(value, str):
        value = str(value)
    match = re.search(r"(\d{6})(?:\.(SH|SZ|SS))?", value, re.IGNORECASE)
    if not match:
        return None
    code = match.group(1)
    suffix = (match.group(2) or "").upper()
    # Normalize Shanghai to the yahoo/akshare `.SS` form; the tushare `.SH`
    # suffix is rejected by is_a_share/get_news/resolve_ticker_name downstream.
    if suffix == "SH":
        suffix = "SS"
    if not suffix:
        suffix = "SS" if code.startswith(("5", "6", "9")) else "SZ"
    return f"{code}.{suffix}"


def _parse_tushare_holdings(data: pd.DataFrame) -> list[Holding]:
    if data is None or data.empty:
        return []
    if "end_date" in data.columns:
        latest = data["end_date"].dropna().astype(str).max()
        if latest:
            data = data[data["end_date"].astype(str) == latest]
    holdings: list[Holding] = []
    seen_symbols: set[str] = set()
    for _, row in data.iterrows():
        raw_symbol = (
            row.get("symbol")
            or row.get("stock_code")
            or row.get("ts_code")
            or row.get("股票代码")
        )
        symbol = _stock_symbol(raw_symbol)
        if not symbol:
            continue
        if symbol in seen_symbols:
            continue
        seen_symbols.add(symbol)
        holdings.append(
            Holding(
                symbol=symbol,
                name=_clean_text(row.get("stk_name") or row.get("name") or row.get("股票名称")) or "",
                weight=_to_float(row.get("stk_mkv_ratio") or row.get("占净值比例")),
                quarter=_clean_text(row.get("end_date") or row.get("季度")),
            )
        )
    holdings.sort(key=lambda h: h.weight if h.weight is not None else -1, reverse=True)
    return holdings


def _fund_metadata(basic: pd.DataFrame) -> tuple[str | None, list[str]]:
    if basic is None or basic.empty:
        return None, []
    row = basic.iloc[0]
    name = _clean_text(row.get("name") or row.get("fund_name") or row.get("fullname"))
    terms: list[str] = []
    for column in ("benchmark", "benchmark_code", "invest_type", "type", "name", "fullname"):
        text = _clean_text(row.get(column))
        if text:
            terms.append(text)
    return name, terms


def _derive_theme_terms(name: str | None, raw_terms: list[str]) -> list[str]:
    text = " ".join([*(raw_terms or []), name or ""])
    terms: list[str] = []
    for pattern in _THEME_PATTERNS:
        if pattern in text:
            terms.append(pattern)
    for term in raw_terms:
        clean = term.strip()
        if clean and len(clean) <= 24:
            terms.append(clean)
    if name:
        terms.append(name)

    deduped: list[str] = []
    seen: set[str] = set()
    for term in terms:
        key = term.lower()
        if key not in seen:
            seen.add(key)
            deduped.append(term)
    return deduped


def _title_key(title: str) -> str:
    return re.sub(r"\s+", "", title).lower()


def _parse_news_articles(text: str, limit: int, seen: set[str]) -> list[str]:
    if not text or text.startswith(("No news found", "Error fetching news", "NO_DATA_AVAILABLE")):
        return []
    blocks = re.findall(r"### .+?(?=\n### |\Z)", text, flags=re.S)
    articles: list[str] = []
    for block in blocks:
        first, _, rest = block.partition("\n")
        title = first.removeprefix("### ").strip()
        content = rest.strip()
        # Sina flash items carry no title, so every one renders as `### 快讯`.
        # Keying on the header alone collapses all flash to one entry across the
        # shared seen-set; fold in the body's first line to keep them distinct.
        title_part = title.split(" (source:", 1)[0]
        first_content_line = content.split("\n", 1)[0].strip()
        key = _title_key(f"{title_part}\n{first_content_line}")
        if key in seen:
            continue
        seen.add(key)
        rendered = f"- **{title}**"
        if content:
            rendered += "\n  " + content.replace("\n", "\n  ")
        articles.append(rendered)
        if len(articles) >= limit:
            break
    return articles


def _render_theme_news(
    terms: list[str],
    start_date: str,
    end_date: str,
    limit: int,
    seen: set[str],
) -> list[str]:
    if not terms:
        return []
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d") + relativedelta(days=1)
    rows: list[tuple[datetime, str]] = []
    for src in ("sina",):
        data = tushare_news._fetch_flash(src, start_date, end_date)
        rows.extend(
            tushare_news._render_flash(
                data,
                terms,
                start_dt,
                end_dt,
                src_label=f"快讯/{src}",
            )
        )
    rows.sort(key=lambda row: row[0], reverse=True)

    articles: list[str] = []
    for _, block in rows:
        parsed = _parse_news_articles(block, 1, seen)
        if not parsed:
            continue
        articles.extend(parsed)
        if len(articles) >= limit:
            break
    return articles


def _render_articles_or_empty(articles: list[str], empty_message: str) -> str:
    if not articles:
        return empty_message + "\n"
    return "\n".join(articles) + "\n"


def _holding_heading(holding: Holding) -> str:
    parts = [holding.symbol, holding.name]
    if holding.weight is not None:
        parts.append(f"weight {holding.weight:g}%")
    return " ".join(part for part in parts if part)


def get_etf_news(
    symbol: Annotated[str, "Mainland China ETF/fund symbol"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    if not is_fund_symbol(symbol):
        raise NoMarketDataError(symbol, display_symbol(symbol), "not a mainland China listed ETF/fund")

    config = get_config()
    top_holdings = int(config.get("etf_news_top_holdings", 5))
    per_holding_limit = int(config.get("etf_news_per_holding_limit", 3))
    theme_limit = int(config.get("etf_news_theme_limit", 5))
    fund_limit = min(int(config.get("news_article_limit", 20)), 5)

    ts_code = to_ts_code(symbol)
    label = display_symbol(symbol)
    missing: list[str] = []
    seen_titles: set[str] = set()

    basic = _fetch_fund_basic(ts_code)
    fund_name, raw_terms = _fund_metadata(basic)
    theme_terms = _derive_theme_terms(fund_name, raw_terms)

    try:
        holdings = _parse_tushare_holdings(_fetch_fund_portfolio(ts_code))
    except Exception:
        holdings = []
    if not holdings:
        holdings = _fetch_akshare_holdings(symbol, end_date)

    try:
        fund_articles = _parse_news_articles(
            tushare_news.get_news(ts_code, start_date, end_date),
            fund_limit,
            seen_titles,
        )
    except Exception:
        fund_articles = []
    if not fund_articles:
        missing.append("ETF/fund-level news")

    try:
        theme_articles = _render_theme_news(theme_terms, start_date, end_date, theme_limit, seen_titles)
    except Exception:
        theme_articles = []
    if not theme_articles:
        missing.append("index/theme news")

    body = f"# ETF News for {label}, from {start_date} to {end_date}\n\n"
    body += "## ETF / Fund-Level News\n"
    body += _render_articles_or_empty(fund_articles, "No ETF/fund-level news found in this window.")
    body += "\n## Index / Theme News\n"
    body += _render_articles_or_empty(theme_articles, "No index/theme news found in this window.")
    body += "\n## Top Holdings News\n"

    if holdings:
        for holding in holdings[:top_holdings]:
            # Tushare fund_portfolio has no stock-name column, so names arrive
            # empty; backfill via the shared A-share name resolver (cached).
            if not holding.name:
                holding.name = resolve_ticker_name(holding.symbol) or ""
            body += f"### {_holding_heading(holding)}\n"
            try:
                news_text = tushare_news.get_news(holding.symbol, start_date, end_date)
                articles = _parse_news_articles(news_text, per_holding_limit, seen_titles)
                body += _render_articles_or_empty(articles, "No holding-specific news found in this window.")
            except Exception as exc:
                body += f"Holding news unavailable: {exc}\n"
    else:
        missing.append("top holdings")
        body += "Top holdings unavailable: latest disclosed holdings could not be retrieved.\n"

    missing_text = "none" if not missing else ", ".join(dict.fromkeys(missing))
    quarters = [holding.quarter for holding in holdings if holding.quarter]
    quarter_note = max(quarters) if quarters else "unknown"
    body += "\n## Coverage Notes\n"
    body += f"- Holdings source: Tushare fund_portfolio, latest disclosed quarter ({quarter_note}); AKShare fallback only when Tushare holdings are unavailable.\n"
    body += "- News source: Tushare first.\n"
    body += f"- Theme terms: {', '.join(theme_terms) if theme_terms else 'none'}.\n"
    body += f"- Missing sections: {missing_text}.\n"
    body += "- Holdings are based on the latest disclosed quarter, not real-time positions.\n"
    return body
