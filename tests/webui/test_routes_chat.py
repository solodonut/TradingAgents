import json

import pytest
from langchain_core.messages import AIMessage

import tradingagents.advisor.vision as vision
from api.schemas import PortfolioHolding


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

    received = {}

    def factory(model=None):
        received["model"] = model
        chain = _FakeChain(chat_responses)
        llm = _FakeLLM(chain, vision_content)
        return llm, llm

    main.app.state.chat_llm_factory = factory
    return received


def _create_completed_run(store, run_id: str, ticker: str) -> None:
    store.insert_run(run_id, ticker, "2026-06-20", "stock", {})
    store.complete_run(run_id, "Hold", {"market_report": f"{ticker} report"})


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


def test_create_session_with_multiple_completed_reports(client):
    import api.main as main

    store = main.get_store()
    _create_completed_run(store, "r1", "AAA")
    _create_completed_run(store, "r2", "BBB")
    response = client.post(
        "/api/chat/sessions", json={"run_ids": ["r2", "r1"]}
    )
    assert response.status_code == 200
    session = client.get(
        f"/api/chat/sessions/{response.json()['session_id']}"
    ).json()["session"]
    assert session["run_ids"] == ["r2", "r1"]
    assert session["run_id"] == "r2"


def test_update_session_reports_replaces_selection(client):
    import api.main as main

    store = main.get_store()
    _create_completed_run(store, "r1", "AAA")
    _create_completed_run(store, "r2", "BBB")
    sid = client.post(
        "/api/chat/sessions", json={"run_ids": ["r1"]}
    ).json()["session_id"]

    response = client.put(
        f"/api/chat/sessions/{sid}/reports", json={"run_ids": ["r2", "r1"]}
    )

    assert response.status_code == 200
    assert response.json()["run_ids"] == ["r2", "r1"]


def test_update_session_reports_accepts_empty_selection(client):
    import api.main as main

    store = main.get_store()
    _create_completed_run(store, "r1", "AAA")
    sid = client.post(
        "/api/chat/sessions", json={"run_ids": ["r1"]}
    ).json()["session_id"]
    response = client.put(
        f"/api/chat/sessions/{sid}/reports", json={"run_ids": []}
    )
    assert response.status_code == 200
    assert response.json()["run_ids"] == []


@pytest.mark.parametrize("invalid_kind", ["missing", "duplicate", "running", "error"])
def test_update_session_reports_rejects_invalid_runs_atomically(client, invalid_kind):
    import api.main as main

    store = main.get_store()
    _create_completed_run(store, "r1", "AAA")
    if invalid_kind == "duplicate":
        invalid_ids = ["r1", "r1"]
    elif invalid_kind == "missing":
        invalid_ids = ["r1", "missing"]
    else:
        invalid_id = f"r-{invalid_kind}"
        store.insert_run(invalid_id, "BAD", "2026-06-20", "stock", {})
        if invalid_kind == "error":
            store.mark_error(invalid_id, "failed")
        invalid_ids = ["r1", invalid_id]

    sid = client.post(
        "/api/chat/sessions", json={"run_ids": ["r1"]}
    ).json()["session_id"]
    response = client.put(
        f"/api/chat/sessions/{sid}/reports", json={"run_ids": invalid_ids}
    )

    assert response.status_code == 422
    session = client.get(f"/api/chat/sessions/{sid}").json()["session"]
    assert session["run_ids"] == ["r1"]


def test_create_session_rejects_legacy_and_multi_report_fields_together(client):
    response = client.post(
        "/api/chat/sessions", json={"run_id": "r1", "run_ids": ["r2"]}
    )
    assert response.status_code == 422


def test_delete_session(client):
    _install_fake_chat(client, [])
    sid = client.post("/api/chat/sessions", json={}).json()["session_id"]
    assert client.delete(f"/api/chat/sessions/{sid}").status_code == 200
    assert client.get(f"/api/chat/sessions/{sid}").status_code == 404


def test_rename_session(client):
    _install_fake_chat(client, [])
    sid = client.post("/api/chat/sessions", json={}).json()["session_id"]
    resp = client.patch(f"/api/chat/sessions/{sid}", json={"title": "复盘计划"})
    assert resp.status_code == 200
    assert resp.json()["title"] == "复盘计划"
    assert client.get(f"/api/chat/sessions/{sid}").json()["session"]["title"] == "复盘计划"


