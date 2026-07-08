from tradingagents.dataflows import config as dfconfig


class FakeStore:
    def get_snapshot(self, ticker, trade_date):
        return {"news": {"status": "ok", "payload": {"text": "SNAPSHOT NEWS"}, "fetched_at": "t"}}


def test_get_etf_news_uses_snapshot(monkeypatch):
    from tradingagents.agents.utils.news_data_tools import get_etf_news

    dfconfig.set_prefetch_ctx("510300.SS", "2026-07-07", FakeStore())
    try:
        out = get_etf_news.invoke(
            {"symbol": "510300.SS", "start_date": "2026-07-01", "end_date": "2026-07-07"}
        )
        assert "SNAPSHOT NEWS" in out
    finally:
        dfconfig.set_prefetch_ctx(None, None, None)


def test_get_news_uses_snapshot(monkeypatch):
    from tradingagents.agents.utils.news_data_tools import get_news

    dfconfig.set_prefetch_ctx("600519.SS", "2026-07-07", FakeStore())
    try:
        out = get_news.invoke(
            {"ticker": "600519.SS", "start_date": "2026-07-01", "end_date": "2026-07-07"}
        )
        assert "SNAPSHOT NEWS" in out
    finally:
        dfconfig.set_prefetch_ctx(None, None, None)
