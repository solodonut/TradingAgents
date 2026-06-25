import logging
from typing import Annotated

from langchain_core.tools import tool

from tradingagents.dataflows.errors import NoMarketDataError
from tradingagents.dataflows.interface import _NETWORK_ERRORS
from tradingagents.dataflows.market_data_validator import build_verified_market_snapshot

logger = logging.getLogger(__name__)


@tool
def get_verified_market_snapshot(
    symbol: Annotated[str, "ticker symbol of the company"],
    curr_date: Annotated[str, "the current trading date, YYYY-mm-dd"],
    look_back_days: Annotated[
        int, "number of recent trading rows to include for sanity-checking"
    ] = 30,
) -> str:
    """Deterministic verification snapshot for exact market-data claims.

    Returns the latest OHLCV row on or before curr_date, common technical
    indicators, and recent closes. Call this before making exact claims about
    price levels, Bollinger bands, RSI, MACD, moving averages, support /
    resistance, or historical comparisons, and treat it as the source of truth.
    """
    # This is an agent-facing tool, so it must honor the data layer's
    # "never raises" contract (see dataflows/interface.py::route_to_vendor).
    # The underlying fetch (load_ohlcv -> AKShare/yfinance) can raise a
    # transient network error (East Money RemoteDisconnected), NoMarketDataError
    # (no/stale rows), or ValueError (no rows on/before the date). If any of
    # those escaped this tool they would propagate through the LangGraph
    # ToolNode and abort the whole run via api/runner.py. Translate them into a
    # sentinel string so the analyst reports unavailability and keeps going
    # instead of crashing or fabricating numbers.
    try:
        return build_verified_market_snapshot(symbol, curr_date, look_back_days)
    except _NETWORK_ERRORS as exc:
        logger.warning(
            "Verified market snapshot for %s unreachable (network error): %s",
            symbol, exc,
        )
        reason = f"network/connectivity error ({type(exc).__name__})"
    except NoMarketDataError as exc:
        logger.warning("Verified market snapshot for %s has no usable data: %s", symbol, exc)
        reason = exc.detail or "no usable rows"
    except Exception as exc:  # noqa: BLE001 — never let this tool crash the run
        logger.warning("Verified market snapshot for %s failed: %s", symbol, exc)
        reason = f"{type(exc).__name__}: {exc}"

    return (
        f"MARKET_SNAPSHOT_UNAVAILABLE: Could not build a verified market-data "
        f"snapshot for '{symbol}' on {curr_date} ({reason}). The data source may "
        f"be unreachable or have no usable rows for this symbol. Do not fabricate "
        f"OHLCV, price-level, or indicator values — rely on other tool outputs and "
        f"state that verified-snapshot data is unavailable."
    )
