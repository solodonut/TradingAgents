"""把代码解析成人类可读名称，供 WebUI 代码清单使用。

大陆 A 股/ETF 的中文名优先级：tushare（fund_basic/stock_basic 的 name 字段，
与基本面共用磁盘缓存，常可零请求命中）→ AKShare → yfinance（英文名）。
其它标的直接走 yfinance。fail-open：任何来源都拿不到时返回 None，清单仍显示
纯代码。各数据源端点偶发慢/不稳，故统一用线程+超时 bounded，超时即回退；后台
线程继续把结果写入磁盘缓存，下次命中即秒出中文名。
"""

import concurrent.futures
import logging

logger = logging.getLogger(__name__)

_NAME_LOOKUP_TIMEOUT_S = 6.0


def _akshare_name(code: str) -> str | None:
    """A 股/ETF 的中文名。无超时控制——由 resolve_ticker_name 包线程超时。"""
    import akshare as ak

    from .akshare_utils import ak_retry, cached_call, is_etf_code, to_bare_code

    bare = to_bare_code(code)
    if is_etf_code(bare):
        spot = cached_call(
            "fund_etf_spot_em", 15 * 60, lambda: ak_retry(ak.fund_etf_spot_em, max_retries=1)
        )
        if spot is None or spot.empty or "代码" not in spot.columns or "名称" not in spot.columns:
            return None
        codes = spot["代码"].astype(str).str.extract(r"(\d{6})", expand=False)
        match = spot[codes == bare]
        if match.empty:
            return None
        name = str(match["名称"].iloc[0]).strip()
        return name or None

    df = ak_retry(lambda: ak.stock_individual_info_em(symbol=bare), max_retries=1)
    if df is None or df.empty or "item" not in df.columns or "value" not in df.columns:
        return None
    row = df[df["item"] == "股票简称"]
    if row.empty:
        return None
    name = str(row["value"].iloc[0]).strip()
    return name or None


def _tushare_name(code: str) -> str | None:
    """A 股/ETF 的中文名（tushare fund_basic/stock_basic 的 name 字段）。

    复用 tushare_fundamentals 的缓存 key（``fund_basic_``/``stock_basic_{ts_code}``），
    该标的若已分析过基本面即可命中磁盘缓存，零额外请求。无超时控制——由
    resolve_ticker_name 包线程超时。
    """
    from .tushare_utils import (
        cached_call,
        call_tushare,
        get_tushare_client,
        is_fund_symbol,
        to_ts_code,
    )

    ts_code = to_ts_code(code)
    if is_fund_symbol(code):
        df = cached_call(
            f"fund_basic_{ts_code}",
            24 * 3600,
            lambda: call_tushare(lambda: get_tushare_client().fund_basic(ts_code=ts_code)),
        )
    else:
        df = cached_call(
            f"stock_basic_{ts_code}",
            24 * 3600,
            lambda: call_tushare(lambda: get_tushare_client().stock_basic(ts_code=ts_code)),
        )
    if df is None or df.empty or "name" not in df.columns:
        return None
    name = str(df["name"].iloc[0]).strip()
    return name or None


def _yfinance_name(code: str) -> str | None:
    """yfinance 公司名（直接调底层，绕过 domestic_china_only 门控）。"""
    from tradingagents.agents.utils.agent_utils import (
        _resolve_instrument_identity_with_yfinance,
    )

    identity = _resolve_instrument_identity_with_yfinance(code)
    name = identity.get("company_name")
    return name or None


def _bounded(fn, code: str) -> str | None:
    """在独立线程里跑名称解析并加超时；超时/限频/任何异常一律 fail-open 返回 None。"""
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        return executor.submit(fn, code).result(timeout=_NAME_LOOKUP_TIMEOUT_S)
    except Exception as exc:  # 超时 / 解析错误 / 任何异常 → 回退
        logger.debug("%s name lookup failed for %s: %s", getattr(fn, "__name__", fn), code, exc)
        return None
    finally:
        # 不等待：超时的话让后台线程继续把结果写进磁盘缓存，下次秒出
        executor.shutdown(wait=False)


def resolve_ticker_name(code: str) -> str | None:
    """A 股/ETF 优先 tushare→AKShare 中文名（bounded），否则/失败回退 yfinance。fail-open。"""
    from .akshare_utils import display_symbol, is_a_share

    ticker = code.strip().upper()
    if not ticker:
        return None

    yahoo_ticker = ticker
    if is_a_share(ticker):
        yahoo_ticker = display_symbol(ticker)
        for source in (_tushare_name, _akshare_name):
            name = _bounded(source, ticker)
            if name:
                return name

    try:
        return _yfinance_name(yahoo_ticker)
    except Exception as exc:
        logger.debug("yfinance name lookup failed for %s: %s", yahoo_ticker, exc)
        return None
