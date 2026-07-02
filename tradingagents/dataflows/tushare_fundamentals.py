"""Tushare Pro mainland China fundamentals and financial statements.

ETF/fund symbols get a structured fund snapshot (basic, recent daily, adjustment
factors, portfolio holdings) and ``not_applicable`` statement responses, matching
the AKShare contract. A-share symbols get company basics, key financial
indicators, and the three statements, filtered on/before ``curr_date`` to avoid
look-ahead bias.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

import pandas as pd

from .errors import NoMarketDataError
from .tushare_utils import (
    cached_call,
    call_tushare,
    display_symbol,
    get_tushare_client,
    is_fund_symbol,
    to_ts_code,
)

_FUNDAMENTAL_TTL_SECONDS = 24 * 3600
_STATEMENT_METHODS = {
    "balance_sheet": "balancesheet",
    "income_statement": "income",
    "cashflow": "cashflow",
}


def _section(title: str, data: pd.DataFrame) -> str:
    if data is None or data.empty:
        return ""
    return f"\n## {title}\n\n" + data.to_csv(index=False)


def _fetch_optional(key: str, func):
    try:
        return cached_call(key, _FUNDAMENTAL_TTL_SECONDS, lambda: call_tushare(func))
    except Exception:
        return pd.DataFrame()


def _etf_statement_not_applicable(symbol: str, title: str, freq: str) -> str:
    label = display_symbol(symbol)
    header = f"# {title} for {label} (ETF/Fund, Tushare Pro, {freq})\n"
    header += "# Status: Not applicable to fund/ETF products\n"
    header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    return (
        header
        + "item,status,detail\n"
        + f"{title},not_applicable,"
        + "ETF/fund products do not publish operating-company financial statements; "
        + "use the Tushare fund/ETF fundamentals snapshot plus price and technical data.\n"
    )


def _fund_report(symbol: str, curr_date: str | None) -> str:
    label = display_symbol(symbol)
    ts_code = to_ts_code(symbol)
    client = get_tushare_client()
    end = (curr_date or pd.Timestamp.today().strftime("%Y-%m-%d")).replace("-", "")

    basic = _fetch_optional(
        f"fund_basic_{ts_code}",
        lambda: client.fund_basic(ts_code=ts_code),
    )
    daily = _fetch_optional(
        f"fund_daily_{ts_code}_{end}",
        lambda: client.fund_daily(ts_code=ts_code, end_date=end),
    ).head(5)
    adj = _fetch_optional(
        f"fund_adj_{ts_code}_{end}",
        lambda: client.fund_adj(ts_code=ts_code, end_date=end),
    ).head(5)
    portfolio = _fetch_optional(
        f"fund_portfolio_{ts_code}",
        lambda: client.fund_portfolio(ts_code=ts_code),
    ).head(20)

    if basic.empty and daily.empty and adj.empty and portfolio.empty:
        raise NoMarketDataError(symbol, label, "no Tushare fund fundamentals")

    header = f"# Fund/ETF Fundamentals for {label} (Tushare Pro)\n"
    header += "# Instrument type: Mainland China listed fund/ETF, not an operating company\n"
    header += "# Realtime net-asset-value, discount/premium, and order-book fields are not included in this Tushare tier\n"
    header += (
        "# Note: the 'Recent Fund Daily Data' and 'Adjustment Factors' sections below "
        "publish on a T+1 basis, so their latest row may lag the current trading day by "
        "one session (e.g. on the evening of a trading day the newest row is still the "
        "prior session). This is a data-source property, not stale data.\n"
    )
    header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    result = header
    result += _section("Fund Basic", basic)
    result += _section("Recent Fund Daily Data", daily)
    result += _section("Adjustment Factors", adj)
    result += _section("Portfolio Holdings", portfolio)
    return result


def _statement_report(symbol: str, kind: str, title: str, freq: str, curr_date: str | None) -> str:
    label = display_symbol(symbol)
    ts_code = to_ts_code(symbol)
    client = get_tushare_client()
    method_name = _STATEMENT_METHODS[kind]
    method = getattr(client, method_name)
    raw = cached_call(
        f"{kind}_{ts_code}",
        _FUNDAMENTAL_TTL_SECONDS,
        lambda: call_tushare(lambda: method(ts_code=ts_code)),
    )
    if raw is None or raw.empty:
        raise NoMarketDataError(symbol, label, f"no Tushare {kind} data")

    data = raw.copy()
    date_column = "end_date" if "end_date" in data.columns else "ann_date"
    data[date_column] = pd.to_datetime(data[date_column], format="%Y%m%d", errors="coerce")
    if curr_date:
        cutoff = pd.Timestamp(curr_date)
        data = data[data[date_column] <= cutoff]
    if data.empty:
        raise NoMarketDataError(symbol, label, f"no {kind} periods on/before {curr_date}")

    data = data.sort_values(date_column, ascending=False)
    data[date_column] = data[date_column].dt.strftime("%Y-%m-%d")
    header = f"# {title} for {label} (A-share, Tushare Pro, {freq})\n"
    header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    return header + data.to_csv(index=False)


def get_fundamentals(
    ticker: Annotated[str, "Mainland ticker (600519, 159241, ...)"],
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
):
    if is_fund_symbol(ticker):
        return _fund_report(ticker, curr_date)

    label = display_symbol(ticker)
    ts_code = to_ts_code(ticker)
    client = get_tushare_client()
    basic = _fetch_optional(f"stock_basic_{ts_code}", lambda: client.stock_basic(ts_code=ts_code))
    indicators = _fetch_optional(
        f"fina_indicator_{ts_code}", lambda: client.fina_indicator(ts_code=ts_code)
    ).head(8)
    if basic.empty and indicators.empty:
        raise NoMarketDataError(ticker, label, "no Tushare stock fundamentals")
    header = f"# Company Fundamentals for {label} (A-share, Tushare Pro)\n"
    header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    return header + _section("Stock Basic", basic) + _section("Financial Indicators", indicators)


def get_balance_sheet(
    ticker: Annotated[str, "Mainland ticker (600519, 159241, ...)"],
    freq: Annotated[str, "frequency hint, accepted for API parity"] = "quarterly",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
):
    if is_fund_symbol(ticker):
        return _etf_statement_not_applicable(ticker, "Balance Sheet", freq)
    return _statement_report(ticker, "balance_sheet", "Balance Sheet", freq, curr_date)


def get_income_statement(
    ticker: Annotated[str, "Mainland ticker (600519, 159241, ...)"],
    freq: Annotated[str, "frequency hint, accepted for API parity"] = "quarterly",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
):
    if is_fund_symbol(ticker):
        return _etf_statement_not_applicable(ticker, "Income Statement", freq)
    return _statement_report(ticker, "income_statement", "Income Statement", freq, curr_date)


def get_cashflow(
    ticker: Annotated[str, "Mainland ticker (600519, 159241, ...)"],
    freq: Annotated[str, "frequency hint, accepted for API parity"] = "quarterly",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
):
    if is_fund_symbol(ticker):
        return _etf_statement_not_applicable(ticker, "Cash Flow", freq)
    return _statement_report(ticker, "cashflow", "Cash Flow", freq, curr_date)
