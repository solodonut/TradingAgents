"""SQLite-backed history store for WebUI analysis runs."""

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from api.schemas import HistorySummary, RunResult

_SCHEMA = """
CREATE TABLE IF NOT EXISTS analysis_runs (
    run_id        TEXT PRIMARY KEY,
    ticker        TEXT NOT NULL,
    trade_date    TEXT NOT NULL,
    asset_type    TEXT NOT NULL,
    decision      TEXT,
    status        TEXT NOT NULL,
    config_json   TEXT NOT NULL,
    result_json   TEXT,
    created_at    TEXT NOT NULL,
    completed_at  TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_default(value: Any) -> Any:
    """JSON fallback for LangGraph/LangChain objects in final_state."""
    if hasattr(value, "type") and hasattr(value, "content"):
        out = {
            "type": value.type,
            "content": value.content,
        }
        message_id = getattr(value, "id", None)
        if message_id:
            out["id"] = message_id
        return out
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return str(value)


def _dumps(value: Any) -> str:
    return json.dumps(value, default=_json_default, ensure_ascii=False)


class Store:
    def __init__(self, db_path: Path):
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def insert_run(
        self, run_id: str, ticker: str, trade_date: str, asset_type: str, config: dict
    ) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO analysis_runs "
                "(run_id, ticker, trade_date, asset_type, decision, status, "
                " config_json, result_json, created_at, completed_at) "
                "VALUES (?, ?, ?, ?, NULL, 'running', ?, NULL, ?, NULL)",
                (run_id, ticker, trade_date, asset_type, _dumps(config), _now()),
            )

    def complete_run(self, run_id: str, decision: str, result: dict) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE analysis_runs SET status='completed', decision=?, "
                "result_json=?, completed_at=? WHERE run_id=?",
                (decision, _dumps(result), _now(), run_id),
            )

    def mark_error(self, run_id: str, message: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE analysis_runs SET status='error', result_json=?, "
                "completed_at=? WHERE run_id=?",
                (_dumps({"error": message}), _now(), run_id),
            )

    def get_run(self, run_id: str) -> RunResult | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM analysis_runs WHERE run_id=?", (run_id,)
            ).fetchone()
        if row is None:
            return None
        return RunResult(
            run_id=row["run_id"],
            ticker=row["ticker"],
            trade_date=row["trade_date"],
            asset_type=row["asset_type"],
            decision=row["decision"],
            status=row["status"],
            config=json.loads(row["config_json"]),
            result=json.loads(row["result_json"]) if row["result_json"] else None,
            created_at=row["created_at"],
            completed_at=row["completed_at"],
        )

    def list_runs(self) -> list[HistorySummary]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT run_id, ticker, trade_date, decision, status, created_at "
                "FROM analysis_runs ORDER BY created_at DESC, rowid DESC"
            ).fetchall()
        return [
            HistorySummary(
                run_id=r["run_id"],
                ticker=r["ticker"],
                trade_date=r["trade_date"],
                decision=r["decision"],
                status=r["status"],
                created_at=r["created_at"],
            )
            for r in rows
        ]

    def delete_run(self, run_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM analysis_runs WHERE run_id=?", (run_id,))

    def has_running_run(self) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM analysis_runs WHERE status='running' LIMIT 1"
            ).fetchone()
        return row is not None
