"""AKShare A-share fundamentals: balance sheet, income, cash flow, overview.

This is the core reason A-shares need a dedicated vendor: Yahoo Finance and
Alpha Vantage barely cover mainland financial statements, while AKShare exposes
the full East Money filings (300+ line items per statement, every reported
period). Each function mirrors the ``y_finance`` fundamentals contract — same
arguments, CSV-with-header return string, ``NoMarketDataError`` on no data —
so the router treats AKShare like any other vendor.

Two A-share-specific concerns are handled here:

* Look-ahead bias: East Money returns every historical period including ones
  whose ``REPORT_DATE`` is after the simulation's ``curr_date``. We drop those,
  exactly like the Yahoo/Alpha Vantage paths do, so a backtest never sees a
  statement that wasn't public yet.
* Prompt noise: each statement carries hundreds of columns, most empty for any
  one company (bank/insurance-specific line items on an industrial, etc.). We
  drop all-null and metadata columns so the agent reads signal, not a wall of
  blanks.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Annotated

import akshare as ak
import pandas as pd

from .akshare_utils import (
    ak_retry,
    cached_call,
    display_symbol,
    is_a_share,
    is_etf_code,
    to_bare_code,
    to_prefixed_code,
)
from .errors import NoMarketDataError

# Financial statements change only at quarterly filing dates, so a 24-hour
# cache makes repeated runs instant while still refreshing within a day of a
# new filing. These calls are the slowest in the vendor (~1 min paginated).
_STATEMENT_TTL_SECONDS = 24 * 3600

# East Money statement metadata columns — identifiers and timestamps that are
# not financial line items. Dropped from the transposed report the agent reads.
_META_COLUMNS = frozenset({
    "SECUCODE", "SECURITY_CODE", "SECURITY_NAME_ABBR", "ORG_CODE", "ORG_TYPE",
    "REPORT_TYPE", "REPORT_DATE_NAME", "SECURITY_TYPE_CODE", "NOTICE_DATE",
    "UPDATE_DATE", "OPINION_TYPE", "OSOPINION_TYPE", "LISTING_STATE",
    "CURRENCY", "ACCEPT_ORG_TYPE", "STD_ITEM_CODE",
})

_STATEMENT_FETCHERS: dict[str, Callable[..., pd.DataFrame]] = {
    "balance_sheet": ak.stock_balance_sheet_by_report_em,
    "income_statement": ak.stock_profit_sheet_by_report_em,
    "cashflow": ak.stock_cash_flow_sheet_by_report_em,
}


def _is_etf_symbol(symbol: str) -> bool:
    """True for mainland listed fund/ETF symbols such as 159241 or 510300.SS."""
    try:
        return is_etf_code(to_bare_code(symbol))
    except ValueError:
        return False


def _etf_statement_not_applicable(symbol: str, title: str, freq: str) -> str:
    """Return a structured, non-failing statement response for ETF/fund products."""
    label = display_symbol(symbol)
    header = f"# {title} for {label} (ETF/Fund, AKShare, {freq})\n"
    header += "# Status: Not applicable to fund/ETF products\n"
    header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    return (
        header
        + "item,status,detail\n"
        + f"{title},not_applicable,"
        + "ETF/fund products do not publish operating-company financial statements; "
        + "use the AKShare fund/ETF fundamentals snapshot plus price and technical data.\n"
    )


def _pick_etf_spot_row(data: pd.DataFrame, code: str) -> pd.Series:
    """Find a fund/ETF row in East Money's ETF spot table across column variants."""
    for column in ("代码", "基金代码", "symbol", "代码简称"):
        if column not in data.columns:
            continue
        values = data[column].astype(str).str.extract(r"(\d{6})", expand=False)
        matches = data[values == code]
        if not matches.empty:
            return matches.iloc[0]
    raise NoMarketDataError(code, code, "fund/ETF not found in AKShare ETF spot table")


