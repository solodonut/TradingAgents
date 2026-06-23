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
from .model_catalog import MODEL_OPTIONS

_PING = [HumanMessage(content="ping")]
_MAX_ERROR_LEN = 500


@dataclass
class ProbeResult:
    model: str
    ok: bool
    error: str | None
    latency_ms: int


# Slots to check, mapped to the model_catalog mode used for their candidates.
_SLOT_MODES = {
    "deep_think_llm": "deep",
    "quick_think_llm": "quick",
}


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


def _candidates_for(provider: str, configured: str, mode: str) -> list[str]:
    """Configured model first, then this provider's catalog candidates.

    Drops the ``"custom"`` placeholder and de-duplicates. Providers absent from
    the catalog (e.g. openrouter) yield just the configured model.
    """
    candidates = [configured]
    options = MODEL_OPTIONS.get(provider.lower(), {})
    for _label, value in options.get(mode, []):
        if value == "custom":
            continue
        if value not in candidates:
            candidates.append(value)
    return candidates


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
    """Probe every candidate per slot and pick a working model.

    Selection is configured-first: keep the configured model if it works,
    otherwise take the first working candidate; if none work, keep the
    configured value and mark the slot ``all_failed``. Does not mutate config.
    """
    provider = config["llm_provider"]
    base_url = config.get("backend_url")
    slots: dict[str, SlotReport] = {}
    any_failed = False

    for slot, mode in _SLOT_MODES.items():
        configured = config[slot]
        candidates = _candidates_for(provider, configured, mode)
        results = [probe_model(provider, model, base_url) for model in candidates]

        if results[0].ok:  # configured is always first
            selected, all_failed = configured, False
        else:
            first_ok = next((r.model for r in results if r.ok), None)
            if first_ok is not None:
                selected, all_failed = first_ok, False
            else:
                selected, all_failed = configured, True

        any_failed = any_failed or all_failed
        slots[slot] = SlotReport(
            configured=configured,
            selected=selected,
            all_failed=all_failed,
            candidates=results,
        )

    return HealthReport(provider=provider, slots=slots, any_failed=any_failed)
