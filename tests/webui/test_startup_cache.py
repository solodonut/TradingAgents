import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException


def test_startup_cache_clearer_deletes_endpoint_cache_files(tmp_path):
    from api.startup_cache import StartupCacheClearer

    cache_root = tmp_path / "cache"
    ak_file = cache_root / "akshare" / "hist_600519.pkl"
    csv_file = cache_root / "NVDA-YFin-data-2020-01-01-2025-01-01.csv"
    checkpoint_file = cache_root / "checkpoints" / "NVDA.db"
    ak_file.parent.mkdir(parents=True)
    checkpoint_file.parent.mkdir(parents=True)
    ak_file.write_bytes(b"ak-cache")
    csv_file.write_text("Date,Close\n2026-07-08,1\n", encoding="utf-8")
    checkpoint_file.write_bytes(b"checkpoint")

    clearer = StartupCacheClearer(cache_root=cache_root)
    clearer.run_sync()

    state = clearer.snapshot()
    assert state["status"] == "completed"
    assert state["deleted_files"] == 2
    assert state["released_bytes"] >= len(b"ak-cache")
    assert not ak_file.exists()
    assert not csv_file.exists()
    assert checkpoint_file.exists()


def test_startup_cache_clearer_error_blocks_on_delete_failure(tmp_path, monkeypatch):
    from api.startup_cache import StartupCacheClearer

    cache_root = tmp_path / "cache"
    doomed = cache_root / "akshare" / "bad.pkl"
    survivor = cache_root / "NVDA-YFin-data-2020-01-01-2025-01-01.csv"
    doomed.parent.mkdir(parents=True)
    doomed.write_bytes(b"bad")
    survivor.write_text("Date,Close\n2026-07-08,1\n", encoding="utf-8")

    original_unlink = Path.unlink

    def fail_for_bad(self):
        if self == doomed:
            raise PermissionError("locked")
        return original_unlink(self)

    monkeypatch.setattr(Path, "unlink", fail_for_bad)

    clearer = StartupCacheClearer(cache_root=cache_root)
    clearer.run_sync()

    state = clearer.snapshot()
    assert state["status"] == "error"
    assert state["errors"] == [{"path": "akshare/bad.pkl", "message": "locked"}]
    assert state["processed_items"] == state["total_items"] == 2
    assert not survivor.exists()
    assert doomed.exists()


def test_startup_cache_clearer_scan_failure_ends_in_error_with_no_public_errors(tmp_path, monkeypatch):
    from api.startup_cache import StartupCacheClearer

    cache_root = tmp_path / "cache"
    cache_root.mkdir()

    clearer = StartupCacheClearer(cache_root=cache_root, max_errors=0)

    def boom():
        raise RuntimeError("scan exploded")

    monkeypatch.setattr(clearer, "_scan_targets", boom)

    clearer.run_sync()

    state = clearer.snapshot()
    assert state["status"] == "error"
    assert state["phase"] == "error"
    assert state["errors"] == []
    assert not clearer.is_ready()


def test_startup_cache_clearer_skips_symlink_targets(tmp_path):
    from api.startup_cache import StartupCacheClearer

    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("keep me", encoding="utf-8")
    symlink = cache_root / "akshare" / "outside-link.txt"
    symlink.parent.mkdir(parents=True)
    symlink.symlink_to(outside)

    clearer = StartupCacheClearer(cache_root=cache_root)
    clearer.run_sync()

    state = clearer.snapshot()
    assert state["status"] == "completed"
    assert symlink.exists()
    assert outside.exists()


def test_startup_cache_clearer_run_sync_rejects_live_background_run(tmp_path, monkeypatch):
    from api.startup_cache import StartupCacheClearer

    cache_root = tmp_path / "cache"
    target = cache_root / "akshare" / "held.pkl"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"held")

    scan_started = threading.Event()
    continue_scan = threading.Event()

    clearer = StartupCacheClearer(cache_root=cache_root)
    original_scan = clearer._scan_targets

    def blocked_scan():
        scan_started.set()
        continue_scan.wait(timeout=2)
        return original_scan()

    monkeypatch.setattr(clearer, "_scan_targets", blocked_scan)

    clearer.start()
    assert scan_started.wait(timeout=2)

    with pytest.raises(RuntimeError, match="already running"):
        clearer.run_sync()

    continue_scan.set()
    clearer._thread.join(timeout=2)

    assert clearer.snapshot()["status"] == "completed"


