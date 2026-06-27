def test_get_watchlist_empty(client):
    resp = client.get("/api/watchlist")
    assert resp.status_code == 200
    assert resp.json() == []


def test_put_then_get_roundtrip(client):
    items = [
        {"ticker": "NVDA", "name": "NVIDIA"},
        {"ticker": "159338", "name": "中证A500ETF国泰"},
    ]
    put = client.put("/api/watchlist", json=items)
    assert put.status_code == 200
    assert put.json() == items

    got = client.get("/api/watchlist")
    assert got.json() == items


def test_put_replaces_previous(client):
    client.put("/api/watchlist", json=[{"ticker": "AAPL", "name": "Apple"}])
    client.put("/api/watchlist", json=[{"ticker": "TSLA", "name": ""}])
    assert client.get("/api/watchlist").json() == [{"ticker": "TSLA", "name": ""}]


def test_put_dedupes_tickers(client):
    resp = client.put(
        "/api/watchlist",
        json=[
            {"ticker": "NVDA", "name": "NVIDIA"},
            {"ticker": "NVDA", "name": "dup"},
        ],
    )
    assert resp.status_code == 200
    assert resp.json() == [{"ticker": "NVDA", "name": "NVIDIA"}]
