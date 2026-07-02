import pytest

from cli.batch_dashboard import BatchState


def _state():
    return BatchState([{"ticker": "AAPL", "name": "Apple"}, {"ticker": "btc-usd", "name": ""}])


@pytest.mark.unit
def test_init_normalizes_ticker_and_defaults_pending():
    s = _state()
    assert [r.ticker for r in s.rows] == ["AAPL", "BTC-USD"]
    assert all(r.status == "pending" for r in s.rows)
    assert not s.all_done()


@pytest.mark.unit
def test_set_run_map_links_run_ids():
    s = _state()
    s.set_run_map({"r1": "AAPL", "r2": "BTC-USD"})
    assert s.rows[0].run_id == "r1"
    assert s.rows[1].run_id == "r2"


@pytest.mark.unit
def test_mark_error_makes_row_terminal():
    s = _state()
    s.mark_error("AAPL")
    s.mark_error("BTC-USD")
    assert s.all_done()


@pytest.mark.unit
def test_apply_queue_sets_running_and_pending():
    s = _state()
    s.set_run_map({"r1": "AAPL", "r2": "BTC-USD"})
    s.apply_queue({
        "running": {"run_id": "r1", "ticker": "AAPL", "status": "running",
                    "queue_position": None, "created_at": "t"},
        "pending": [{"run_id": "r2", "ticker": "BTC-USD", "status": "pending",
                     "queue_position": 1, "created_at": "t"}],
    })
    assert s.current_running_id == "r1"
    assert s.rows[0].status == "running"
    assert s.rows[1].status == "pending"
    assert not s.all_done()


@pytest.mark.unit
def test_apply_history_fills_decision_and_terminal():
    s = _state()
    s.set_run_map({"r1": "AAPL", "r2": "BTC-USD"})
    s.apply_history([
        {"run_id": "r1", "ticker": "AAPL", "trade_date": "2026-07-02",
         "decision": "Buy", "status": "completed", "created_at": "t",
         "instrument_name": "Apple"},
        {"run_id": "r2", "ticker": "BTC-USD", "trade_date": "2026-07-02",
         "decision": None, "status": "error", "created_at": "t",
         "instrument_name": None},
    ])
    assert s.rows[0].status == "completed"
    assert s.rows[0].decision == "Buy"
    assert s.rows[1].status == "error"
    assert s.all_done()


@pytest.mark.unit
def test_apply_queue_ignores_unlinked_rows():
    s = _state()  # no run_map set
    s.apply_queue({"running": None, "pending": []})
    assert s.current_running_id is None
    assert all(r.status == "pending" for r in s.rows)


@pytest.mark.unit
def test_render_runs_without_error():
    import io

    from rich.console import Console

    s = _state()
    s.set_run_map({"r1": "AAPL"})
    s.apply_queue({"running": {"run_id": "r1", "ticker": "AAPL",
                               "status": "running", "queue_position": None,
                               "created_at": "t"}, "pending": []})
    s.apply_status({"last_report_section": "market_report", "llm_active": True,
                    "active_llm_calls": 1, "last_llm_model": "deepseek-chat",
                    "last_llm_error": None})
    Console(file=io.StringIO(), force_terminal=True).print(s.render())


@pytest.mark.unit
def test_render_no_running_shows_placeholder():
    import io

    from rich.console import Console

    s = _state()
    Console(file=io.StringIO(), force_terminal=True).print(s.render())