def _format_etf_fundamentals(symbol: str, curr_date: str | None) -> str:
    """Domestic ETF/fund overview from East Money via AKShare."""
    code = to_bare_code(symbol)
    label = display_symbol(symbol)

    try:
        spot = cached_call(
            "fund_etf_spot_em",
            15 * 60,
            lambda: ak_retry(ak.fund_etf_spot_em),
        )
    except Exception as e:
        raise NoMarketDataError(symbol, label, f"AKShare ETF spot unavailable: {e}") from e

    if spot is None or spot.empty:
        raise NoMarketDataError(symbol, label, "empty AKShare ETF spot table")

    row = _pick_etf_spot_row(spot.copy(), code)
    row = row.dropna()
    row = row[row.astype(str).str.strip() != ""]

    nav_summary = pd.DataFrame()
    try:
        end_date = (curr_date or pd.Timestamp.today().strftime("%Y-%m-%d")).replace("-", "")
        nav = cached_call(
            f"fund_etf_info_{code}_{end_date}",
            _STATEMENT_TTL_SECONDS,
            lambda: ak_retry(lambda: ak.fund_etf_fund_info_em(fund=code, end_date=end_date)),
        )
        if nav is not None and not nav.empty:
            nav_summary = nav.tail(5).copy()
    except Exception:
        # Spot data is enough for an ETF/fund fundamentals overview. Historical
        # NAV occasionally has gaps for newly listed funds, so omit it quietly.
        nav_summary = pd.DataFrame()

    spot_table = row.rename("value").to_frame()
    spot_table.index.name = "field"

    header = f"# Fund/ETF Fundamentals for {label} (AKShare, East Money)\n"
    header += "# Instrument type: Mainland China listed fund/ETF, not an operating company\n"
    header += "# Reporting currency: CNY where applicable\n"
    header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    result = header + "## ETF Spot Snapshot\n\n" + spot_table.to_csv()
    if not nav_summary.empty:
        result += "\n## Recent NAV History\n\n" + nav_summary.to_csv(index=False)
    result += (
        "\n# Note: Balance sheet, income statement, and cash-flow statement are "
        "not applicable to ETF/fund products. Use this snapshot with OHLCV and "
        "technical indicators for analysis.\n"
    )
    return result


def _fetch_statement(symbol: str, kind: str, curr_date: str | None) -> pd.DataFrame:
    """Fetch one statement type, drop future periods, keep populated line items.

    Returns a DataFrame indexed by financial line-item name with one column per
    reported period (most recent first), ready to serialize to CSV. The
    ``REPORT_DATE`` filter prevents look-ahead bias when ``curr_date`` is set.
    """
    prefixed = to_prefixed_code(symbol)
    fetcher = _STATEMENT_FETCHERS[kind]
    cache_key = f"{kind}_{prefixed}"
    raw = cached_call(
        cache_key,
        _STATEMENT_TTL_SECONDS,
        lambda: ak_retry(lambda: fetcher(symbol=prefixed)),
    )

    if raw is None or raw.empty:
        raise NoMarketDataError(symbol, prefixed, f"no {kind} data from AKShare")

    raw = raw.copy()
    raw["REPORT_DATE"] = pd.to_datetime(raw["REPORT_DATE"], errors="coerce")

    if curr_date:
        cutoff = pd.Timestamp(curr_date)
        raw = raw[raw["REPORT_DATE"] <= cutoff]
    if raw.empty:
        raise NoMarketDataError(
            symbol, prefixed, f"no {kind} periods on/before {curr_date}"
        )

    raw = raw.sort_values("REPORT_DATE", ascending=False)
    period_labels = raw["REPORT_DATE"].dt.strftime("%Y-%m-%d").tolist()

    line_items = raw.drop(columns=[c for c in _META_COLUMNS if c in raw.columns])
    line_items = line_items.drop(columns=["REPORT_DATE"])

    transposed = line_items.transpose()
    transposed.columns = period_labels
    # Drop line items that are empty across every reported period — these are
    # industry-specific fields (bank/insurance) that don't apply to this issuer.
    transposed = transposed.dropna(how="all")
    if transposed.empty:
        raise NoMarketDataError(symbol, prefixed, f"no populated {kind} line items")
    return transposed


def _statement_report(symbol: str, kind: str, title: str, freq: str, curr_date: str | None) -> str:
    """Shared serializer: build the CSV-with-header string for one statement."""
    label = display_symbol(symbol)
    data = _fetch_statement(symbol, kind, curr_date)
    csv_string = data.to_csv()
    header = f"# {title} for {label} (A-share, AKShare, {freq})\n"
    header += f"# Reporting currency: CNY · Periods shown: {len(data.columns)}\n"
    header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    return header + csv_string


