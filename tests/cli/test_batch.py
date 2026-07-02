import pytest
import typer

from cli.api_client import ApiError
from cli.batch import (
    BatchSettings,
    analysts_for_asset_type,
    enqueue_watchlist,
    poll_until_done,
    run_batch,
)
from cli.batch_dashboard import BatchState


@pytest.mark.unit
def test_crypto_drops_fundamentals():
    assert analysts_for_asset_type(
        ["market", "social", "news", "fundamentals"], "crypto"
    ) == ["market", "social", "news"]


@pytest.mark.unit
def test_stock_keeps_all():
    assert analysts_for_asset_type(["market", "fundamentals"], "stock") == [
        "market", "fundamentals"
    ]


@pytest.mark.unit
def test_crypto_only_fundamentals_falls_back():
    # dropping would leave nothing -> keep original so server never 400s on empty
    assert analysts_for_asset_type(["fundamentals"], "crypto") == ["fundamentals"]


class FakeClient:
    def __init__(self, *, watchlist=None, queues=None, history=None,
                 enqueue_side=None, status=None):
        self._watchlist = watchlist or []
        self._queues = list(queues or [])
        self._history = history or []
        self._enqueue_side = enqueue_side  # dict ticker->resp or Exception
        self._status = status
        self.enqueue_calls = []

    def get_watchlist(self):
        return self._watchlist

    def enqueue(self, *, ticker, **kwargs):
        self.enqueue_calls.append((ticker, kwargs))
        if isinstance(self._enqueue_side, dict):
            val = self._enqueue_side.get(ticker.strip().upper())
            if isinstance(val, Exception):
                raise val
            return val or {"run_ids": [f"run-{ticker.strip().upper()}"]}
        return {"run_ids": [f"run-{ticker.strip().upper()}"]}

    def get_queue(self):
        return self._queues.pop(0) if self._queues else {"running": None, "pending": []}

    def get_history(self):
        return self._history

    def get_status(self, run_id):
        return self._status


def _settings():
    return BatchSettings(
        analysts=["market", "fundamentals"], research_depth=3,
        output_language="Chinese", trade_date="2026-07-02",
        llm_provider="deepseek", deep_think_llm="deepseek-reasoner",
        quick_think_llm="deepseek-chat",
    )


@pytest.mark.unit
def test_enqueue_watchlist_preserves_order_and_maps_run_ids():
    client = FakeClient()
    wl = [{"ticker": "AAPL", "name": "Apple"},
          {"ticker": "BTC-USD", "name": ""},
          {"ticker": "MSFT", "name": "Microsoft"}]
    run_map, failed = enqueue_watchlist(client, wl, _settings())
    assert failed == []
    assert [c[0] for c in client.enqueue_calls] == ["AAPL", "BTC-USD", "MSFT"]
    assert run_map == {"run-AAPL": "AAPL", "run-BTC-USD": "BTC-USD", "run-MSFT": "MSFT"}


@pytest.mark.unit
def test_enqueue_watchlist_crypto_drops_fundamentals():
    client = FakeClient()
    enqueue_watchlist(client, [{"ticker": "BTC-USD", "name": ""}], _settings())
    _, kwargs = client.enqueue_calls[0]
    assert kwargs["analysts"] == ["market"]        # fundamentals dropped for crypto
    assert kwargs["asset_type"] == "crypto"


@pytest.mark.unit
def test_enqueue_watchlist_records_failures():
    client = FakeClient(enqueue_side={"AAPL": ApiError("boom")})
    run_map, failed = enqueue_watchlist(
        client, [{"ticker": "AAPL", "name": ""}], _settings()
    )
    assert failed == ["AAPL"]
    assert run_map == {}


@pytest.mark.unit
def test_poll_until_done_advances_to_terminal():
    wl = [{"ticker": "AAPL", "name": "A"}, {"ticker": "MSFT", "name": "M"}]
    state = BatchState(wl)
    state.set_run_map({"run-AAPL": "AAPL", "run-MSFT": "MSFT"})
    queues = [
        {"running": {"run_id": "run-AAPL", "ticker": "AAPL", "status": "running",
                     "queue_position": None, "created_at": "t"},
         "pending": [{"run_id": "run-MSFT", "ticker": "MSFT", "status": "pending",
                      "queue_position": 1, "created_at": "t"}]},
        {"running": {"run_id": "run-MSFT", "ticker": "MSFT", "status": "running",
                     "queue_position": None, "created_at": "t"}, "pending": []},
        {"running": None, "pending": []},
    ]
    history = [
        {"run_id": "run-AAPL", "ticker": "AAPL", "trade_date": "t", "decision": "Buy",
         "status": "completed", "created_at": "t", "instrument_name": "A"},
        {"run_id": "run-MSFT", "ticker": "MSFT", "trade_date": "t", "decision": "Hold",
         "status": "completed", "created_at": "t", "instrument_name": "M"},
    ]
    client = FakeClient(queues=queues, history=history,
                        status={"last_report_section": "market_report"})
    poll_until_done(client, state, poll_interval=0, sleep=lambda _: None)
    assert state.all_done()
    assert state.rows[0].decision == "Buy"
    assert state.rows[1].decision == "Hold"


@pytest.mark.unit
def test_poll_until_done_survives_transient_api_error():
    state = BatchState([{"ticker": "AAPL", "name": "A"}])
    state.set_run_map({"run-AAPL": "AAPL"})

    class FlakyClient(FakeClient):
        def __init__(self):
            super().__init__(history=[
                {"run_id": "run-AAPL", "ticker": "AAPL", "trade_date": "t",
                 "decision": "Buy", "status": "completed", "created_at": "t",
                 "instrument_name": "A"}])
            self._first = True

        def get_queue(self):
            if self._first:
                self._first = False
                raise ApiError("transient")
            return {"running": None, "pending": []}

    poll_until_done(FlakyClient(), state, poll_interval=0, sleep=lambda _: None)
    assert state.all_done()


@pytest.mark.unit
def test_run_batch_exits_when_service_down(monkeypatch):
    def boom(self):
        raise ApiError("refused")
    monkeypatch.setattr("cli.batch.ApiClient.get_watchlist", boom)
    with pytest.raises(typer.Exit) as ei:
        run_batch()
    assert ei.value.exit_code == 1


@pytest.mark.unit
def test_run_batch_exits_when_watchlist_empty(monkeypatch):
    monkeypatch.setattr("cli.batch.ApiClient.get_watchlist", lambda self: [])
    with pytest.raises(typer.Exit) as ei:
        run_batch()
    assert ei.value.exit_code == 0


@pytest.mark.unit
def test_batch_command_registered():
    from cli.main import app

    names = {cmd.name for cmd in app.registered_commands}
    assert "batch" in names
