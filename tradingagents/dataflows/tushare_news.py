"""Tushare Pro 新闻资讯:个股(公司公告 + 关键词过滤快讯)与全局(快讯 + 长篇 + 新闻联播)。

Tushare 的快讯流(``news`` / ``major_news``)是通用 feed,不支持按个股搜索,所以个股新闻
靠 ``anns_d`` 公司公告(真·按 ts_code)+ 用股票中文名/代码在快讯正文里 ``contains`` 过滤。
契约与 ``akshare_news`` / ``yfinance_news`` 完全一致,``route_to_vendor`` 可透明切换。
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

import pandas as pd
from dateutil.relativedelta import relativedelta

from .config import get_config
from .errors import NoMarketDataError
from .ticker_name import resolve_ticker_name
from .tushare_utils import (
    cached_call,
    call_tushare,
    display_symbol,
    get_tushare_client,
    is_mainland_symbol,
    to_ts_code,
)

# 快讯流 intraday 波动大;1h 缓存收敛单次分析的重复调用(与 akshare_news 一致)。
_NEWS_TTL_SECONDS = 3600


def _compact(date_str: str) -> str:
    return date_str.replace("-", "")


def _flash_dt(date_str: str, end: bool = False) -> str:
    # tushare ``news`` / ``major_news`` 的 start_date/end_date 用 'YYYY-MM-DD HH:MM:SS'。
    return f"{date_str} 23:59:59" if end else f"{date_str} 00:00:00"


def _fetch_anns(ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
    key = f"anns_d/{ts_code}/{_compact(start_date)}/{_compact(end_date)}"

    def _fetch():
        client = get_tushare_client()
        return call_tushare(
            lambda: client.anns_d(
                ts_code=ts_code,
                start_date=_compact(start_date),
                end_date=_compact(end_date),
            )
        )

    return cached_call(key, _NEWS_TTL_SECONDS, _fetch)


def _fetch_flash(src: str, start_date: str, end_date: str) -> pd.DataFrame:
    key = f"news/{src}/{_compact(start_date)}/{_compact(end_date)}"

    def _fetch():
        client = get_tushare_client()
        return call_tushare(
            lambda: client.news(
                src=src,
                start_date=_flash_dt(start_date),
                end_date=_flash_dt(end_date, end=True),
            )
        )

    return cached_call(key, _NEWS_TTL_SECONDS, _fetch)


def _render_anns(df: pd.DataFrame) -> list[tuple[datetime, str]]:
    rows = []
    if df is None or df.empty:
        return rows
    for _, row in df.iterrows():
        pub = pd.to_datetime(row.get("ann_date"), errors="coerce")
        if pd.isna(pub):
            continue
        title = row.get("title", "无标题")
        url = row.get("url", "")
        block = f"### {title} (source: 公司公告)\n"
        if isinstance(url, str) and url.strip():
            block += f"Link: {url.strip()}\n"
        block += "\n"
        rows.append((pub.to_pydatetime(), block))
    return rows


def _render_flash(df: pd.DataFrame, keywords: list[str], start_dt, end_dt, src_label="快讯"):
    rows = []
    if df is None or df.empty:
        return rows
    for _, row in df.iterrows():
        pub = pd.to_datetime(row.get("datetime"), errors="coerce")
        if pd.isna(pub) or not (start_dt <= pub.to_pydatetime() <= end_dt):
            continue
        title = row.get("title") or ""
        content = row.get("content") or ""
        haystack = f"{title}{content}"
        if keywords and not any(k in haystack for k in keywords):
            continue
        display_title = title.strip() if isinstance(title, str) and title.strip() else "快讯"
        block = f"### {display_title} (source: {src_label})\n"
        if isinstance(content, str) and content.strip():
            block += f"{content.strip()}\n"
        block += "\n"
        rows.append((pub.to_pydatetime(), block))
    return rows


def get_news(
    ticker: Annotated[str, "A-share ticker (600519, 600519.SH, ...)"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """个股新闻:公司公告(anns_d)+ 关键词过滤快讯(news),合并按时间倒序。"""
    if not is_mainland_symbol(ticker):
        raise NoMarketDataError(ticker, "not an A-share; no Tushare company news")

    ts_code = to_ts_code(ticker)
    label = display_symbol(ticker)
    article_limit = get_config()["news_article_limit"]

    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d") + relativedelta(days=1)

    anns_err = flash_err = None
    anns_rows = flash_rows = []

    try:
        anns_rows = _render_anns(_fetch_anns(ts_code, start_date, end_date))
    except Exception as e:  # 单路失败降级,不整体报错
        anns_err = e

    name = resolve_ticker_name(ticker)
    code_only = ts_code.split(".")[0]
    keywords = [k for k in (name, code_only) if k]
    if keywords:
        try:
            flash_rows = _render_flash(
                _fetch_flash("sina", start_date, end_date), keywords, start_dt, end_dt
            )
        except Exception as e:
            flash_err = e

    if anns_err is not None and (flash_err is not None or not keywords) and not anns_rows and not flash_rows:
        return f"Error fetching news for {label}: {anns_err or flash_err}"

    # 公告在前(更硬),再按时间倒序拼快讯。
    ordered = anns_rows + sorted(flash_rows, key=lambda r: r[0], reverse=True)
    ordered = ordered[:article_limit]

    if not ordered:
        return f"No news found for {label} between {start_date} and {end_date}"

    body = "".join(block for _, block in ordered)
    return f"## {label} News, from {start_date} to {end_date}:\n\n{body}"
