"""Ticker route: resolve a single code to its company name + type (read-only)."""

from fastapi import APIRouter

from tradingagents.dataflows.ticker_name import resolve_ticker_name
from tradingagents.dataflows.tushare_utils import resolve_symbol_type

router = APIRouter(prefix="/api/ticker", tags=["ticker"])


@router.get("/{code}")
def lookup_ticker(code: str) -> dict:
    ticker = code.strip().upper()
    name = resolve_ticker_name(ticker)
    return {
        "ticker": ticker,
        "name": name,
        "valid": bool(name),
        "type": resolve_symbol_type(ticker),
    }