def test_bulk_delete_sessions(client):
    _install_fake_chat(client, [])
    keep = client.post("/api/chat/sessions", json={}).json()["session_id"]
    delete_one = client.post("/api/chat/sessions", json={}).json()["session_id"]
    delete_two = client.post("/api/chat/sessions", json={}).json()["session_id"]

    resp = client.request(
        "DELETE",
        "/api/chat/sessions",
        json={"session_ids": [delete_one, delete_two]},
    )

    assert resp.status_code == 200
    assert resp.json()["deleted"] == [delete_one, delete_two]
    assert client.get(f"/api/chat/sessions/{keep}").status_code == 200
    assert client.get(f"/api/chat/sessions/{delete_one}").status_code == 404
    assert client.get(f"/api/chat/sessions/{delete_two}").status_code == 404


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


def test_stream_chat_uses_all_selected_reports(client, monkeypatch):
    import api.main as main
    import api.routes.chat as chat_routes

    store = main.get_store()
    _create_completed_run(store, "r1", "AAA")
    _create_completed_run(store, "r2", "BBB")
    captured = {}

    def capture_prompt(report_context: str, holdings_ctx: str, profile_ctx: str = "") -> str:
        captured["report_context"] = report_context
        return "system"

    monkeypatch.setattr(chat_routes, "build_system_prompt", capture_prompt)
    _install_fake_chat(client, [AIMessage(content="ok。不构成投资建议。")])
    sid = client.post(
        "/api/chat/sessions", json={"run_ids": ["r2", "r1"]}
    ).json()["session_id"]
    with client.stream(
        "POST", f"/api/chat/sessions/{sid}/stream", json={"message": "比较"}
    ) as stream:
        "".join(stream.iter_text())

    context = captured["report_context"]
    assert context.index("报告 1 · BBB") < context.index("报告 2 · AAA")
    assert "BBB report" in context
    assert "AAA report" in context


def test_stream_chat_requests_export_scope_without_creating_file(client, monkeypatch, tmp_path):
    import api.routes.chat as chat_routes

    report_dir = tmp_path / "report"
    monkeypatch.setattr(chat_routes, "REPORT_DIR", report_dir)
    question = "你希望导出哪部分？"
    options = ["AAPL 操作结论", "风险与仓位建议"]
    _install_fake_chat(
        client,
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "request_export_scope",
                        "args": {"question": question, "options": options},
                        "id": "scope-1",
                    }
                ],
            ),
            AIMessage(content="请选择导出范围。"),
        ],
    )
    sid = client.post("/api/chat/sessions", json={}).json()["session_id"]

    with client.stream(
        "POST",
        f"/api/chat/sessions/{sid}/stream",
        json={"message": "先给我导出选项"},
    ) as stream:
        body = "".join(stream.iter_text())

    assert "event: tool_call" in body
    assert '"tool": "request_export_scope"' in body
    assert not report_dir.exists()
    messages = client.get(f"/api/chat/sessions/{sid}").json()["messages"]
    assert messages[-1]["role"] == "assistant"
    assert messages[-1]["tool_calls"] == [
        {
            "tool": "request_export_scope",
            "args": {"question": question, "options": options},
            "unavailable": False,
        }
    ]


