"""Backfill instrument_name for existing analysis_runs.

The instrument name (ETF / company full name) was historically only injected
into prompts, never persisted. This one-off script fills the new
``instrument_name`` column for old rows:

1. First parse the ``instrument_context`` string already saved in
   ``result_json`` (fast, offline).
2. If that yields nothing (older runs stored only a ticker-only context),
   fall back to resolving the name live via ``resolve_instrument_identity``
   — the same path the live pipeline uses (AKShare for A-shares, yfinance
   otherwise, subject to ``domestic_china_only``).

Best-effort throughout: unresolvable rows are simply left blank.

Run: ``.venv/bin/python scripts/backfill_instrument_names.py``
"""

import json
import re
import sqlite3
import sys
from pathlib import Path

# The name appears in build_instrument_context() output as:
#   "... Resolved identity: Company: <name>; ..." (more details follow), or
#   "... Resolved identity: Name: <name>. Do not substitute ..." (name is last/only).
_NAME_RE = re.compile(r"(?:Company|Name): (.+?)(?:; |\. Do not)")


def extract_name(result_json: str | None) -> str | None:
    if not result_json:
        return None
    try:
        ctx = json.loads(result_json).get("instrument_context")
    except (json.JSONDecodeError, AttributeError):
        return None
    if not isinstance(ctx, str):
        return None
    m = _NAME_RE.search(ctx)
    return m.group(1).strip() if m else None


def main() -> int:
    from api.main import DB_PATH
    from api.store import Store
    from tradingagents.agents.utils.agent_utils import resolve_instrument_identity
    from tradingagents.dataflows.config import set_config
    from tradingagents.default_config import DEFAULT_CONFIG

    if not Path(DB_PATH).exists():
        print(f"No database at {DB_PATH}; nothing to backfill.")
        return 0

    set_config(DEFAULT_CONFIG.copy())  # make AKShare / yfinance routing match the live pipeline
    store = Store(DB_PATH)  # runs the ALTER TABLE migration if needed
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT run_id, ticker, result_json FROM analysis_runs WHERE instrument_name IS NULL"
    ).fetchall()
    conn.close()

    filled = 0
    for r in rows:
        name = extract_name(r["result_json"])
        if not name:
            try:
                name = resolve_instrument_identity(r["ticker"]).get("company_name")
            except Exception as exc:  # noqa: BLE001 — best-effort, never abort the batch
                print(f"  {r['ticker']:<12} -> <resolve failed: {exc}>")
                name = None
        if name:
            store.set_instrument_name(r["run_id"], name)
            filled += 1
            print(f"  {r['ticker']:<12} -> {name}")

    print(f"Backfilled {filled}/{len(rows)} rows with a resolvable name.")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    sys.exit(main())
