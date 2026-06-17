from langchain_core.messages import HumanMessage

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


def test_complete_run_serializes_langchain_messages(tmp_path):
    store = Store(tmp_path / "test.db")
    store.insert_run("r1", "NVDA", "2024-05-10", "stock", {})
    store.complete_run(
        "r1",
        decision="Buy",
        result={
            "final_trade_decision": "x",
            "messages": [HumanMessage(content="analyze NVDA", id="h1")],
        },
    )

    row = store.get_run("r1")
    assert row.status == "completed"
    assert row.result["messages"] == [
        {
            "type": "human",
            "content": "analyze NVDA",
            "id": "h1",
        }
    ]


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


def test_cancel_run_stops_running_gate_and_prevents_late_completion(tmp_path):
    store = Store(tmp_path / "test.db")
    store.insert_run("r1", "NVDA", "2024-05-10", "stock", {})

    store.cancel_run("r1", "stopped by user")

    row = store.get_run("r1")
    assert row.status == "cancelled"
    assert row.result == {"cancelled": True, "reason": "stopped by user"}
    assert store.has_running_run() is False

    store.complete_run("r1", decision="Buy", result={"final_trade_decision": "late"})
    row = store.get_run("r1")
    assert row.status == "cancelled"
    assert row.decision is None


def test_update_partial_result_preserves_running_status(tmp_path):
    store = Store(tmp_path / "test.db")
    store.insert_run("r1", "NVDA", "2024-05-10", "stock", {})

    store.update_partial_result("r1", {"market_report": "market"})
    store.update_partial_result("r1", {"news_report": "news"})

    row = store.get_run("r1")
    assert row.status == "running"
    assert row.result == {"market_report": "market", "news_report": "news"}


def test_update_partial_result_does_not_modify_finished_run(tmp_path):
    store = Store(tmp_path / "test.db")
    store.insert_run("r1", "NVDA", "2024-05-10", "stock", {})
    store.complete_run("r1", decision="Hold", result={"final_trade_decision": "done"})

    assert store.update_partial_result("r1", {"market_report": "late"}) is False

    row = store.get_run("r1")
    assert row.result == {"final_trade_decision": "done"}
