"""Evidence registry and markdown citation helpers."""

from __future__ import annotations

import html
import re
from collections.abc import Iterable, Mapping
from copy import deepcopy
from typing import Any

_CITATION_RE = re.compile(r"\[S(\d+)\]")


def extract_citation_ids(text: str) -> list[str]:
    seen: set[str] = set()
    ids: list[str] = []
    for match in _CITATION_RE.finditer(text or ""):
        citation_id = f"S{match.group(1)}"
        if citation_id not in seen:
            seen.add(citation_id)
            ids.append(citation_id)
    return ids


def _display(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value)


def _safe_cell(value: Any) -> str:
    text = _display(value) or "-"
    return html.escape(text).replace("|", "\\|")


def _canonicalize(value: Any) -> Any:
    if isinstance(value, Mapping):
        items = [(_canonicalize(key), _canonicalize(item_value)) for key, item_value in value.items()]
        items.sort(key=lambda pair: repr(pair[0]))
        return ("mapping", tuple(items))
    if isinstance(value, list):
        return ("list", tuple(_canonicalize(item) for item in value))
    if isinstance(value, tuple):
        return ("tuple", tuple(_canonicalize(item) for item in value))
    if isinstance(value, set):
        return ("set", tuple(sorted((_canonicalize(item) for item in value), key=repr)))
    return (type(value).__name__, value)


def _query_key(query: Any) -> Any:
    return _canonicalize(query)


def _dedupe_key(item: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        item.get("kind") or "",
        item.get("source_name") or "",
        item.get("title") or "",
        item.get("url") or "",
        item.get("tool_name") or "",
        _query_key(item.get("query") or {}),
    )


def _normalize_item(item: Mapping[str, Any], citation_id: str) -> dict[str, Any]:
    return {
        "id": citation_id,
        "kind": _display(item.get("kind")) or "vendor_dataset",
        "source_name": _display(item.get("source_name")) or _display(item.get("vendor")) or "unknown",
        "title": _display(item.get("title")) or _display(item.get("tool_name")) or "Untitled evidence",
        "url": _display(item.get("url")),
        "published_at": _display(item.get("published_at")),
        "vendor": _display(item.get("vendor")),
        "tool_name": _display(item.get("tool_name")),
        "query": deepcopy(item.get("query") or {}),
        "excerpt": _display(item.get("excerpt")),
    }


def _is_valid_citation_id(value: str) -> bool:
    return value.startswith("S") and value[1:].isdigit()


def _next_available_id(start: int, reserved: set[str], assigned: set[str]) -> str:
    candidate = start
    while True:
        citation_id = f"S{candidate}"
        if citation_id not in reserved and citation_id not in assigned:
            return citation_id
        candidate += 1


class EvidenceRegistry:
    def __init__(self, items: Iterable[Mapping[str, Any]] | None = None):
        self.items: list[dict[str, Any]] = []
        self._keys: dict[tuple[Any, ...], str] = {}
        seed_items = list(items or [])
        reserved_ids = {
            raw_id
            for raw in seed_items
            if _is_valid_citation_id(raw_id := _display(raw.get("id")))
        }
        next_generated = (
            max((int(citation_id[1:]) for citation_id in reserved_ids), default=0) + 1
        )
        assigned_ids: set[str] = set()

        for raw in seed_items:
            raw_id = _display(raw.get("id"))
            citation_id = raw_id if _is_valid_citation_id(raw_id) and raw_id not in assigned_ids else None
            if citation_id is None:
                citation_id = _next_available_id(next_generated, reserved_ids, assigned_ids)
                next_generated = int(citation_id[1:]) + 1

            normalized = _normalize_item(raw, citation_id)
            key = _dedupe_key(normalized)
            if key in self._keys:
                continue

            self.items.append(normalized)
            self._keys[key] = citation_id
            assigned_ids.add(citation_id)

        self._next = next_generated

    def register(self, **item: Any) -> str:
        provisional = _normalize_item(item, "S0")
        key = _dedupe_key(provisional)
        existing = self._keys.get(key)
        if existing:
            return existing

        citation_id = f"S{self._next}"
        self._next += 1
        normalized = _normalize_item(item, citation_id)
        self.items.append(normalized)
        self._keys[_dedupe_key(normalized)] = citation_id
        return citation_id

    def to_list(self) -> list[dict[str, Any]]:
        return deepcopy(self.items)

    def by_id(self) -> dict[str, dict[str, Any]]:
        return {item["id"]: deepcopy(item) for item in self.items}


def render_source_table(
    evidence_items: Iterable[Mapping[str, Any]],
    citation_ids: Iterable[str],
    *,
    heading: str,
) -> str:
    by_id = {item.get("id"): item for item in evidence_items}
    rows: list[str] = []
    for citation_id in citation_ids:
        item = by_id.get(citation_id)
        if not item:
            continue
        url = _display(item.get("url"))
        link = f"[打开]({url})" if url else "-"
        rows.append(
            "| "
            + " | ".join(
                [
                    f"[{citation_id}]",
                    _safe_cell(item.get("source_name")),
                    _safe_cell(item.get("title")),
                    _safe_cell(item.get("published_at")),
                    link,
                ]
            )
            + " |"
        )
    if not rows:
        return ""
    return "\n".join(
        [
            f"### {heading}",
            "",
            "| 编号 | 来源 | 标题/数据集 | 日期 | 链接 |",
            "|---|---|---|---|---|",
            *rows,
        ]
    )
