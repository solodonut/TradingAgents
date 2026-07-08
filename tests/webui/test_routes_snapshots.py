def test_etf_dates_and_snapshot(client):
    import api.main as main

    store = main.get_store()
    store.upsert_snapshot("510300.SS", "2026-07-07", "news", "ok", {"text": "hi"})

    r = client.get("/api/etf/510300.SS/dates")
    assert r.status_code == 200
    assert r.json()["dates"] == ["2026-07-07"]

    r2 = client.get("/api/etf/510300.SS/snapshot", params={"date": "2026-07-07"})
    assert r2.status_code == 200
    assert r2.json()["categories"]["news"]["payload"] == {"text": "hi"}


def test_etf_snapshot_empty_date_returns_empty(client):
    r = client.get("/api/etf/000001.SS/snapshot", params={"date": "2026-07-07"})
    assert r.status_code == 200
    assert r.json()["categories"] == {}