def get_balance_sheet(
    ticker: Annotated[str, "A-share ticker (600519, 600519.SS, ...)"],
    freq: Annotated[str, "frequency hint, accepted for API parity"] = "quarterly",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
):
    """A-share balance sheet (资产负债表) as a CSV string with header."""
    if not is_a_share(ticker):
        raise NoMarketDataError(ticker, ticker, "not an A-share symbol for AKShare")
    if _is_etf_symbol(ticker):
        return _etf_statement_not_applicable(ticker, "Balance Sheet", freq)
    try:
        return _statement_report(ticker, "balance_sheet", "Balance Sheet", freq, curr_date)
    except NoMarketDataError:
        raise
    except Exception as e:
        return f"Error retrieving balance sheet for {ticker}: {str(e)}"


def get_income_statement(
    ticker: Annotated[str, "A-share ticker (600519, 600519.SS, ...)"],
    freq: Annotated[str, "frequency hint, accepted for API parity"] = "quarterly",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
):
    """A-share income statement (利润表) as a CSV string with header."""
    if not is_a_share(ticker):
        raise NoMarketDataError(ticker, ticker, "not an A-share symbol for AKShare")
    if _is_etf_symbol(ticker):
        return _etf_statement_not_applicable(ticker, "Income Statement", freq)
    try:
        return _statement_report(ticker, "income_statement", "Income Statement", freq, curr_date)
    except NoMarketDataError:
        raise
    except Exception as e:
        return f"Error retrieving income statement for {ticker}: {str(e)}"


def get_cashflow(
    ticker: Annotated[str, "A-share ticker (600519, 600519.SS, ...)"],
    freq: Annotated[str, "frequency hint, accepted for API parity"] = "quarterly",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
):
    """A-share cash flow statement (现金流量表) as a CSV string with header."""
    if not is_a_share(ticker):
        raise NoMarketDataError(ticker, ticker, "not an A-share symbol for AKShare")
    if _is_etf_symbol(ticker):
        return _etf_statement_not_applicable(ticker, "Cash Flow", freq)
    try:
        return _statement_report(ticker, "cashflow", "Cash Flow", freq, curr_date)
    except NoMarketDataError:
        raise
    except Exception as e:
        return f"Error retrieving cash flow for {ticker}: {str(e)}"


def get_fundamentals(
    ticker: Annotated[str, "A-share ticker (600519, 600519.SS, ...)"],
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
):
    """A-share fundamentals overview built from East Money financial ratios.

    Yahoo's overview (``info`` dict) is empty for A-shares, so we synthesize an
    equivalent ratio sheet from ``stock_financial_analysis_indicator`` (每股收益,
    净资产收益率, 利润率, 周转率, ...). Periods after ``curr_date`` are dropped to
    avoid look-ahead bias.
    """
    if not is_a_share(ticker):
        raise NoMarketDataError(ticker, ticker, "not an A-share symbol for AKShare")

    if _is_etf_symbol(ticker):
        return _format_etf_fundamentals(ticker, curr_date)

    code = to_bare_code(ticker)
    label = display_symbol(ticker)
    start_year = str((pd.Timestamp(curr_date) if curr_date else pd.Timestamp.today()).year - 2)

    try:
        data = cached_call(
            f"finratio_{code}_{start_year}",
            _STATEMENT_TTL_SECONDS,
            lambda: ak_retry(
                lambda: ak.stock_financial_analysis_indicator(symbol=code, start_year=start_year)
            ),
        )
    except Exception as e:
        return f"Error retrieving fundamentals for {ticker}: {str(e)}"

    if data is None or data.empty:
        raise NoMarketDataError(ticker, label, "no fundamental ratios from AKShare")

    data = data.copy()
    date_col = "日期" if "日期" in data.columns else data.columns[0]
    data[date_col] = pd.to_datetime(data[date_col], errors="coerce")
    data = data.dropna(subset=[date_col])

    if curr_date:
        data = data[data[date_col] <= pd.Timestamp(curr_date)]
    if data.empty:
        raise NoMarketDataError(ticker, label, f"no fundamental periods on/before {curr_date}")

    data = data.sort_values(date_col, ascending=False)
    period_labels = data[date_col].dt.strftime("%Y-%m-%d").tolist()
    ratios = data.drop(columns=[date_col]).transpose()
    ratios.columns = period_labels
    ratios = ratios.replace({"--": pd.NA}).dropna(how="all")
    if ratios.empty:
        raise NoMarketDataError(ticker, label, "no populated fundamental ratios")

    csv_string = ratios.to_csv()
    header = f"# Company Fundamentals for {label} (A-share, AKShare key ratios)\n"
    header += f"# Reporting currency: CNY · Periods shown: {len(period_labels)}\n"
    header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    return header + csv_string