def test_stream_chat_exports_active_session_to_report_directory(client, monkeypatch, tmp_path):
    import api.main as main
    import api.routes.chat as chat_routes
    import tradingagents.advisor.export as export_module

    store = main.get_store()
    active_sid = client.post("/api/chat/sessions", json={}).json()["session_id"]
    other_sid = client.post("/api/chat/sessions", json={}).json()["session_id"]
    client.patch(
        f"/api/chat/sessions/{active_sid}", json={"title": "AAPL 复盘结论"}
    )
    store.insert_chat_message("active-user", active_sid, "user", "AAPL 应减仓", tool_calls=[])
    store.insert_chat_message(
        "active-assistant", active_sid, "assistant", "确认减仓至 20%", tool_calls=[]
    )
    store.insert_chat_message("other-user", other_sid, "user", "不要导出这段", tool_calls=[])

    captured = {}

    def capture_report(llm, messages, scope):
        captured["messages"] = [message.content for message in messages]
        captured["scope"] = scope
        return "# AAPL 复盘结论\n\n减仓至 20%。"

    report_dir = tmp_path / "report"
    monkeypatch.setattr(chat_routes, "REPORT_DIR", report_dir)
    monkeypatch.setattr(export_module, "generate_report_markdown", capture_report)
    scope = "仅导出 AAPL 已确认的仓位操作结论"
    current_request = "导出仅包含 AAPL 已确认仓位操作的报告"
    _install_fake_chat(
        client,
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "export_chat_report",
                        "args": {"scope": scope},
                        "id": "export-1",
                    }
                ],
            ),
            AIMessage(content="报告已保存。"),
        ],
    )

    with client.stream(
        "POST",
        f"/api/chat/sessions/{active_sid}/stream",
        json={"message": current_request},
    ) as stream:
        body = "".join(stream.iter_text())

    assert "event: tool_call" in body
    assert captured == {
        "messages": ["AAPL 应减仓", "确认减仓至 20%", current_request],
        "scope": scope,
    }
    assert "不要导出这段" not in captured["messages"]
    files = list(report_dir.glob("*.md"))
    assert len(files) == 1
    assert files[0].name.endswith("-AAPL 复盘结论.md")
    assert files[0].read_text(encoding="utf-8") == "# AAPL 复盘结论\n\n减仓至 20%。\n"
    messages = client.get(f"/api/chat/sessions/{active_sid}").json()["messages"]
    assert messages[-1]["tool_calls"] == [
        {
            "tool": "export_chat_report",
            "args": {"scope": scope},
            "unavailable": False,
        }
    ]


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


def test_portfolio_extract_accepts_multiple_images_and_merges_with_existing(client):
    _install_fake_chat(
        client,
        [],
        vision_content=json.dumps(
            [
                {"ticker": "AAPL", "shares": 12},
                {"ticker": "NVDA", "shares": 2},
            ]
        ),
    )
    sid = client.post("/api/chat/sessions", json={}).json()["session_id"]
    client.put(
        f"/api/chat/sessions/{sid}/portfolio",
        json={
            "holdings": [
                {"ticker": "AAPL", "shares": 10},
                {"ticker": "MSFT", "shares": 5},
            ],
            "source": "manual",
        },
    )

    resp = client.post(
        f"/api/chat/sessions/{sid}/portfolio",
        files=[
            ("files", ("p1.png", b"\x89PNG-one", "image/png")),
            ("files", ("p2.png", b"\x89PNG-two", "image/png")),
        ],
    )

    assert resp.status_code == 200
    assert [(h["ticker"], h["shares"]) for h in resp.json()["holdings"]] == [
        ("AAPL", 12),
        ("MSFT", 5),
        ("NVDA", 2),
    ]


def test_portfolio_extract_prefers_files_over_legacy_file_field(client, monkeypatch):
    extracted_payloads: list[bytes] = []

    def fake_extract_holdings(llm, image_bytes, mime="image/png"):
        extracted_payloads.append(image_bytes)
        return [PortfolioHolding(ticker=f"ROW{len(extracted_payloads)}")]

    monkeypatch.setattr(vision, "extract_holdings", fake_extract_holdings)
    _install_fake_chat(
        client,
        [],
        vision_content=json.dumps([{"ticker": "AAPL", "shares": 12}]),
    )
    sid = client.post("/api/chat/sessions", json={}).json()["session_id"]

    resp = client.post(
        f"/api/chat/sessions/{sid}/portfolio",
        files=[
            ("file", ("legacy.png", b"\x89PNG-legacy", "image/png")),
            ("files", ("p1.png", b"\x89PNG-one", "image/png")),
            ("files", ("p2.png", b"\x89PNG-two", "image/png")),
        ],
    )

    assert resp.status_code == 200
    assert extracted_payloads == [b"\x89PNG-one", b"\x89PNG-two"]


