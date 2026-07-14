"""Evidence registry and markdown citation helpers."""

from __future__ import annotations

import html
import re
from collections.abc import Iterable, Mapping
from copy import deepcopy
from typing import Any
from urllib.parse import quote, urlsplit

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


_BRACKET_RE = re.compile(r"\[([^\[\]]+)\]")


def extract_cited_evidence_ids(
    text: str, evidence_items: Iterable[Mapping[str, Any]]
) -> list[str]:
    """Resolve bracketed citation tokens to evidence ids.

    Matches readable labels (``[历史行情（OHLCV）]``), titles, and legacy ``[S#]`` ids.
    A label may be shared by several items, so each token can contribute more than
    one id. Unknown tokens (arbitrary text, markdown-link labels) resolve to nothing.
    Returns ids in first-seen order, deduped.
    """
    lookup: dict[str, list[str]] = {}
    for item in evidence_items:
        citation_id = _display(item.get("id"))
        if not citation_id:
            continue
        for token in (citation_id, _display(item.get("title")), _display(item.get("display_label"))):
            if not token:
                continue
            ids = lookup.setdefault(token, [])
            if citation_id not in ids:
                ids.append(citation_id)

    seen: set[str] = set()
    result: list[str] = []
    for match in _BRACKET_RE.finditer(text or ""):
        token = match.group(1).strip()
        for citation_id in lookup.get(token, ()):
            if citation_id not in seen:
                seen.add(citation_id)
                result.append(citation_id)
    return result


def _display(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value)


def _safe_cell(value: Any) -> str:
    text = _display(value) or "-"
    return html.escape(text).replace("|", "\\|")


def _safe_link(value: Any) -> str:
    url = _display(value)
    if not url:
        return "-"
    parsed = urlsplit(url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return "-"
    escaped_url = quote(url, safe=":/?#[]@!$&'*,;=%")
    return f"[打开]({escaped_url})"


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


_INDICATOR_LABELS = {
    "macd": "MACD",
    "macdh": "MACD 柱状图（macdh）",
    "atr": "ATR",
    "rsi": "RSI",
    "vwma": "VWMA",
    "boll": "布林带整体数据（boll）",
    "boll_lb": "布林下轨（boll_lb）",
    "boll_ub": "布林上轨（boll_ub）",
}

_MOVING_AVERAGE_RE = re.compile(r"^close_(\d+)_(ema|sma)$")

_TOOL_LABELS = {
    "get_stock_data": "历史行情（OHLCV）",
    "get_verified_market_snapshot": "已验证市场快照",
    "get_fundamentals": "综合基本面",
    "get_balance_sheet": "资产负债表",
    "get_cashflow": "现金流量表",
    "get_income_statement": "利润表",
}


def _indicator_display_label(indicator: str) -> str:
    ind = indicator.strip().lower()
    if not ind:
        return ""
    match = _MOVING_AVERAGE_RE.match(ind)
    if match:
        return f"{match.group(1)} 日 {match.group(2).upper()}"
    return _INDICATOR_LABELS.get(ind, "")


def _derive_display_label(kind: str, tool_name: str, query: Mapping[str, Any]) -> str:
    """Readable data/purpose label for inline citations, assigned at registration time."""
    if kind == "data_unavailable":
        return ""
    if tool_name == "get_indicators":
        indicator = query.get("indicator") if isinstance(query, Mapping) else None
        return _indicator_display_label(_display(indicator))
    return _TOOL_LABELS.get(tool_name, "")


def _normalize_item(item: Mapping[str, Any], citation_id: str) -> dict[str, Any]:
    kind = _display(item.get("kind")) or "vendor_dataset"
    tool_name = _display(item.get("tool_name"))
    query = deepcopy(item.get("query") or {})
    return {
        "id": citation_id,
        "kind": kind,
        "source_name": _display(item.get("source_name")) or _display(item.get("vendor")) or "unknown",
        "title": _display(item.get("title")) or tool_name or "Untitled evidence",
        "url": _display(item.get("url")),
        "published_at": _display(item.get("published_at")),
        "vendor": _display(item.get("vendor")),
        "tool_name": tool_name,
        "query": query,
        "excerpt": _display(item.get("excerpt")),
        "display_label": _derive_display_label(kind, tool_name, query),
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

    def display_label(self, citation_id: str) -> str:
        for item in self.items:
            if item.get("id") == citation_id:
                return _display(item.get("display_label"))
        return ""


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
        link = _safe_link(item.get("url"))
        label = _display(item.get("display_label")) or citation_id
        label_cell = "[" + html.escape(label).replace("|", "\\|") + "]"
        rows.append(
            "| "
            + " | ".join(
                [
                    label_cell,
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
