"""把代码解析成人类可读名称，供 WebUI 代码清单使用。

大陆 A 股/ETF 优先用 AKShare 的中文名；其它标的（以及 AKShare 未命中/超时）
回退 yfinance（英文名）。fail-open：任何来源都拿不到时返回 None，清单仍显示
纯代码。AKShare 端点偶发慢/不稳，故用线程+超时 bounded，超时即回退；后台线程
继续把全表写入磁盘缓存，下次命中即秒出中文名。
"""

import concurrent.futures
import logging

logger = logging.getLogger(__name__)

_AKSHARE_TIMEOUT_S = 6.0


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


def _yfinance_name(code: str) -> str | None:
    """yfinance 公司名（直接调底层，绕过 domestic_china_only 门控）。"""
    from tradingagents.agents.utils.agent_utils import (
        _resolve_instrument_identity_with_yfinance,
    )

    identity = _resolve_instrument_identity_with_yfinance(code)
    name = identity.get("company_name")
    return name or None


def resolve_ticker_name(code: str) -> str | None:
    """A 股/ETF 优先 AKShare 中文名（bounded），否则/失败回退 yfinance。fail-open。"""
    from .akshare_utils import is_a_share

    ticker = code.strip().upper()
    if not ticker:
        return None

    if is_a_share(ticker):
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        try:
            future = executor.submit(_akshare_name, ticker)
            name = future.result(timeout=_AKSHARE_TIMEOUT_S)
            if name:
                return name
        except Exception as exc:  # 超时 / 解析错误 / 任何异常 → 回退
            logger.debug("AKShare name lookup failed for %s: %s", ticker, exc)
        finally:
            # 不等待：超时的话让后台线程继续把全表写进磁盘缓存，下次秒出
            executor.shutdown(wait=False)

    try:
        return _yfinance_name(ticker)
    except Exception as exc:
        logger.debug("yfinance name lookup failed for %s: %s", ticker, exc)
        return None
