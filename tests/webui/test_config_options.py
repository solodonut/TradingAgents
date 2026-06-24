from api.config_options import build_config_options


def test_build_config_options_shape():
    opts = build_config_options()
    assert {a["value"] for a in opts.analysts} == {
        "market",
        "social",
        "news",
        "fundamentals",
    }
    assert [d["value"] for d in opts.research_depth] == [1, 3, 5]
    assert "Chinese" in opts.languages
    assert "English" in opts.languages


def test_configured_provider_reflects_config(monkeypatch):
    import api.config_options as mod

    monkeypatch.setattr(
        mod,
        "DEFAULT_CONFIG",
        {**mod.DEFAULT_CONFIG, "llm_provider": "openai", "deep_think_llm": "gpt-5.5"},
    )
    opts = build_config_options()
    assert opts.configured_provider == "openai"
    assert opts.configured_deep_llm == "gpt-5.5"


def test_get_config_options_route(client):
    resp = client.get("/api/config/options")
    assert resp.status_code == 200
    body = resp.json()
    assert "analysts" in body and "research_depth" in body


def test_model_options_present_for_configured_provider():
    opts = build_config_options()
    assert set(opts.model_options.keys()) == {"deep", "quick"}
    # 默认 provider 是 ibm_ica，有具体模型列表
    assert len(opts.model_options["deep"]) > 0
    assert len(opts.model_options["quick"]) > 0
    # 每个选项是 (label, model_id) 二元组
    label, model_id = opts.model_options["deep"][0]
    assert isinstance(label, str) and isinstance(model_id, str)


def test_model_options_empty_for_unknown_provider(monkeypatch):
    import api.config_options as mod

    monkeypatch.setattr(
        mod,
        "DEFAULT_CONFIG",
        {**mod.DEFAULT_CONFIG, "llm_provider": "nonexistent_provider"},
    )
    opts = build_config_options()
    assert opts.model_options == {"deep": [], "quick": []}
