"""Startup-time LLM health check and automatic model selection.

Probes the configured provider's candidate models so the service can pick a
working model for each slot before the first real analysis runs. Framework-free
and import-safe: importing this module must not require an API key or perform
any network request.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from langchain_core.messages import HumanMessage

from .factory import create_llm_client

_PING = [HumanMessage(content="ping")]
_MAX_ERROR_LEN = 500


@dataclass
class ProbeResult:
    model: str
    ok: bool
    error: str | None
    latency_ms: int


def probe_model(provider: str, model: str, base_url: str | None = None) -> ProbeResult:
    """Probe one model with a minimal request. Never raises.

    A model is considered usable if a minimal ``invoke`` returns without
    raising. Any exception (build error, auth, network, bad model) yields
    ``ok=False`` with a short error string.
    """
    start = time.monotonic()
    try:
        client = create_llm_client(provider=provider, model=model, base_url=base_url)
        client.get_llm().invoke(_PING)
    except Exception as exc:  # noqa: BLE001 - any failure means "unusable"
        elapsed = int((time.monotonic() - start) * 1000)
        message = f"{type(exc).__name__}: {exc}"[:_MAX_ERROR_LEN]
        return ProbeResult(model=model, ok=False, error=message, latency_ms=elapsed)
    elapsed = int((time.monotonic() - start) * 1000)
    return ProbeResult(model=model, ok=True, error=None, latency_ms=elapsed)
