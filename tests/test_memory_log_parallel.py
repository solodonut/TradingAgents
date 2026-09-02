"""Memory log under parallel runs: two processes writing the same markdown file.

Parallel queue runs each live in their own process, so the log's read-modify-write
(``update_with_outcome``) has no in-process lock to protect it — before the file
lock, one process's reflection was silently overwritten by the other's.

Kept in its own module so the spawned children import only what they need.
"""

import multiprocessing as mp
import time

import pytest

from tradingagents.agents.utils.memory import TradingMemoryLog, _log_file_lock

DATE = "2026-01-15"
GROUP_A = ["AAA", "BBB", "CCC", "DDD", "EEE"]
GROUP_B = ["FFF", "GGG", "HHH", "III", "JJJ"]


def _log(path: str) -> TradingMemoryLog:
    return TradingMemoryLog({"memory_log_path": path})


def _store_all(path: str, tickers: list[str]) -> None:
    log = _log(path)
    for ticker in tickers:
        log.store_decision(ticker, DATE, f"Rating: Buy\nEnter {ticker} now.")


def _reflect_all(path: str, tickers: list[str]) -> None:
    log = _log(path)
    for ticker in tickers:
        log.update_with_outcome(
            ticker,
            DATE,
            raw_return=0.05,
            alpha_return=0.01,
            holding_days=5,
            reflection=f"reflection for {ticker}",
        )


def _reflect_one(path: str, ticker: str, ready) -> None:
    ready.set()
    _log(path).update_with_outcome(
        ticker,
        DATE,
        raw_return=0.05,
        alpha_return=0.01,
        holding_days=5,
        reflection=f"reflection for {ticker}",
    )


def _run_both(target, path, timeout=60):
    ctx = mp.get_context("spawn")
    procs = [
        ctx.Process(target=target, args=(str(path), group), daemon=True)
        for group in (GROUP_A, GROUP_B)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout)
        assert p.exitcode == 0, f"child failed with exit code {p.exitcode}"


@pytest.mark.unit
def test_parallel_processes_all_append_their_pending_entries(tmp_path):
    path = tmp_path / "trading_memory.md"

    _run_both(_store_all, path)

    text = path.read_text(encoding="utf-8")
    for ticker in GROUP_A + GROUP_B:
        assert f"| {ticker} |" in text
    assert text.count("| pending]") == 10


@pytest.mark.unit
def test_parallel_processes_do_not_lose_each_others_reflections(tmp_path):
    """The lost-update case: read-all/write-all from two processes at once."""
    path = tmp_path / "trading_memory.md"
    _store_all(str(path), GROUP_A + GROUP_B)

    _run_both(_reflect_all, path)

    text = path.read_text(encoding="utf-8")
    for ticker in GROUP_A + GROUP_B:
        assert f"reflection for {ticker}" in text
    assert "| pending]" not in text
    # entries are updated in place, never duplicated or dropped
    assert len(_log(str(path)).load_entries()) == 10


@pytest.mark.unit
def test_file_lock_holds_off_another_process(tmp_path):
    """The mechanism itself: while this process holds the lock, no one else writes."""
    path = tmp_path / "trading_memory.md"
    _store_all(str(path), ["AAA"])
    ctx = mp.get_context("spawn")
    ready = ctx.Event()
    proc = ctx.Process(target=_reflect_one, args=(str(path), "AAA", ready), daemon=True)

    with _log_file_lock(path):
        proc.start()
        assert ready.wait(timeout=60), "child never reached the update"
        time.sleep(0.3)  # it is now blocked on the lock, not merely slow
        assert proc.is_alive()
        assert "reflection for AAA" not in path.read_text(encoding="utf-8")

    proc.join(30)
    assert proc.exitcode == 0
    assert "reflection for AAA" in path.read_text(encoding="utf-8")


@pytest.mark.unit
def test_parallel_writes_leave_no_temp_files_behind(tmp_path):
    path = tmp_path / "trading_memory.md"
    _store_all(str(path), GROUP_A + GROUP_B)

    _run_both(_reflect_all, path)

    assert list(tmp_path.glob("*.tmp")) == []
