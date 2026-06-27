"""Watchlist routes: read/replace the persistent instrument list."""

from fastapi import APIRouter

from api.main import get_store
from api.schemas import WatchlistItem

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


@router.get("", response_model=list[WatchlistItem])
def get_watchlist() -> list[WatchlistItem]:
    store = get_store()
    return [WatchlistItem(**item) for item in store.get_watchlist()]


@router.put("", response_model=list[WatchlistItem])
def replace_watchlist(items: list[WatchlistItem]) -> list[WatchlistItem]:
    # 去重（保留首次出现），避免前端误传重复代码触发主键冲突。
    seen: set[str] = set()
    deduped: list[WatchlistItem] = []
    for item in items:
        if item.ticker in seen:
            continue
        seen.add(item.ticker)
        deduped.append(item)
    store = get_store()
    store.set_watchlist([item.model_dump() for item in deduped])
    return deduped
