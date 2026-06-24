"""Ticker route: resolve a single code to its company name (read-only)."""

from fastapi import APIRouter

from tradingagents.agents.utils.agent_utils import resolve_instrument_identity

router = APIRouter(prefix="/api/ticker", tags=["ticker"])


@router.get("/{code}")
def lookup_ticker(code: str) -> dict:
    ticker = code.strip().upper()
    identity = resolve_instrument_identity(ticker)
    name = identity.get("company_name")
    return {"ticker": ticker, "name": name, "valid": bool(name)}
