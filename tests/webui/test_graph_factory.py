def test_real_graph_factory_builds_graph(monkeypatch):
    import api.main as main
    from api.schemas import AnalysisRequest

    captured = {}

    class _FakeTAG:
        def __init__(self, selected_analysts, debug, config, **kwargs):
            captured["analysts"] = selected_analysts
            captured["config"] = config
            captured["callbacks"] = kwargs.get("callbacks")

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
    main.app.state.starting_telemetry = None

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
    assert captured["callbacks"] == []
    assert init_state["company_of_interest"] == "NVDA"
    assert decision is None and final_state is None


def test_real_graph_factory_passes_telemetry_callback(monkeypatch):
    import api.main as main
    from api.schemas import AnalysisRequest
    from api.telemetry import RunTelemetry

    captured = {}

    class _FakeTAG:
        def __init__(self, selected_analysts, debug, config, **kwargs):
            captured["callbacks"] = kwargs.get("callbacks")

            class _Prop:
                def create_initial_state(self, ticker, date, **kw):
                    return {"company_of_interest": ticker, "trade_date": date}

                def get_graph_args(self):
                    return {}

            self.propagator = _Prop()
            self.memory_log = type("_ML", (), {"get_past_context": lambda self, t: ""})()
            self.graph = type("_Inner", (), {"stream": lambda self, s, **k: iter(())})()

        def resolve_instrument_context(self, ticker, asset_type):
            return ""

    monkeypatch.setattr(main, "TradingAgentsGraph", _FakeTAG)
    main.app.state.starting_telemetry = RunTelemetry("r1")

    req = AnalysisRequest(ticker="NVDA", trade_date="2024-05-10")
    main.real_graph_factory(req)

    assert len(captured["callbacks"]) == 1


def test_real_graph_factory_injects_prefetched(monkeypatch):
    import api.main as main

    captured = {}

    class FakeSummary:
        def for_context(self):
            return {"ticker": "510300.SS", "missing": [], "news_text": "n", "quote": None}

    def fake_prefetch(ticker, trade_date, store, **kw):
        captured["ticker"] = ticker
        return FakeSummary()

    monkeypatch.setattr(main, "prefetch_snapshot", fake_prefetch)
    init_state = {"company_of_interest": "510300.SS"}
    main._inject_prefetched(init_state, "510300.SS", "2026-07-07", store=None)
    assert init_state["prefetched"]["news_text"] == "n"
    assert captured["ticker"] == "510300.SS"
