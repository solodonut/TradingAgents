"""Startup-time LLM health check and automatic model selection.

Probes the models configured in ``.env`` / ``DEFAULT_CONFIG`` for each slot so
the service can report which ones are reachable. No catalog fallback: the
configured model is the only candidate. Framework-free
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


# Slots to check.
_SLOTS = ("deep_think_llm", "quick_think_llm")


@dataclass
class SlotReport:
    configured: str
    selected: str
    all_failed: bool
    candidates: list[ProbeResult]


@dataclass
class HealthReport:
    provider: str
    slots: dict[str, SlotReport]
    any_failed: bool


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


def check_and_select(config: dict) -> HealthReport:
    """Probe the configured model of each slot.

    Only the configured model is probed; there is no fallback to other catalog
    models. A failing slot is marked ``all_failed`` and keeps its configured
    value. Does not mutate config.
    """
    provider = config["llm_provider"]
    base_url = config.get("backend_url")
    slots: dict[str, SlotReport] = {}

    for slot in _SLOTS:
        configured = config[slot]
        result = probe_model(provider, configured, base_url)
        slots[slot] = SlotReport(
            configured=configured,
            selected=configured,
            all_failed=not result.ok,
            candidates=[result],
        )

    return HealthReport(
        provider=provider,
        slots=slots,
        any_failed=any(r.all_failed for r in slots.values()),
    )
