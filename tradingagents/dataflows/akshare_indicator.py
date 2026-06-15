"""AKShare A-share technical indicators via stockstats.

The Yahoo indicator path (``y_finance.get_stock_stats_indicators_window``) hard-
wires ``load_ohlcv`` -> yfinance. A-shares need the same stockstats computation
but fed from AKShare OHLCV, so this module reuses the EXACT same indicator
catalog, look-back-window logic, and output string format — only the data
source differs. Keeping the catalog text identical means the agent prompts read
the same regardless of market.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

import pandas as pd
from dateutil.relativedelta import relativedelta
from stockstats import wrap

from .akshare_stock import _fetch_hist, _normalize_frame
from .akshare_utils import is_a_share, to_bare_code
from .errors import NoMarketDataError

# Supported indicators — same set as the Yahoo path's ``best_ind_params``.
_SUPPORTED = (
    "close_50_sma", "close_200_sma", "close_10_ema",
    "macd", "macds", "macdh",
    "rsi", "boll", "boll_ub", "boll_lb", "atr", "vwma", "mfi",
)


def _load_akshare_ohlcv(symbol: str, curr_date: str) -> pd.DataFrame:
    """Load 5y of A-share OHLCV up to curr_date, look-ahead filtered.

    Mirrors ``stockstats_utils.load_ohlcv`` semantics: a fixed 5-year window so
    indicators have enough history for 200-period averages, then rows after
    curr_date are dropped to prevent look-ahead bias in backtests. The frame is
    returned with a ``Date`` column (not index) because stockstats' ``wrap``
    and the window loop below expect that shape.
    """
    code = to_bare_code(symbol)
    curr_dt = pd.to_datetime(curr_date)
    start = (curr_dt - pd.DateOffset(years=5)).strftime("%Y-%m-%d")
    end = curr_dt.strftime("%Y-%m-%d")

    raw = _fetch_hist(code, start, end)
    if raw is None or raw.empty:
        raise NoMarketDataError(symbol, symbol, "AKShare returned no rows for indicators")

    data = _normalize_frame(raw).reset_index()
    data = data[data["Date"] <= curr_dt]
    if data.empty:
        raise NoMarketDataError(symbol, symbol, "no A-share rows on/before curr_date")
    return data


def _bulk_indicator(symbol: str, indicator: str, curr_date: str) -> dict:
    """Compute ``indicator`` for every available date; return {date_str: value}."""
    data = _load_akshare_ohlcv(symbol, curr_date)
    df = wrap(data)
    df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")
    df[indicator]  # trigger stockstats calculation
    result = {}
    for _, row in df.iterrows():
        value = row[indicator]
        result[row["Date"]] = "N/A" if pd.isna(value) else str(value)
    return result


def get_indicators(
    symbol: Annotated[str, "A-share ticker (600519, 600519.SS, ...)"],
    indicator: Annotated[str, "technical indicator to get the analysis and report of"],
    curr_date: Annotated[str, "The current trading date you are trading on, YYYY-mm-dd"],
    look_back_days: Annotated[int, "how many days to look back"],
) -> str:
    """Return per-day indicator values over the look-back window for an A-share.

    Same signature and output format as
    ``y_finance.get_stock_stats_indicators_window`` so the router can swap
    vendors transparently. The trailing indicator description is taken verbatim
    from the Yahoo catalog by computing a one-day window on a thrown-away symbol
    is avoided — instead we keep an explicit supported list and reuse the shared
    description text embedded in the Yahoo function's output.
    """
    if not is_a_share(symbol):
        raise NoMarketDataError(symbol, symbol, "not an A-share symbol for AKShare")
    if indicator not in _SUPPORTED:
        raise ValueError(
            f"Indicator {indicator} is not supported. Please choose from: {list(_SUPPORTED)}"
        )

    end_date = curr_date
    curr_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    before = curr_dt - relativedelta(days=look_back_days)

    indicator_data = _bulk_indicator(symbol, indicator, curr_date)

    cursor = curr_dt
    ind_string = ""
    while cursor >= before:
        date_str = cursor.strftime("%Y-%m-%d")
        value = indicator_data.get(date_str, "N/A: Not a trading day (weekend or holiday)")
        ind_string += f"{date_str}: {value}\n"
        cursor = cursor - relativedelta(days=1)

    # Reuse the Yahoo catalog's description for this indicator by extracting the
    # tail of a minimal Yahoo-format string. We avoid a second network call by
    # reconstructing only the description block, which lives in the Yahoo
    # module's local dict; pull it via the function's closure-free constant.
    description = _indicator_description(indicator)

    return (
        f"## {indicator} values from {before.strftime('%Y-%m-%d')} to {end_date}:\n\n"
        + ind_string
        + "\n\n"
        + description
    )


def _indicator_description(indicator: str) -> str:
    """Return the shared human description for an indicator.

    Mirrors the ``best_ind_params`` catalog in ``y_finance``. Kept here as the
    single fallback so the A-share report footer matches the US one word-for-word.
    """
    catalog = {
        "close_50_sma": (
            "50 SMA: A medium-term trend indicator. "
            "Usage: Identify trend direction and serve as dynamic support/resistance. "
            "Tips: It lags price; combine with faster indicators for timely signals."
        ),
        "close_200_sma": (
            "200 SMA: A long-term trend benchmark. "
            "Usage: Confirm overall market trend and identify golden/death cross setups. "
            "Tips: It reacts slowly; best for strategic trend confirmation rather than frequent trading entries."
        ),
        "close_10_ema": (
            "10 EMA: A responsive short-term average. "
            "Usage: Capture quick shifts in momentum and potential entry points. "
            "Tips: Prone to noise in choppy markets; use alongside longer averages for filtering false signals."
        ),
        "macd": (
            "MACD: Computes momentum via differences of EMAs. "
            "Usage: Look for crossovers and divergence as signals of trend changes. "
            "Tips: Confirm with other indicators in low-volatility or sideways markets."
        ),
        "macds": (
            "MACD Signal: An EMA smoothing of the MACD line. "
            "Usage: Use crossovers with the MACD line to trigger trades. "
            "Tips: Should be part of a broader strategy to avoid false positives."
        ),
        "macdh": (
            "MACD Histogram: Shows the gap between the MACD line and its signal. "
            "Usage: Visualize momentum strength and spot divergence early. "
            "Tips: Can be volatile; complement with additional filters in fast-moving markets."
        ),
        "rsi": (
            "RSI: Measures momentum to flag overbought/oversold conditions. "
            "Usage: Apply 70/30 thresholds and watch for divergence to signal reversals. "
            "Tips: In strong trends, RSI may remain extreme; always cross-check with trend analysis."
        ),
        "boll": (
            "Bollinger Middle: A 20 SMA serving as the basis for Bollinger Bands. "
            "Usage: Acts as a dynamic benchmark for price movement. "
            "Tips: Combine with the upper and lower bands to effectively spot breakouts or reversals."
        ),
        "boll_ub": (
            "Bollinger Upper Band: Typically 2 standard deviations above the middle line. "
            "Usage: Signals potential overbought conditions and breakout zones. "
            "Tips: Confirm signals with other tools; prices may ride the band in strong trends."
        ),
        "boll_lb": (
            "Bollinger Lower Band: Typically 2 standard deviations below the middle line. "
            "Usage: Indicates potential oversold conditions. "
            "Tips: Use additional analysis to avoid false reversal signals."
        ),
        "atr": (
            "ATR: Averages true range to measure volatility. "
            "Usage: Set stop-loss levels and adjust position sizes based on current market volatility. "
            "Tips: It's a reactive measure, so use it as part of a broader risk management strategy."
        ),
        "vwma": (
            "VWMA: A moving average weighted by volume. "
            "Usage: Confirm trends by integrating price action with volume data. "
            "Tips: Watch for skewed results from volume spikes; use in combination with other volume analyses."
        ),
        "mfi": (
            "MFI: The Money Flow Index is a momentum indicator that uses both price and volume to measure buying and selling pressure. "
            "Usage: Identify overbought (>80) or oversold (<20) conditions and confirm the strength of trends or reversals. "
            "Tips: Use alongside RSI or MACD to confirm signals; divergence between price and MFI can indicate potential reversals."
        ),
    }
    return catalog.get(indicator, "No description available.")