def test_startup_cache_clearer_file_size_failure_continues_remaining_files(tmp_path, monkeypatch):
    from api.startup_cache import StartupCacheClearer

    cache_root = tmp_path / "cache"
    doomed = cache_root / "akshare" / "bad.pkl"
    survivor = cache_root / "akshare" / "good.pkl"
    doomed.parent.mkdir(parents=True)
    doomed.write_bytes(b"bad")
    survivor.write_bytes(b"good")

    clearer = StartupCacheClearer(cache_root=cache_root)

    def fake_size(path):
        if path == doomed:
            raise FileNotFoundError("gone")
        return len(path.read_bytes())

    monkeypatch.setattr(clearer, "_get_file_size", fake_size)

    clearer.run_sync()

    state = clearer.snapshot()
    assert state["status"] == "error"
    assert state["processed_items"] == state["total_items"] == 2
    assert doomed.exists()
    assert not survivor.exists()
    assert state["errors"] == [{"path": "akshare/bad.pkl", "message": "gone"}]


def test_startup_cache_clearer_start_ignores_second_call_while_thread_alive(tmp_path):
    from api.startup_cache import StartupCacheClearer

    cache_root = tmp_path / "cache"
    target = cache_root / "akshare" / "held.pkl"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"held")

    callback_entered = threading.Event()
    release_callback = threading.Event()

    clearer = StartupCacheClearer(cache_root=cache_root)

    def on_complete(_state):
        callback_entered.set()
        release_callback.wait(timeout=2)

    clearer.start(on_complete=on_complete)
    assert callback_entered.wait(timeout=2)

    first_thread = clearer._thread
    assert first_thread is not None
    assert first_thread.is_alive()

    clearer.start()

    assert clearer._thread is first_thread

    release_callback.set()
    first_thread.join(timeout=2)

    assert clearer.snapshot()["status"] == "completed"


def test_assert_startup_cache_ready_blocks_until_completed(tmp_path):
    from api.startup_cache import StartupCacheClearer, assert_startup_cache_ready

    cache_root = tmp_path / "cache"
    cache_root.mkdir()

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))

    pending_clearer = StartupCacheClearer(cache_root=cache_root)
    request.app.state.startup_cache_clearer = pending_clearer

    with pytest.raises(HTTPException, match="启动缓存清理未完成"):
        assert_startup_cache_ready(request)

    completed_clearer = StartupCacheClearer(cache_root=cache_root)
    completed_clearer.run_sync()
    request.app.state.startup_cache_clearer = completed_clearer

    assert_startup_cache_ready(request)


def test_assert_startup_cache_ready_raises_specific_message_for_terminal_error(tmp_path, monkeypatch):
    from api.startup_cache import StartupCacheClearer, assert_startup_cache_ready

    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    clearer = StartupCacheClearer(cache_root=cache_root)

    def boom():
        raise RuntimeError("scan exploded")

    monkeypatch.setattr(clearer, "_scan_targets", boom)
    clearer.run_sync()
    request.app.state.startup_cache_clearer = clearer

    with pytest.raises(HTTPException, match="启动缓存清理失败"):
        assert_startup_cache_ready(request)


def test_startup_cache_status_route(client, tmp_path):
    import api.main as main
    from api.startup_cache import StartupCacheClearer

    clearer = StartupCacheClearer(tmp_path / "cache")
    clearer.run_sync()
    main.app.state.startup_cache_clearer = clearer

    resp = client.get("/api/startup-cache/status")

    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"


def test_startup_cache_status_route_returns_503_when_uninitialized(client):
    import api.main as main

    main.app.state.startup_cache_clearer = None

    resp = client.get("/api/startup-cache/status")

    assert resp.status_code == 503
    assert resp.json()["detail"] == "startup cache clearer not initialized"


def test_startup_cache_stream_route(client, tmp_path):
    import api.main as main
    from api.startup_cache import StartupCacheClearer

    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    (cache_root / "one.csv").write_text("x", encoding="utf-8")
    clearer = StartupCacheClearer(cache_root)
    clearer.run_sync()
    main.app.state.startup_cache_clearer = clearer

    with client.stream("GET", "/api/startup-cache/stream") as stream:
        body = "".join(stream.iter_text())

    assert "event: cache_clear_status" in body
    assert "event: summary" in body
    assert '"status": "completed"' in body


def test_startup_cache_stream_route_returns_503_when_uninitialized(client):
    import api.main as main

    main.app.state.startup_cache_clearer = None

    resp = client.get("/api/startup-cache/stream")

    assert resp.status_code == 503
    assert resp.json()["detail"] == "startup cache clearer not initialized"


def test_sse_json_wraps_payload_as_json_string():
    from api.startup_cache import sse_json

    payload = {"event": "cache_clear_status", "data": {"status": "completed"}}
    wrapped = sse_json(payload)

    assert wrapped["event"] == "cache_clear_status"
    assert wrapped["data"] == json.dumps({"status": "completed"})
