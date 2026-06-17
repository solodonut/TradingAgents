import base64
import json

from langchain_core.messages import AIMessage

from tradingagents.advisor.vision import (
    build_vision_message,
    extract_holdings,
    parse_holdings_json,
)


class _FakeVisionLLM:
    def __init__(self, content):
        self._content = content

    def invoke(self, messages):
        return AIMessage(content=self._content)


def test_build_vision_message_has_image_and_text():
    msg = build_vision_message(b"\x89PNG\r\n", mime="image/png")
    blocks = msg.content
    types = {b["type"] for b in blocks}
    assert types == {"image_url", "text"}
    img = next(b for b in blocks if b["type"] == "image_url")
    assert img["image_url"]["url"].startswith("data:image/png;base64,")
    decoded = base64.b64decode(img["image_url"]["url"].split(",", 1)[1])
    assert decoded == b"\x89PNG\r\n"


def test_parse_holdings_json_plain_array():
    raw = json.dumps([{"ticker": "AAPL", "shares": 10, "weight": 40}])
    holdings = parse_holdings_json(raw)
    assert holdings[0].ticker == "AAPL"
    assert holdings[0].shares == 10


def test_parse_holdings_json_fenced_code_block():
    raw = "```json\n[{\"ticker\": \"MSFT\"}]\n```"
    holdings = parse_holdings_json(raw)
    assert holdings[0].ticker == "MSFT"


def test_parse_holdings_json_unparseable_returns_empty():
    assert parse_holdings_json("sorry, I can't read this image") == []


def test_extract_holdings_uses_llm():
    llm = _FakeVisionLLM(json.dumps([{"ticker": "AAPL", "shares": 5}]))
    holdings = extract_holdings(llm, b"img", mime="image/png")
    assert holdings[0].ticker == "AAPL"
