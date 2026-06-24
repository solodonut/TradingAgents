import threading
import time
import types

import pytest

from api.scheduler import QueueScheduler
from api.store import Store


def _wait_until(predicate, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


class _FakeApp:
    """Minimal stand-in for FastAPI app with the state attrs scheduler touches."""

    def __init__(self, store, graph_factory):
        self._store = store
        self.state = types.SimpleNamespace(
            graph_factory=graph_factory,
            queues={},
            cancellations={},
            telemetry={},
            starting_telemetry=None,
        )


def _instant_factory(chunks_by_ticker):
    """graph_factory whose stream yields preset chunks then ends, per ticker."""

    def factory(req):
        chunks = chunks_by_ticker.get(req.ticker, [])

        class _Inner:
            def stream(inner_self, init_state, **kwargs):
                yield from chunks

        graph = types.SimpleNamespace(graph=_Inner())
        return graph, {}, "Hold", {"final_trade_decision": "**Rating**: Hold"}

    return factory


@pytest.fixture()
def scheduler_env(tmp_path, monkeypatch):
    store = Store(tmp_path / "sched.db")
    import api.main as main

    monkeypatch.setattr(main, "get_store", lambda: store)
    return store, main


def test_advance_starts_first_pending_and_chains(scheduler_env):
    store, main = scheduler_env
    factory = _instant_factory(
        {
            "NVDA": [{"market_report": "m"}, {"final_trade_decision": "**Rating**: Hold"}],
            "AAPL": [{"market_report": "m"}, {"final_trade_decision": "**Rating**: Hold"}],
        }
    )
    app = _FakeApp(store, factory)
    sched = QueueScheduler(app)

    store.enqueue_run("a", "NVDA", "2024-05-10", "stock", {"ticker": "NVDA", "trade_date": "2024-05-10"})
    store.enqueue_run("b", "AAPL", "2024-05-10", "stock", {"ticker": "AAPL", "trade_date": "2024-05-10"})

    sched.advance()

    assert _wait_until(lambda: store.get_status("a") == "completed")
    assert _wait_until(lambda: store.get_status("b") == "completed")


def test_advance_skips_failing_run(scheduler_env):
    store, main = scheduler_env

    def factory(req):
        if req.ticker == "BAD":
            class _Boom:
                def stream(inner_self, init_state, **kwargs):
                    raise RuntimeError("kaboom")
                    yield  # pragma: no cover

            return types.SimpleNamespace(graph=_Boom()), {}, None, None

        class _Ok:
            def stream(inner_self, init_state, **kwargs):
                yield {"final_trade_decision": "**Rating**: Hold"}

        return types.SimpleNamespace(graph=_Ok()), {}, "Hold", {"final_trade_decision": "x"}

    app = _FakeApp(store, factory)
    sched = QueueScheduler(app)

    store.enqueue_run("bad", "BAD", "2024-05-10", "stock", {"ticker": "BAD", "trade_date": "2024-05-10"})
    store.enqueue_run("ok", "OK", "2024-05-10", "stock", {"ticker": "OK", "trade_date": "2024-05-10"})

    sched.advance()

    assert _wait_until(lambda: store.get_status("bad") == "error")
    assert _wait_until(lambda: store.get_status("ok") == "completed")


def test_advance_skips_build_failure_run(scheduler_env):
    """Scheduler's own except branch: graph_factory raises → run marked error, next run completes."""
    store, main = scheduler_env

    def factory(req):
        if req.ticker == "BUILDFAIL":
            raise RuntimeError("build failed")

        class _Ok:
            def stream(inner_self, init_state, **kwargs):
                yield {"final_trade_decision": "**Rating**: Hold"}

        return types.SimpleNamespace(graph=_Ok()), {}, "Hold", {"final_trade_decision": "x"}

    app = _FakeApp(store, factory)
    sched = QueueScheduler(app)

    store.enqueue_run("bf", "BUILDFAIL", "2024-05-10", "stock", {"ticker": "BUILDFAIL", "trade_date": "2024-05-10"})
    store.enqueue_run("ok", "OK", "2024-05-10", "stock", {"ticker": "OK", "trade_date": "2024-05-10"})

    sched.advance()

    assert _wait_until(lambda: store.get_status("bf") == "error")
    assert _wait_until(lambda: store.get_status("ok") == "completed")


def test_cancel_then_advance_starts_next(scheduler_env):
    store, main = scheduler_env
    gate = threading.Event()

    def factory(req):
        if req.ticker == "FIRST":
            class _Gated:
                def stream(inner_self, init_state, **kwargs):
                    yield {"market_report": "m"}
                    gate.wait(timeout=3)
                    yield {"news_report": "n"}

            return types.SimpleNamespace(graph=_Gated()), {}, None, None

        class _Ok:
            def stream(inner_self, init_state, **kwargs):
                yield {"final_trade_decision": "**Rating**: Hold"}

        return types.SimpleNamespace(graph=_Ok()), {}, "Hold", {"final_trade_decision": "x"}

    app = _FakeApp(store, factory)
    sched = QueueScheduler(app)

    store.enqueue_run("f", "FIRST", "2024-05-10", "stock", {"ticker": "FIRST", "trade_date": "2024-05-10"})
    store.enqueue_run("s", "SECOND", "2024-05-10", "stock", {"ticker": "SECOND", "trade_date": "2024-05-10"})

    sched.advance()
    assert _wait_until(lambda: store.get_status("f") == "running")

    # cancel the first: set its cancel event + mark cancelled, then release the gate
    app.state.cancellations["f"].set()
    store.cancel_run("f", "cancelled by user")
    gate.set()

    assert _wait_until(lambda: store.get_status("f") == "cancelled")
    assert _wait_until(lambda: store.get_status("s") == "completed")
