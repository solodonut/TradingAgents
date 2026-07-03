from api.store import Store


def test_set_and_get_log_path(tmp_path):
    store = Store(tmp_path / "webui.db")
    store.enqueue_run(
        run_id="r1", ticker="SPY", trade_date="2026-07-03",
        asset_type="stock", config={},
    )
    assert store.get_log_path("r1") is None
    store.set_log_path("r1", "/tmp/x/SPY_1.jsonl")
    assert store.get_log_path("r1") == "/tmp/x/SPY_1.jsonl"


def test_get_log_path_unknown_run(tmp_path):
    store = Store(tmp_path / "webui.db")
    assert store.get_log_path("nope") is None
