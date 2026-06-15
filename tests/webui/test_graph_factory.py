def test_real_graph_factory_builds_graph(monkeypatch):
    import api.main as main
    from api.schemas import AnalysisRequest

    captured = {}

    class _FakeTAG:
        def __init__(self, selected_analysts, debug, config, **kwargs):
            captured["analysts"] = selected_analysts
            captured["config"] = config

            class _Prop:
                def create_initial_state(self, ticker, date, **kw):
                    captured["ticker"] = ticker
                    return {"company_of_interest": ticker, "trade_date": date}

                def get_graph_args(self):
                    return {"stream_mode": "values"}

            self.propagator = _Prop()
            self.memory_log = type(
                "_ML", (), {"get_past_context": lambda self, t: ""}
            )()

            class _Inner:
                def stream(inner_self, s, **k):
                    yield {}

            self.graph = _Inner()

        def resolve_instrument_context(self, ticker, asset_type):
            return ""

    monkeypatch.setattr(main, "TradingAgentsGraph", _FakeTAG)

    req = AnalysisRequest(
        ticker="NVDA",
        trade_date="2024-05-10",
        analysts=["market", "news"],
        research_depth=5,
        llm_provider="openai",
    )
    graph, init_state, decision, final_state = main.real_graph_factory(req)
    assert captured["analysts"] == ["market", "news"]
    assert captured["config"]["max_debate_rounds"] == 5
    assert captured["config"]["llm_provider"] == "openai"
    assert init_state["company_of_interest"] == "NVDA"
    assert decision is None and final_state is None
