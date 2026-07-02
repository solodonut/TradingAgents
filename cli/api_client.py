"""Thin HTTP client for the TradingAgents WebUI API (used by the batch TUI)."""

import os

import requests

DEFAULT_BASE_URL = "http://localhost:8000"


class ApiError(Exception):
    """Any failure talking to the WebUI API (network error or non-2xx)."""


class ApiClient:
    def __init__(self, base_url: str | None = None, timeout: float = 30.0):
        resolved = base_url or os.getenv("TRADINGAGENTS_API_URL") or DEFAULT_BASE_URL
        self.base_url = resolved.rstrip("/")
        self.timeout = timeout

    def _get(self, path: str):
        try:
            resp = requests.get(f"{self.base_url}{path}", timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            raise ApiError(f"GET {path} failed: {exc}") from exc

    def _post(self, path: str, payload: dict):
        try:
            resp = requests.post(f"{self.base_url}{path}", json=payload, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            raise ApiError(f"POST {path} failed: {exc}") from exc

    def get_watchlist(self) -> list[dict]:
        return self._get("/api/watchlist")

    def enqueue(
        self,
        *,
        ticker: str,
        name: str,
        trade_date: str,
        asset_type: str,
        analysts: list[str],
        research_depth: int,
        output_language: str,
        llm_provider: str | None,
        deep_think_llm: str | None,
        quick_think_llm: str | None,
    ) -> dict:
        normalized = ticker.strip().upper()
        payload = {
            "tickers": [normalized],
            "ticker_names": {normalized: name} if name else {},
            "trade_date": trade_date,
            "asset_type": asset_type,
            "analysts": analysts,
            "research_depth": research_depth,
            "output_language": output_language,
            "llm_provider": llm_provider,
            "deep_think_llm": deep_think_llm,
            "quick_think_llm": quick_think_llm,
        }
        return self._post("/api/queue", payload)

    def get_queue(self) -> dict:
        return self._get("/api/queue")

    def get_status(self, run_id: str) -> dict | None:
        try:
            return self._get(f"/api/analysis/{run_id}/status")
        except ApiError:
            return None

    def get_history(self) -> list[dict]:
        return self._get("/api/history")
