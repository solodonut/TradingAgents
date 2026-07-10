import time


def _wait_for_terminal_status(client):
    for _ in range(100):
        response = client.get("/api/cache/status")
        assert response.status_code == 200
        state = response.json()
        if state["status"] in {"completed", "error"}:
            return state
        time.sleep(0.01)
    raise AssertionError("manual cache clear did not finish")


def test_manual_cache_clear_deletes_checkpoints(client, tmp_path):
    checkpoint = tmp_path / "cache" / "checkpoints" / "510330.db"
    vendor_cache = tmp_path / "cache" / "tushare" / "fund_daily.pkl"
    checkpoint.parent.mkdir(parents=True)
    vendor_cache.parent.mkdir(parents=True)
    checkpoint.write_bytes(b"resume")
    vendor_cache.write_bytes(b"market")

    response = client.post("/api/cache/clear")

    assert response.status_code == 200
    state = _wait_for_terminal_status(client)
    assert state["status"] == "completed"
    assert not checkpoint.exists()
    assert not vendor_cache.exists()


def test_manual_cache_clear_rejects_active_analysis(client):
    import api.main as main

    main.app.state.run_lock.acquire()
    try:
        response = client.post("/api/cache/clear")
    finally:
        main.app.state.run_lock.release()

    assert response.status_code == 409
    assert response.json()["detail"] == "分析运行中，无法清除缓存"


def test_manual_cache_stream_emits_terminal_summary(client):
    assert client.post("/api/cache/clear").status_code == 200

    with client.stream("GET", "/api/cache/stream") as stream:
        body = "".join(stream.iter_text())

    assert "event: cache_clear_status" in body
    assert "event: summary" in body
