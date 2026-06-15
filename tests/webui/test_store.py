import json

from api.store import Store


def test_insert_and_get_run(tmp_path):
    store = Store(tmp_path / "test.db")
    store.insert_run(
        run_id="r1",
        ticker="NVDA",
        trade_date="2024-05-10",
        asset_type="stock",
        config={"llm_provider": "openai"},
    )
    row = store.get_run("r1")
    assert row.status == "running"
    assert row.ticker == "NVDA"
    assert row.decision is None
    assert row.config == {"llm_provider": "openai"}


def test_complete_run_updates_decision_and_result(tmp_path):
    store = Store(tmp_path / "test.db")
    store.insert_run("r1", "NVDA", "2024-05-10", "stock", {})
    store.complete_run("r1", decision="Buy", result={"final_trade_decision": "x"})
    row = store.get_run("r1")
    assert row.status == "completed"
    assert row.decision == "Buy"
    assert row.result == {"final_trade_decision": "x"}
    assert row.completed_at is not None


def test_mark_error(tmp_path):
    store = Store(tmp_path / "test.db")
    store.insert_run("r1", "NVDA", "2024-05-10", "stock", {})
    store.mark_error("r1", "boom")
    row = store.get_run("r1")
    assert row.status == "error"


def test_list_runs_returns_summaries_newest_first(tmp_path):
    store = Store(tmp_path / "test.db")
    store.insert_run("r1", "AAPL", "2024-01-01", "stock", {})
    store.insert_run("r2", "NVDA", "2024-01-02", "stock", {})
    summaries = store.list_runs()
    assert [s.run_id for s in summaries] == ["r2", "r1"]


def test_delete_run(tmp_path):
    store = Store(tmp_path / "test.db")
    store.insert_run("r1", "NVDA", "2024-05-10", "stock", {})
    store.delete_run("r1")
    assert store.get_run("r1") is None


def test_has_running_run(tmp_path):
    store = Store(tmp_path / "test.db")
    assert store.has_running_run() is False
    store.insert_run("r1", "NVDA", "2024-05-10", "stock", {})
    assert store.has_running_run() is True
    store.complete_run("r1", decision="Hold", result={})
    assert store.has_running_run() is False
