from api.schemas import PortfolioHolding
from api.store import Store


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


def test_chat_tables_coexist_with_existing_db(tmp_path):
    store = Store(tmp_path / "t.db")
    store.insert_run("r1", "NVDA", "2024-05-10", "stock", {})
    assert store.get_run("r1").status == "running"
