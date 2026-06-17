from langchain_core.messages import AIMessage

from tradingagents.advisor.engine import run_chat


class _FakeChain:
    """Returns a scripted sequence of AIMessages on successive invokes."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.invocations = []

    def invoke(self, messages):
        self.invocations.append(messages)
        return self._responses.pop(0)


def test_run_chat_streams_tokens_when_no_tool_calls():
    chain = _FakeChain([AIMessage(content="持仓集中度偏高。不构成投资建议。")])
    events = list(
        run_chat(
            chain=chain,
            history_messages=[],
            user_message="该减仓吗?",
            tools_by_name={},
        )
    )
    kinds = [e["event"] for e in events]
    assert kinds[-1] == "done"
    token_text = "".join(
        e["data"]["content"] for e in events if e["event"] == "token"
    )
    assert "持仓集中度偏高" in token_text


def test_run_chat_executes_tool_then_answers():
    ai_with_tool = AIMessage(
        content="",
        tool_calls=[
            {"name": "get_stock_data", "args": {"symbol": "AAPL"}, "id": "tc1"}
        ],
    )
    ai_final = AIMessage(content="当前价已确认。不构成投资建议。")
    chain = _FakeChain([ai_with_tool, ai_final])

    def fake_tool(**kwargs):
        return "AAPL,2024-01-01,190.0"

    events = list(
        run_chat(
            chain=chain,
            history_messages=[],
            user_message="现在多少钱?",
            tools_by_name={"get_stock_data": fake_tool},
        )
    )
    kinds = [e["event"] for e in events]
    assert "tool_call" in kinds
    assert kinds[-1] == "done"
    tool_event = next(e for e in events if e["event"] == "tool_call")
    assert tool_event["data"]["tool"] == "get_stock_data"
    text = "".join(e["data"]["content"] for e in events if e["event"] == "token")
    assert "已确认" in text


def test_run_chat_done_carries_full_text_and_tool_calls():
    ai_with_tool = AIMessage(
        content="",
        tool_calls=[{"name": "get_news", "args": {"ticker": "AAPL"}, "id": "t1"}],
    )
    ai_final = AIMessage(content="结论。")
    chain = _FakeChain([ai_with_tool, ai_final])
    events = list(
        run_chat(
            chain=chain,
            history_messages=[],
            user_message="新闻?",
            tools_by_name={"get_news": lambda **k: "headline"},
        )
    )
    done = events[-1]
    assert done["event"] == "done"
    assert done["data"]["content"] == "结论。"
    assert done["data"]["tool_calls"][0]["tool"] == "get_news"
