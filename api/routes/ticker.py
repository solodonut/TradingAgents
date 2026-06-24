"""Ticker route: resolve a single code to its company name (read-only)."""

from fastapi import APIRouter

from tradingagents.dataflows.ticker_name import resolve_ticker_name

router = APIRouter(prefix="/api/ticker", tags=["ticker"])


@router.get("/{code}")
def lookup_ticker(code: str) -> dict:
    ticker = code.strip().upper()
    name = resolve_ticker_name(ticker)
    return {"ticker": ticker, "name": name, "valid": bool(name)}
