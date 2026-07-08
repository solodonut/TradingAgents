"""ETF snapshot routes: list snapshot dates and read one date's snapshot."""

from fastapi import APIRouter, Query

router = APIRouter(prefix="/api/etf", tags=["etf-snapshots"])


@router.get("/{ticker}/dates")
def etf_snapshot_dates(ticker: str) -> dict:
    from api.main import get_store

    return {"ticker": ticker, "dates": get_store().list_snapshot_dates(ticker)}


@router.get("/{ticker}/snapshot")
def etf_snapshot(ticker: str, date: str = Query(...)) -> dict:
    from api.main import get_store

    snap = get_store().get_snapshot(ticker, date)
    categories = {
        cat: {"status": v["status"], "payload": v["payload"]} for cat, v in snap.items()
    }
    return {"ticker": ticker, "trade_date": date, "categories": categories}