def test_portfolio_extract_appends_trade_on_different_date(client):
    _install_fake_chat(
        client,
        [],
        vision_content=json.dumps(
            [
                {
                    "ticker": "AAPL",
                    "action": "buy",
                    "trade_date": "2026-06-18",
                    "shares": 8,
                }
            ]
        ),
    )
    sid = client.post("/api/chat/sessions", json={}).json()["session_id"]
    client.put(
        f"/api/chat/sessions/{sid}/portfolio",
        json={
            "holdings": [
                {
                    "ticker": "AAPL",
                    "action": "buy",
                    "trade_date": "2026-06-17",
                    "shares": 10,
                }
            ],
            "source": "manual",
        },
    )

    resp = client.post(
        f"/api/chat/sessions/{sid}/portfolio",
        files={"file": ("p.png", b"\x89PNG", "image/png")},
    )

    assert resp.status_code == 200
    assert [(h["ticker"], h["trade_date"], h["shares"]) for h in resp.json()["holdings"]] == [
        ("AAPL", "2026-06-17", 10),
        ("AAPL", "2026-06-18", 8),
    ]


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


def test_get_profile_defaults_when_unset(client):
    _install_fake_chat(client, [])
    sid = client.post("/api/chat/sessions", json={}).json()["session_id"]
    resp = client.get(f"/api/chat/sessions/{sid}/profile")
    assert resp.status_code == 200
    body = resp.json()
    assert body["available_capital"] is None
    assert body["capital_currency"] == "CNY"


def test_put_profile_persists_and_sets_confirmed_at(client):
    _install_fake_chat(client, [])
    sid = client.post("/api/chat/sessions", json={}).json()["session_id"]
    resp = client.put(
        f"/api/chat/sessions/{sid}/profile",
        json={"available_capital": 300000, "risk_tolerance": "balanced"},
    )
    assert resp.status_code == 200
    assert resp.json()["available_capital"] == 300000
    assert resp.json()["confirmed_at"] is not None
    # round-trips
    again = client.get(f"/api/chat/sessions/{sid}/profile").json()
    assert again["risk_tolerance"] == "balanced"


def test_profile_routes_404_for_missing_session(client):
    _install_fake_chat(client, [])
    assert client.get("/api/chat/sessions/nope/profile").status_code == 404
    assert (
        client.put("/api/chat/sessions/nope/profile", json={}).status_code == 404
    )


def test_stream_chat_registers_profile_tools_and_injects_profile(client):
    import api.main as main

    captured = {}

    class _RecordingChain:
        def __init__(self):
            self._round = 0

        def invoke(self, messages):
            # 记录注入的 system prompt（第一条消息由 prompt 模板渲染）
            self._round += 1
            if self._round == 1:
                captured["system"] = str(messages)
                return AIMessage(
                    content="",
                    tool_calls=[{
                        "name": "compute_position_sizing",
                        "args": {"ticker": "AAPL", "price": 200,
                                 "target_weight_pct": 10},
                        "id": "call1",
                    }],
                )
            return AIMessage(content="done")

    class _LLM:
        def bind_tools(self, tools):
            captured["tool_names"] = {t.name for t in tools}
            return _RecordingChain()

        def invoke(self, messages):
            return AIMessage(content="[]")

    main.app.state.chat_llm_factory = lambda model=None: (_LLM(), _LLM())

    sid = client.post("/api/chat/sessions", json={}).json()["session_id"]
    client.put(
        f"/api/chat/sessions/{sid}/profile",
        json={"available_capital": 300000, "capital_currency": "CNY"},
    )
    with client.stream(
        "POST", f"/api/chat/sessions/{sid}/stream", json={"message": "AAPL 配 10%"}
    ) as resp:
        body = "".join(resp.iter_text())

    assert "compute_position_sizing" in captured["tool_names"]
    assert "propose_session_facts" in captured["tool_names"]
    assert "300000" in captured["system"]
    assert "done" in body


def test_stream_chat_passes_chat_llm_to_factory(client):
    received = _install_fake_chat(client, [AIMessage(content="ok")])
    sid = client.post("/api/chat/sessions", json={}).json()["session_id"]
    with client.stream(
        "POST",
        f"/api/chat/sessions/{sid}/stream",
        json={"message": "hi", "chat_llm": "claude-opus-4-8"},
    ) as stream:
        "".join(stream.iter_text())
    assert received["model"] == "claude-opus-4-8"


def test_stream_chat_defaults_model_to_none_when_absent(client):
    received = _install_fake_chat(client, [AIMessage(content="ok")])
    sid = client.post("/api/chat/sessions", json={}).json()["session_id"]
    with client.stream(
        "POST", f"/api/chat/sessions/{sid}/stream", json={"message": "hi"}
    ) as stream:
        "".join(stream.iter_text())
    assert received["model"] is None
