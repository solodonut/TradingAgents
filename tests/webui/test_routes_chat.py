import json

from langchain_core.messages import AIMessage


def _install_fake_chat(client, chat_responses, vision_content="[]"):
    import api.main as main

    class _FakeChain:
        def __init__(self, responses):
            self._responses = list(responses)

        def invoke(self, messages):
            return self._responses.pop(0)

    class _FakeLLM:
        def __init__(self, chain, vision_content):
            self._chain = chain
            self._vision_content = vision_content

        def bind_tools(self, tools):
            return self._chain

        def invoke(self, messages):  # vision path
            return AIMessage(content=self._vision_content)

    def factory():
        chain = _FakeChain(chat_responses)
        llm = _FakeLLM(chain, vision_content)
        return llm, llm

    main.app.state.chat_llm_factory = factory


def test_create_and_get_session(client):
    _install_fake_chat(client, [])
    resp = client.post("/api/chat/sessions", json={"run_id": None})
    assert resp.status_code == 200
    sid = resp.json()["session_id"]
    detail = client.get(f"/api/chat/sessions/{sid}")
    assert detail.status_code == 200
    assert detail.json()["session"]["session_id"] == sid
    assert detail.json()["messages"] == []


def test_list_sessions(client):
    _install_fake_chat(client, [])
    client.post("/api/chat/sessions", json={})
    resp = client.get("/api/chat/sessions")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_delete_session(client):
    _install_fake_chat(client, [])
    sid = client.post("/api/chat/sessions", json={}).json()["session_id"]
    assert client.delete(f"/api/chat/sessions/{sid}").status_code == 200
    assert client.get(f"/api/chat/sessions/{sid}").status_code == 404


def test_stream_chat_emits_done_and_persists(client):
    _install_fake_chat(client, [AIMessage(content="结论。不构成投资建议。")])
    sid = client.post("/api/chat/sessions", json={}).json()["session_id"]
    with client.stream(
        "POST", f"/api/chat/sessions/{sid}/stream", json={"message": "该减仓吗?"}
    ) as s:
        body = "".join(chunk for chunk in s.iter_text())
    assert "event: token" in body
    assert "event: done" in body
    msgs = client.get(f"/api/chat/sessions/{sid}").json()["messages"]
    roles = [m["role"] for m in msgs]
    assert roles == ["user", "assistant"]
    assert "结论" in msgs[1]["content"]


def test_portfolio_extract_and_get(client):
    _install_fake_chat(
        client,
        [],
        vision_content=json.dumps([{"ticker": "AAPL", "shares": 10, "weight": 40}]),
    )
    sid = client.post("/api/chat/sessions", json={}).json()["session_id"]
    resp = client.post(
        f"/api/chat/sessions/{sid}/portfolio",
        files={"file": ("p.png", b"\x89PNG", "image/png")},
    )
    assert resp.status_code == 200
    assert resp.json()["holdings"][0]["ticker"] == "AAPL"
    assert resp.json()["source"] == "vision"
    got = client.get(f"/api/chat/sessions/{sid}/portfolio")
    assert got.json()["holdings"][0]["ticker"] == "AAPL"


def test_portfolio_manual_overwrite(client):
    _install_fake_chat(client, [])
    sid = client.post("/api/chat/sessions", json={}).json()["session_id"]
    resp = client.put(
        f"/api/chat/sessions/{sid}/portfolio",
        json={"holdings": [{"ticker": "MSFT", "shares": 5}], "source": "manual"},
    )
    assert resp.status_code == 200
    got = client.get(f"/api/chat/sessions/{sid}/portfolio")
    assert got.json()["holdings"][0]["ticker"] == "MSFT"
    assert got.json()["source"] == "manual"


def test_chat_does_not_trigger_409_when_analysis_running(client, monkeypatch):
    import api.main as main

    monkeypatch.setattr(main.get_store(), "has_running_run", lambda: True)
    _install_fake_chat(client, [AIMessage(content="ok。不构成投资建议。")])
    sid = client.post("/api/chat/sessions", json={}).json()["session_id"]
    with client.stream(
        "POST", f"/api/chat/sessions/{sid}/stream", json={"message": "hi"}
    ) as s:
        body = "".join(chunk for chunk in s.iter_text())
    assert "event: done" in body


def test_stream_unknown_session_404(client):
    _install_fake_chat(client, [])
    resp = client.post("/api/chat/sessions/nope/stream", json={"message": "hi"})
    assert resp.status_code == 404
