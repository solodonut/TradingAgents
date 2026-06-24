import api.routes.ticker as ticker_routes


def test_lookup_returns_name_when_resolved(client, monkeypatch):
    monkeypatch.setattr(
        ticker_routes,
        "resolve_instrument_identity",
        lambda code: {"company_name": "NVIDIA Corporation"},
    )
    resp = client.get("/api/ticker/NVDA")
    assert resp.status_code == 200
    assert resp.json() == {"ticker": "NVDA", "name": "NVIDIA Corporation", "valid": True}


def test_lookup_uppercases_and_strips(client, monkeypatch):
    seen = {}

    def fake(code):
        seen["code"] = code
        return {"company_name": "Apple Inc."}

    monkeypatch.setattr(ticker_routes, "resolve_instrument_identity", fake)
    resp = client.get("/api/ticker/aapl")
    assert resp.status_code == 200
    assert resp.json()["ticker"] == "AAPL"
    assert seen["code"] == "AAPL"


def test_lookup_invalid_returns_null_name_not_error(client, monkeypatch):
    monkeypatch.setattr(ticker_routes, "resolve_instrument_identity", lambda code: {})
    resp = client.get("/api/ticker/ZZZZ")
    assert resp.status_code == 200
    assert resp.json() == {"ticker": "ZZZZ", "name": None, "valid": False}
