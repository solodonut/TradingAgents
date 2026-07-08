"""Startup endpoint cache clearing and progress reporting."""

from __future__ import annotations

import json
import queue
import threading
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import HTTPException, Request

StartupCacheStatus = Literal["pending", "running", "completed", "error"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class StartupCacheError:
    path: str
    message: str


@dataclass
class StartupCacheState:
    status: StartupCacheStatus = "pending"
    phase: str = "pending"
    message: str = "等待启动缓存清理"
    current_path: str | None = None
    processed_items: int = 0
    total_items: int = 0
    deleted_files: int = 0
    released_bytes: int = 0
    errors: list[StartupCacheError] = field(default_factory=list)
    started_at: str | None = None
    completed_at: str | None = None
    updated_at: str | None = None


class StartupCacheClearer:
    """Clear endpoint data caches once per API process startup."""

    def __init__(self, cache_root: str | Path, *, max_errors: int = 20):
        self.cache_root = Path(cache_root).expanduser()
        self._cache_root_resolved = self.cache_root.resolve(strict=False)
        self.max_errors = max_errors
        self._state = StartupCacheState()
        self._lock = threading.Lock()
        self._subscribers: list[queue.Queue[dict | None]] = []
        self._thread: threading.Thread | None = None
        self._running = False
        self._on_complete = None
        self._error_count = 0

    def start(self, *, on_complete=None) -> None:
        with self._lock:
            if self._is_active_locked():
                return
            self._on_complete = on_complete
            self._begin_run_locked()
            self._thread = threading.Thread(target=self._run_and_callback, daemon=True)
            self._thread.start()

    def run_sync(self) -> None:
        with self._lock:
            if self._is_active_locked():
                raise RuntimeError("startup cache clearer is already running")
            self._begin_run_locked()
        try:
            self._run()
        finally:
            with self._lock:
                self._running = False

    def _begin_run_locked(self) -> None:
        self._state = StartupCacheState(
            status="running", phase="scanning", message="正在扫描 endpoint 本地数据缓存"
        )
        self._running = True
        self._error_count = 0
        self._state.started_at = _now_iso()
        self._state.updated_at = self._state.started_at

    def _is_active_locked(self) -> bool:
        return self._running or (self._thread is not None and self._thread.is_alive())

    def _run(self) -> None:
        try:
            self._update(
                status="running",
                phase="scanning",
                message="正在扫描 endpoint 本地数据缓存",
                updated_at=_now_iso(),
            )
            targets = self._scan_targets()
            self._update(
                total_items=len(targets),
                phase="deleting",
                message="正在清理 endpoint 本地数据缓存",
                updated_at=_now_iso(),
            )

            for path in targets:
                rel = self._relative(path)
                self._update(current_path=rel, updated_at=_now_iso())
                try:
                    size = self._get_file_size(path)
                    path.unlink()
                    self._increment_success(size)
                except Exception as exc:  # noqa: BLE001 - report and continue
                    self._record_error(rel, str(exc))

            final_status: StartupCacheStatus = "error" if self._error_count else "completed"
            final_message = (
                "启动缓存清理失败，暂不能开始分析"
                if final_status == "error"
                else "启动缓存清理完成"
            )
            self._update(
                status=final_status,
                phase=final_status,
                message=final_message,
                current_path=None,
                completed_at=_now_iso(),
                updated_at=_now_iso(),
            )
        except Exception as exc:  # noqa: BLE001 - unexpected run failure must terminally fail
            self._record_terminal_error("startup", str(exc))
        finally:
            self._close_subscribers()
            with self._lock:
                self._running = False

    def snapshot(self) -> dict:
        with self._lock:
            return self._state_dict_locked()

    def is_ready(self) -> bool:
        return self.snapshot()["status"] == "completed"

    def subscribe(self) -> Iterator[dict]:
        q: queue.Queue[dict | None] = queue.Queue()
        with self._lock:
            self._subscribers.append(q)
            q.put({"event": "cache_clear_status", "data": self._state_dict_locked()})

        try:
            while True:
                item = q.get()
                if item is None:
                    break
                yield item
                data = item["data"]
                if data.get("status") in {"completed", "error"}:
                    yield {"event": "summary", "data": data}
                    break
        finally:
            with self._lock:
                if q in self._subscribers:
                    self._subscribers.remove(q)

    def _run_and_callback(self) -> None:
        try:
            self._run()
        finally:
            if self._on_complete is not None:
                self._on_complete(self.snapshot())

    def _scan_targets(self) -> list[Path]:
        if not self.cache_root.exists():
            return []

        targets: list[Path] = []
        for path in self.cache_root.rglob("*"):
            if path.is_symlink():
                continue
            if not path.is_file():
                continue
            if self._is_excluded(path):
                continue
            if not self._is_within_cache_root(path):
                continue
            targets.append(path)
        return sorted(targets)

    def _is_excluded(self, path: Path) -> bool:
        try:
            rel = path.relative_to(self.cache_root)
        except ValueError:
            return True
        return rel.parts[:1] == ("checkpoints",)

    def _relative(self, path: Path) -> str:
        try:
            return path.relative_to(self.cache_root).as_posix()
        except ValueError:
            return path.name

    def _is_within_cache_root(self, path: Path) -> bool:
        try:
            path.resolve(strict=False).relative_to(self._cache_root_resolved)
            return True
        except ValueError:
            return False

    def _get_file_size(self, path: Path) -> int:
        return path.stat().st_size

    def _increment_success(self, size: int) -> None:
        with self._lock:
            self._state.processed_items += 1
            self._state.deleted_files += 1
            self._state.released_bytes += size
            self._state.updated_at = _now_iso()
            data = self._state_dict_locked()
        self._publish(data)

    def _record_error(self, rel: str, message: str) -> None:
        with self._lock:
            self._error_count += 1
            self._state.processed_items += 1
            if len(self._state.errors) < self.max_errors:
                self._state.errors.append(StartupCacheError(path=rel, message=message))
            self._state.updated_at = _now_iso()
            data = self._state_dict_locked()
        self._publish(data)

    def _record_terminal_error(self, rel: str, message: str) -> None:
        with self._lock:
            self._error_count += 1
            self._state.status = "error"
            self._state.phase = "error"
            self._state.message = "启动缓存清理失败，暂不能开始分析"
            self._state.current_path = None
            self._state.completed_at = _now_iso()
            self._state.updated_at = self._state.completed_at
            if len(self._state.errors) < self.max_errors:
                self._state.errors.append(StartupCacheError(path=rel, message=message))
            data = self._state_dict_locked()
        self._publish(data)

    def _update(self, **changes) -> None:
        with self._lock:
            for key, value in changes.items():
                setattr(self._state, key, value)
            data = self._state_dict_locked()
        self._publish(data)

    def _state_dict_locked(self) -> dict:
        data = asdict(self._state)
        data["cache_root"] = str(self.cache_root)
        return data

    def _publish(self, data: dict) -> None:
        item = {"event": "cache_clear_status", "data": data}
        with self._lock:
            subscribers = list(self._subscribers)
        for subscriber in subscribers:
            subscriber.put(item)

    def _close_subscribers(self) -> None:
        with self._lock:
            subscribers = list(self._subscribers)
        for subscriber in subscribers:
            subscriber.put(None)


def get_startup_cache_clearer(request: Request) -> StartupCacheClearer | None:
    return getattr(request.app.state, "startup_cache_clearer", None)


def assert_startup_cache_ready(request: Request) -> None:
    clearer = get_startup_cache_clearer(request)
    if clearer is None:
        return
    state = clearer.snapshot()
    if state["status"] == "error":
        raise HTTPException(status_code=503, detail="启动缓存清理失败，暂不能开始分析")
    if state["status"] != "completed":
        raise HTTPException(status_code=503, detail="启动缓存清理未完成，暂不能开始分析")


def sse_json(item: dict) -> dict:
    return {"event": item["event"], "data": json.dumps(item["data"])}
