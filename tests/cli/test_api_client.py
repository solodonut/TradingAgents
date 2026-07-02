from unittest.mock import MagicMock, patch

import pytest
import requests

from cli.api_client import ApiClient, ApiError


@pytest.mark.unit
def test_base_url_precedence_arg_over_env(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_API_URL", "http://env-host:9000")
    client = ApiClient("http://arg-host:8000/")
    assert client.base_url == "http://arg-host:8000"  # trailing slash stripped


@pytest.mark.unit
def test_base_url_from_env(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_API_URL", "http://env-host:9000/")
    assert ApiClient().base_url == "http://env-host:9000"


@pytest.mark.unit
def test_base_url_default(monkeypatch):
    monkeypatch.delenv("TRADINGAGENTS_API_URL", raising=False)
    assert ApiClient().base_url == "http://localhost:8000"


def _fake_response(payload):
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


@pytest.mark.unit
def test_enqueue_builds_payload():
    client = ApiClient("http://h:8000")
    with patch("cli.api_client.requests.post") as post:
        post.return_value = _fake_response({"run_ids": ["r1"], "running_run_id": "r1"})
        out = client.enqueue(
            ticker="aapl", name="Apple", trade_date="2026-07-02", asset_type="stock",
            analysts=["market"], research_depth=3, output_language="Chinese",
            llm_provider="deepseek", deep_think_llm="deepseek-reasoner",
            quick_think_llm="deepseek-chat",
        )
    assert out["run_ids"] == ["r1"]
    url, kwargs = post.call_args[0][0], post.call_args[1]
    assert url == "http://h:8000/api/queue"
    body = kwargs["json"]
    assert body["tickers"] == ["AAPL"]              # normalized upper
    assert body["ticker_names"] == {"AAPL": "Apple"}
    assert body["asset_type"] == "stock"


@pytest.mark.unit
def test_enqueue_omits_empty_name():
    client = ApiClient("http://h:8000")
    with patch("cli.api_client.requests.post") as post:
        post.return_value = _fake_response({"run_ids": ["r1"]})
        client.enqueue(
            ticker="BTC-USD", name="", trade_date="2026-07-02", asset_type="crypto",
            analysts=["market"], research_depth=1, output_language="English",
            llm_provider=None, deep_think_llm=None, quick_think_llm=None,
        )
    assert post.call_args[1]["json"]["ticker_names"] == {}


@pytest.mark.unit
def test_get_status_swallows_error_returns_none():
    client = ApiClient("http://h:8000")
    with patch("cli.api_client.requests.get") as get:
        get.side_effect = requests.RequestException("404")
        assert client.get_status("missing") is None


@pytest.mark.unit
def test_get_watchlist_wraps_network_error():
    client = ApiClient("http://h:8000")
    with patch("cli.api_client.requests.get") as get:
        get.side_effect = requests.ConnectionError("refused")
        with pytest.raises(ApiError):
            client.get_watchlist()
