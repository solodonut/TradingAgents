"""Deterministic market-data verification snapshot.

The market analyst is an LLM that can confabulate exact numbers — citing a
Bollinger band or a "historically validated bounce" that the underlying data
doesn't support (#830). This module computes a ground-truth snapshot (latest
OHLCV row on or before the analysis date, common indicators, recent closes)
the analyst is told to treat as the source of truth for any exact numeric
claim. Deterministic, no LLM involved.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

import pandas as pd
from stockstats import wrap

from tradingagents.dataflows.akshare_indicator import _load_akshare_ohlcv
from tradingagents.dataflows.akshare_utils import is_a_share
from tradingagents.dataflows.amazingdata_indicator import (
    _load_ohlcv as _load_amazingdata_ohlcv,
)
from tradingagents.dataflows.errors import NoMarketDataError
from tradingagents.dataflows.stockstats_utils import load_ohlcv
from tradingagents.dataflows.tushare_indicator import _load_tushare_ohlcv

logger = logging.getLogger(__name__)

# A fixed, common indicator set so the snapshot is the same shape every run.
DEFAULT_SNAPSHOT_INDICATORS: tuple[str, ...] = (
    "close_10_ema", "close_50_sma", "close_200_sma",
    "rsi", "boll", "boll_ub", "boll_lb",
    "macd", "macds", "macdh", "atr",
)


class SnapshotVendorChainError(RuntimeError):
    """Every mainland snapshot vendor failed to return usable OHLCV."""


def _load_mainland_ohlcv(symbol: str, curr_date: str) -> tuple[pd.DataFrame, str]:
    """Load mainland OHLCV in the fixed verification-source order."""
    loaders = (
        ("AmazingData", _load_amazingdata_ohlcv),
        ("Tushare", _load_tushare_ohlcv),
        ("AKShare", _load_akshare_ohlcv),
    )
    failures = []
    for source, loader in loaders:
        try:
            data = loader(symbol, curr_date)
            if data is None or data.empty:
                raise NoMarketDataError(symbol, symbol, f"{source} returned no rows")
            return data, source
        except Exception as exc:  # noqa: BLE001 - one vendor failure must fall through
            logger.warning(
                "Verified snapshot source %s failed for %s: %s",
                source,
                symbol,
                exc,
            )
            failures.append(f"{source}={type(exc).__name__}: {exc}")

    raise SnapshotVendorChainError(
        "All verified snapshot sources failed in order "
        f"AmazingData -> Tushare -> AKShare ({'; '.join(failures)})"
    )


def _verified_rows(symbol: str, curr_date: str) -> tuple[pd.DataFrame, str]:
    """OHLCV on or before curr_date, date-sorted. Raises if nothing usable.

    Mainland instruments use the fixed AmazingData -> Tushare -> AKShare
    verification chain. Other markets keep the existing Yahoo-backed loader.
    Every loader already filters look-ahead rows, but we re-apply the cutoff
    defensively because this verification path must not trust its input.
    """
    if is_a_share(symbol):
        data, source = _load_mainland_ohlcv(symbol, curr_date)
    else:
        data, source = load_ohlcv(symbol, curr_date), "Yahoo Finance"
    if data is None or data.empty:
        raise ValueError(f"No OHLCV data available for {symbol}.")

    df = data.copy()
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.dropna(subset=["Date"])
    df = df[df["Date"] <= pd.to_datetime(curr_date)].sort_values("Date")
    if df.empty:
        raise ValueError(f"No OHLCV rows on or before {curr_date} for {symbol}.")
    return df, source


def _fmt(value) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int,)):
        return str(value)
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def build_verified_market_snapshot(
    symbol: str,
    curr_date: str,
    look_back_days: int = 30,
    indicators: Iterable[str] | None = None,
) -> str:
    """Render a ground-truth snapshot: latest OHLCV row, indicators, recent closes."""
    # `df` keeps the original capitalized OHLCV columns (Open/High/Low/Close/
    # Volume); stockstats `wrap()` lowercases columns and adds indicator
    # columns, so read raw prices from `df` and indicators from `stock_df`.
    df, source = _verified_rows(symbol, curr_date)
    stock_df = wrap(df.copy())

    selected = tuple(indicators or DEFAULT_SNAPSHOT_INDICATORS)
    indicator_values: dict[str, str] = {}
    for name in selected:
        try:
            stock_df[name]  # triggers stockstats calculation
            indicator_values[name] = _fmt(stock_df.iloc[-1][name])
        except Exception as exc:  # noqa: BLE001 — one bad indicator shouldn't sink the snapshot
            indicator_values[name] = f"N/A ({type(exc).__name__})"

    latest = df.iloc[-1]
    latest_date = _fmt(latest["Date"])
    window = max(1, min(int(look_back_days), 30))
    recent = df.tail(window)

    lines = [
        f"## Verified market data snapshot for {symbol.upper()}",
        "",
        f"- Requested analysis date: {curr_date}",
        f"- Latest trading row used: {latest_date}",
        f"- Data source used: {source}",
        "- Rows after the requested analysis date are excluded before verification.",
        "",
        "### Latest verified OHLCV row",
        "",
        "| Field | Value |",
        "|---|---:|",
    ]
    for field in ("Open", "High", "Low", "Close", "Volume"):
        lines.append(f"| {field} | {_fmt(latest.get(field))} |")

    lines += ["", "### Verified technical indicators (latest row)", "",
              "| Indicator | Value |", "|---|---:|"]
    for name, value in indicator_values.items():
        lines.append(f"| {name} | {value} |")

    lines += ["", f"### Recent verified closes (last {len(recent)} rows)", "",
              "| Date | Close |", "|---|---:|"]
    for _, row in recent.iterrows():
        lines.append(f"| {_fmt(row['Date'])} | {_fmt(row.get('Close'))} |")

    lines += [
        "",
        "Use this snapshot as the source of truth for exact OHLCV, price-level, "
        "and indicator-value claims. If another tool output conflicts with it, "
        "flag the discrepancy rather than inventing a reconciled number. Do not "
        "claim historical validation, support/resistance bounces, or exact "
        "percentage moves unless directly supported by tool output with concrete "
        "dates and prices.",
    ]
    return "\n".join(lines)
