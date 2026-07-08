from fastapi.testclient import TestClient

import api.routes.ticker as ticker_routes


def test_lookup_returns_name_when_resolved(client, monkeypatch):
    monkeypatch.setattr(ticker_routes, "resolve_ticker_name", lambda code: "NVIDIA Corporation")
    resp = client.get("/api/ticker/NVDA")
    assert resp.status_code == 200
    assert resp.json() == {
        "ticker": "NVDA",
        "name": "NVIDIA Corporation",
        "valid": True,
        "type": "stock",
    }


def test_lookup_uppercases_and_strips(client, monkeypatch):
    seen = {}

    def fake(code):
        seen["code"] = code
        return "Apple Inc."

    monkeypatch.setattr(ticker_routes, "resolve_ticker_name", fake)
    resp = client.get("/api/ticker/aapl")
    assert resp.status_code == 200
    assert resp.json()["ticker"] == "AAPL"
    assert seen["code"] == "AAPL"


def test_lookup_invalid_returns_null_name_not_error(client, monkeypatch):
    monkeypatch.setattr(ticker_routes, "resolve_ticker_name", lambda code: None)
    resp = client.get("/api/ticker/ZZZZ")
    assert resp.status_code == 200
    assert resp.json() == {"ticker": "ZZZZ", "name": None, "valid": False, "type": "stock"}


def test_ticker_lookup_returns_type():
    from api.main import app

    client = TestClient(app)
    assert client.get("/api/ticker/510300.SS").json()["type"] == "etf"
    assert client.get("/api/ticker/600519.SS").json()["type"] == "stock"
