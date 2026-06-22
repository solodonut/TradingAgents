from api.schemas import PortfolioHolding
from api.store import Store


def _completed_run(store: Store, run_id: str, ticker: str) -> None:
    store.insert_run(run_id, ticker, "2026-06-20", "stock", {})
    store.complete_run(run_id, "Hold", {"market_report": f"{ticker} report"})


def test_create_and_get_chat_session(tmp_path):
    store = Store(tmp_path / "t.db")
    store.create_chat_session("s1", run_id="r1", title="AAPL")
    s = store.get_chat_session("s1")
    assert s.session_id == "s1"
    assert s.run_id == "r1"
    assert s.title == "AAPL"


def test_list_chat_sessions_newest_first(tmp_path):
    store = Store(tmp_path / "t.db")
    store.create_chat_session("s1", run_id=None, title="one")
    store.create_chat_session("s2", run_id=None, title="two")
    ids = [s.session_id for s in store.list_chat_sessions()]
    assert ids[0] == "s2"


def test_insert_and_list_chat_messages(tmp_path):
    store = Store(tmp_path / "t.db")
    store.create_chat_session("s1", run_id=None, title=None)
    store.insert_chat_message("m1", "s1", "user", "hi", tool_calls=[])
    store.insert_chat_message(
        "m2", "s1", "assistant", "hello", tool_calls=[{"tool": "get_stock_data"}]
    )
    msgs = store.list_chat_messages("s1")
    assert [m.message_id for m in msgs] == ["m1", "m2"]
    assert msgs[1].tool_calls == [{"tool": "get_stock_data"}]


def test_save_and_get_portfolio_overwrites(tmp_path):
    store = Store(tmp_path / "t.db")
    store.create_chat_session("s1", run_id=None, title=None)
    store.save_portfolio(
        "s1", [PortfolioHolding(ticker="AAPL", shares=10)], source="vision"
    )
    store.save_portfolio(
        "s1", [PortfolioHolding(ticker="MSFT", shares=5)], source="manual"
    )
    holdings, source = store.get_portfolio("s1")
    assert source == "manual"
    assert [h.ticker for h in holdings] == ["MSFT"]


def test_get_portfolio_missing_returns_empty(tmp_path):
    store = Store(tmp_path / "t.db")
    store.create_chat_session("s1", run_id=None, title=None)
    holdings, source = store.get_portfolio("s1")
    assert holdings == []
    assert source is None


def test_delete_chat_session_cascades_messages(tmp_path):
    store = Store(tmp_path / "t.db")
    store.create_chat_session("s1", run_id=None, title=None)
    store.insert_chat_message("m1", "s1", "user", "hi", tool_calls=[])
    store.delete_chat_session("s1")
    assert store.get_chat_session("s1") is None
    assert store.list_chat_messages("s1") == []


def test_rename_chat_session_updates_title(tmp_path):
    store = Store(tmp_path / "t.db")
    store.create_chat_session("s1", run_id=None, title="old")
    store.rename_chat_session("s1", "新的会话名称")
    assert store.get_chat_session("s1").title == "新的会话名称"


def test_chat_session_persists_ordered_run_ids(tmp_path):
    store = Store(tmp_path / "t.db")
    _completed_run(store, "r1", "AAA")
    _completed_run(store, "r2", "BBB")
    store.create_chat_session("s1", run_id=None, title="pair", run_ids=["r2", "r1"])
    session = store.get_chat_session("s1")
    assert session.run_ids == ["r2", "r1"]
    assert session.run_id == "r2"


def test_replace_chat_session_run_ids_accepts_empty_selection(tmp_path):
    store = Store(tmp_path / "t.db")
    store.create_chat_session("s1", run_id="legacy", title=None)
    store.replace_chat_session_run_ids("s1", [])
    session = store.get_chat_session("s1")
    assert session.run_ids == []
    assert session.run_id is None


def test_legacy_chat_session_run_id_is_exposed_as_run_ids(tmp_path):
    store = Store(tmp_path / "t.db")
    store.create_chat_session("s1", run_id="legacy", title=None)
    assert store.get_chat_session("s1").run_ids == ["legacy"]


def test_deleting_run_removes_new_and_legacy_chat_associations(tmp_path):
    store = Store(tmp_path / "t.db")
    _completed_run(store, "r1", "AAA")
    _completed_run(store, "r2", "BBB")
    store.create_chat_session("new", run_id=None, title=None, run_ids=["r1"])
    store.create_chat_session("legacy", run_id="r2", title=None)
    store.delete_run("r1")
    store.delete_run("r2")
    assert store.get_chat_session("new").run_ids == []
    assert store.get_chat_session("legacy").run_ids == []


def test_chat_tables_coexist_with_existing_db(tmp_path):
    store = Store(tmp_path / "t.db")
    store.insert_run("r1", "NVDA", "2024-05-10", "stock", {})
    assert store.get_run("r1").status == "running"


from api.schemas import SessionProfile


def test_save_and_get_session_profile_overwrites(tmp_path):
    store = Store(tmp_path / "t.db")
    store.create_chat_session("s1", run_id=None, title=None)
    store.save_session_profile("s1", SessionProfile(available_capital=100000))
    store.save_session_profile(
        "s1", SessionProfile(available_capital=300000, risk_tolerance="balanced")
    )
    profile = store.get_session_profile("s1")
    assert profile.available_capital == 300000
    assert profile.risk_tolerance == "balanced"


def test_get_session_profile_missing_returns_none(tmp_path):
    store = Store(tmp_path / "t.db")
    store.create_chat_session("s1", run_id=None, title=None)
    assert store.get_session_profile("s1") is None


def test_delete_chat_session_cascades_profile(tmp_path):
    store = Store(tmp_path / "t.db")
    store.create_chat_session("s1", run_id=None, title=None)
    store.save_session_profile("s1", SessionProfile(available_capital=100000))
    store.delete_chat_session("s1")
    assert store.get_session_profile("s1") is None
