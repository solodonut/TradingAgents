"""Run-scoped provenance context for evidence registration."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from tradingagents.graph.evidence import EvidenceRegistry

_current: ContextVar[EvidenceRegistry | None] = ContextVar("evidence_registry", default=None)


def set_current_evidence_registry(registry: EvidenceRegistry | None) -> None:
    _current.set(registry)


@contextmanager
def use_evidence_registry(registry: EvidenceRegistry | None) -> Iterator[EvidenceRegistry | None]:
    token = _current.set(registry)
    try:
        yield registry
    finally:
        _current.reset(token)


def get_current_evidence_registry() -> EvidenceRegistry | None:
    return _current.get()


def clear_current_evidence_registry() -> None:
    _current.set(None)


def current_evidence_items() -> list[dict[str, Any]]:
    registry = get_current_evidence_registry()
    return registry.to_list() if registry is not None else []


def register_dataset_evidence(
    *,
    kind: str,
    source_name: str,
    title: str,
    vendor: str,
    tool_name: str,
    query: dict[str, Any],
    published_at: str = "",
    excerpt: str = "",
    url: str = "",
) -> str | None:
    registry = get_current_evidence_registry()
    if registry is None:
        return None
    return registry.register(
        kind=kind,
        source_name=source_name,
        title=title,
        url=url,
        published_at=published_at,
        vendor=vendor,
        tool_name=tool_name,
        query=query,
        excerpt=excerpt,
    )


def register_unavailable_evidence(
    *,
    tool_name: str,
    vendor: str = "",
    query: dict[str, Any],
    reason: str,
) -> str | None:
    registry = get_current_evidence_registry()
    if registry is None:
        return None
    return registry.register(
        kind="data_unavailable",
        source_name=vendor or "configured vendors",
        title=f"{tool_name} unavailable",
        url="",
        published_at="",
        vendor=vendor,
        tool_name=tool_name,
        query=query,
        excerpt=reason,
    )


def prefix_with_evidence(text: str, citation_id: str | None, title: str) -> str:
    if not citation_id:
        return text
    return f"## [{citation_id}] {title}\n\n{text}"
