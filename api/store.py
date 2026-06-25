"""SQLite-backed history store for WebUI analysis runs."""

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from api.schemas import (
    ChatMessage,
    ChatSession,
    HistorySummary,
    PortfolioHolding,
    QueueItem,
    QueueState,
    RunResult,
    SessionProfile,
)

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

CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id    TEXT PRIMARY KEY,
    run_id        TEXT,
    title         TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_session_runs (
    session_id TEXT NOT NULL,
    run_id     TEXT NOT NULL,
    position   INTEGER NOT NULL,
    PRIMARY KEY (session_id, run_id)
);

CREATE TABLE IF NOT EXISTS chat_messages (
    message_id      TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL,
    role            TEXT NOT NULL,
    content         TEXT NOT NULL,
    tool_calls_json TEXT,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_portfolios (
    session_id    TEXT PRIMARY KEY,
    holdings_json TEXT NOT NULL,
    source        TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_profiles (
    session_id   TEXT PRIMARY KEY,
    profile_json TEXT NOT NULL,
    updated_at   TEXT NOT NULL
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
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(analysis_runs)")}
            if "queue_position" not in cols:
                conn.execute("ALTER TABLE analysis_runs ADD COLUMN queue_position INTEGER")
            if "instrument_name" not in cols:
                conn.execute("ALTER TABLE analysis_runs ADD COLUMN instrument_name TEXT")

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

    def set_instrument_name(self, run_id: str, name: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE analysis_runs SET instrument_name=? WHERE run_id=?",
                (name, run_id),
            )

    def complete_run(self, run_id: str, decision: str, result: dict) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE analysis_runs SET status='completed', decision=?, "
                "result_json=?, completed_at=? WHERE run_id=? AND status='running'",
                (decision, _dumps(result), _now(), run_id),
            )

    def mark_error(self, run_id: str, message: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE analysis_runs SET status='error', result_json=?, "
                "completed_at=? WHERE run_id=? AND status='running'",
                (_dumps({"error": message}), _now(), run_id),
            )

    def cancel_run(self, run_id: str, reason: str = "cancelled by user") -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE analysis_runs SET status='cancelled', result_json=?, "
                "completed_at=? WHERE run_id=? AND status='running'",
                (_dumps({"cancelled": True, "reason": reason}), _now(), run_id),
            )
            return cur.rowcount > 0

    def update_partial_result(self, run_id: str, partial: dict) -> bool:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT result_json FROM analysis_runs WHERE run_id=? AND status='running'",
                (run_id,),
            ).fetchone()
            if row is None:
                return False
            current = json.loads(row["result_json"]) if row["result_json"] else {}
            current.update(partial)
            cur = conn.execute(
                "UPDATE analysis_runs SET result_json=? WHERE run_id=? AND status='running'",
                (_dumps(current), run_id),
            )
            return cur.rowcount > 0

    def get_status(self, run_id: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT status FROM analysis_runs WHERE run_id=?", (run_id,)
            ).fetchone()
        return None if row is None else row["status"]

    def _to_run_result(self, row: sqlite3.Row) -> RunResult:
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

    def get_run(self, run_id: str) -> RunResult | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM analysis_runs WHERE run_id=?", (run_id,)
            ).fetchone()
        if row is None:
            return None
        return self._to_run_result(row)

    def list_runs(self) -> list[HistorySummary]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT run_id, ticker, trade_date, decision, status, created_at, instrument_name "
                "FROM analysis_runs WHERE status != 'pending' "
                "ORDER BY created_at DESC, rowid DESC"
            ).fetchall()
        return [
            HistorySummary(
                run_id=r["run_id"],
                ticker=r["ticker"],
                trade_date=r["trade_date"],
                decision=r["decision"],
                status=r["status"],
                created_at=r["created_at"],
                instrument_name=r["instrument_name"],
            )
            for r in rows
        ]

    def delete_run(self, run_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM chat_session_runs WHERE run_id=?", (run_id,))
            conn.execute(
                "UPDATE chat_sessions SET run_id=NULL WHERE run_id=?", (run_id,)
            )
            conn.execute("DELETE FROM analysis_runs WHERE run_id=?", (run_id,))

    def has_running_run(self) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM analysis_runs WHERE status='running' LIMIT 1"
            ).fetchone()
        return row is not None

    def _to_queue_item(self, row: sqlite3.Row) -> QueueItem:
        return QueueItem(
            run_id=row["run_id"],
            ticker=row["ticker"],
            status=row["status"],
            queue_position=row["queue_position"],
            created_at=row["created_at"],
        )

    def enqueue_run(
        self, run_id: str, ticker: str, trade_date: str, asset_type: str, config: dict
    ) -> None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(queue_position), 0) AS m "
                "FROM analysis_runs WHERE status='pending'"
            ).fetchone()
            pos = row["m"] + 1
            conn.execute(
                "INSERT INTO analysis_runs "
                "(run_id, ticker, trade_date, asset_type, decision, status, "
                " config_json, result_json, created_at, completed_at, queue_position) "
                "VALUES (?, ?, ?, ?, NULL, 'pending', ?, NULL, ?, NULL, ?)",
                (run_id, ticker, trade_date, asset_type, _dumps(config), _now(), pos),
            )

    def start_run(self, run_id: str) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE analysis_runs SET status='running', queue_position=NULL "
                "WHERE run_id=? AND status='pending'",
                (run_id,),
            )
            return cur.rowcount > 0

    def next_pending(self) -> RunResult | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM analysis_runs WHERE status='pending' "
                "ORDER BY queue_position ASC, rowid ASC LIMIT 1"
            ).fetchone()
        return None if row is None else self._to_run_result(row)

    def list_queue(self) -> QueueState:
        with self._connect() as conn:
            running_row = conn.execute(
                "SELECT run_id, ticker, status, queue_position, created_at "
                "FROM analysis_runs WHERE status='running' "
                "ORDER BY created_at ASC LIMIT 1"
            ).fetchone()
            pending_rows = conn.execute(
                "SELECT run_id, ticker, status, queue_position, created_at "
                "FROM analysis_runs WHERE status='pending' "
                "ORDER BY queue_position ASC, rowid ASC"
            ).fetchall()
        return QueueState(
            running=self._to_queue_item(running_row) if running_row else None,
            pending=[self._to_queue_item(r) for r in pending_rows],
        )

    def remove_pending(self, run_id: str) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM analysis_runs WHERE run_id=? AND status='pending'",
                (run_id,),
            )
            return cur.rowcount > 0

    def clear_pending(self) -> int:
        with self._lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM analysis_runs WHERE status='pending'")
            return cur.rowcount

    def reorder_pending(self, ordered_run_ids: list[str]) -> None:
        with self._lock, self._connect() as conn:
            pending = {
                r["run_id"]
                for r in conn.execute(
                    "SELECT run_id FROM analysis_runs WHERE status='pending'"
                )
            }
            pos = 1
            for run_id in ordered_run_ids:
                if run_id in pending:
                    conn.execute(
                        "UPDATE analysis_runs SET queue_position=? "
                        "WHERE run_id=? AND status='pending'",
                        (pos, run_id),
                    )
                    pos += 1

    def reset_orphaned_runs(self) -> int:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE analysis_runs SET status='error', result_json=?, completed_at=? "
                "WHERE status='running'",
                (_dumps({"error": "服务重启中断"}), _now()),
            )
            return cur.rowcount

    # ---- chat sessions ----

    def create_chat_session(
        self,
        session_id: str,
        run_id: str | None,
        title: str | None,
        run_ids: list[str] | None = None,
    ) -> None:
        now = _now()
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO chat_sessions "
                "(session_id, run_id, title, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (session_id, run_id if run_ids is None else None, title, now, now),
            )
            if run_ids is not None:
                self._replace_chat_session_run_ids(conn, session_id, run_ids)

    def _chat_session_from_row(
        self, conn: sqlite3.Connection, row: sqlite3.Row
    ) -> ChatSession:
        association_rows = conn.execute(
            "SELECT run_id FROM chat_session_runs WHERE session_id=? "
            "ORDER BY position ASC",
            (row["session_id"],),
        ).fetchall()
        run_ids = [association["run_id"] for association in association_rows]
        if not run_ids and row["run_id"]:
            run_ids = [row["run_id"]]
        return ChatSession(
            session_id=row["session_id"],
            run_id=run_ids[0] if run_ids else None,
            run_ids=run_ids,
            title=row["title"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def get_chat_session(self, session_id: str) -> ChatSession | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM chat_sessions WHERE session_id=?", (session_id,)
            ).fetchone()
            if row is None:
                return None
            return self._chat_session_from_row(conn, row)

    def list_chat_sessions(self) -> list[ChatSession]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM chat_sessions ORDER BY updated_at DESC, rowid DESC"
            ).fetchall()
            return [self._chat_session_from_row(conn, row) for row in rows]

    def delete_chat_session(self, session_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM chat_messages WHERE session_id=?", (session_id,))
            conn.execute("DELETE FROM chat_portfolios WHERE session_id=?", (session_id,))
            conn.execute("DELETE FROM chat_profiles WHERE session_id=?", (session_id,))
            conn.execute("DELETE FROM chat_session_runs WHERE session_id=?", (session_id,))
            conn.execute("DELETE FROM chat_sessions WHERE session_id=?", (session_id,))

    def _replace_chat_session_run_ids(
        self, conn: sqlite3.Connection, session_id: str, run_ids: list[str]
    ) -> None:
        conn.execute("DELETE FROM chat_session_runs WHERE session_id=?", (session_id,))
        conn.executemany(
            "INSERT INTO chat_session_runs (session_id, run_id, position) "
            "VALUES (?, ?, ?)",
            [
                (session_id, run_id, position)
                for position, run_id in enumerate(run_ids)
            ],
        )
        conn.execute(
            "UPDATE chat_sessions SET run_id=NULL, updated_at=? WHERE session_id=?",
            (_now(), session_id),
        )

    def replace_chat_session_run_ids(
        self, session_id: str, run_ids: list[str]
    ) -> None:
        with self._lock, self._connect() as conn:
            self._replace_chat_session_run_ids(conn, session_id, run_ids)

    def rename_chat_session(self, session_id: str, title: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE chat_sessions SET title=?, updated_at=? WHERE session_id=?",
                (title.strip(), _now(), session_id),
            )

    def _touch_session(self, conn: sqlite3.Connection, session_id: str) -> None:
        conn.execute(
            "UPDATE chat_sessions SET updated_at=? WHERE session_id=?",
            (_now(), session_id),
        )

    # ---- chat messages ----

    def insert_chat_message(
        self,
        message_id: str,
        session_id: str,
        role: str,
        content: str,
        tool_calls: list[dict],
    ) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO chat_messages "
                "(message_id, session_id, role, content, tool_calls_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (message_id, session_id, role, content, _dumps(tool_calls), _now()),
            )
            self._touch_session(conn, session_id)

    def list_chat_messages(self, session_id: str) -> list[ChatMessage]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM chat_messages WHERE session_id=? "
                "ORDER BY created_at ASC, rowid ASC",
                (session_id,),
            ).fetchall()
        return [
            ChatMessage(
                message_id=r["message_id"],
                session_id=r["session_id"],
                role=r["role"],
                content=r["content"],
                tool_calls=json.loads(r["tool_calls_json"]) if r["tool_calls_json"] else [],
                created_at=r["created_at"],
            )
            for r in rows
        ]

    # ---- portfolio ----

    def save_portfolio(
        self, session_id: str, holdings: list[PortfolioHolding], source: str
    ) -> None:
        payload = [h.model_dump() for h in holdings]
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO chat_portfolios (session_id, holdings_json, source, updated_at) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(session_id) DO UPDATE SET "
                "holdings_json=excluded.holdings_json, source=excluded.source, "
                "updated_at=excluded.updated_at",
                (session_id, _dumps(payload), source, _now()),
            )
            self._touch_session(conn, session_id)

    def get_portfolio(
        self, session_id: str
    ) -> tuple[list[PortfolioHolding], str | None]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT holdings_json, source FROM chat_portfolios WHERE session_id=?",
                (session_id,),
            ).fetchone()
        if row is None:
            return [], None
        holdings = [PortfolioHolding(**h) for h in json.loads(row["holdings_json"])]
        return holdings, row["source"]

    # ---- session profile ----

    def save_session_profile(self, session_id: str, profile: SessionProfile) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO chat_profiles (session_id, profile_json, updated_at) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(session_id) DO UPDATE SET "
                "profile_json=excluded.profile_json, updated_at=excluded.updated_at",
                (session_id, _dumps(profile.model_dump()), _now()),
            )
            self._touch_session(conn, session_id)

    def get_session_profile(self, session_id: str) -> SessionProfile | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT profile_json FROM chat_profiles WHERE session_id=?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return SessionProfile(**json.loads(row["profile_json"]))
