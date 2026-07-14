# Source-Table Label Resolution Design

## Context

Follow-up to `2026-07-13-readable-report-source-citations-design.md`, which changed
tool-output evidence prefixes from `## [S1] get_stock_data: 600519` to a readable
data/purpose label such as `## [历史行情（OHLCV）]`. That change left two gaps in the
end-to-end citation loop:

1. `get_citation_instruction()` still tells agents to cite `[S#]`, but no `S#` appears in
   tool output anymore, so agents can only copy the readable label they see.
2. `extract_citation_ids()` (regex `\[S\d+\]`) matches nothing in a label-cited report,
   so `render_source_table()` produces empty source tables and the report validator
   falsely warns "未发现来源引用".

## Goal

Close the loop for readable-label citations: agents cite the readable label, the final
report's source tables resolve those labels back to evidence provenance, and validation
recognizes them. Keep `S#` as the internal dedup/lookup key. Keep `[S#]` working for
already-stored historical reports.

## Design

### 1. Citation instruction — `agents/utils/agent_utils.py`

Reword `get_citation_instruction()` to tell agents: after each key claim, copy the
bracketed source label exactly as it appears at the top of the relevant tool output
(e.g. `[历史行情（OHLCV）]`, `[资产负债表]`); use only labels that appear in tool outputs or
upstream reports; do not invent labels or links; if no source supports a claim, say so.
The "do not invent" guardrail is preserved; the `[S#]` wording is removed.

### 2. New resolver — `graph/evidence.py`

`extract_cited_evidence_ids(text, evidence_items) -> list[str]`

- Build a lookup from the evidence items where each item's `display_label` (when
  non-empty), `title`, and `id` all map to that item's `S#` id. A label may map to more
  than one id (label collisions), so label values are lists; the `id` mapping is 1:1.
- Scan `text` for every `[...]` bracket token in first-seen order (regex
  `\[([^\[\]]+)\]`, inner text trimmed).
- A token contributes ids only if it exactly matches a known label, title, or id;
  unknown tokens (arbitrary `[text]`, markdown link labels) are ignored by construction.
- Return matched `S#` ids in first-seen order, deduped. Dual-mode: both `[S1]` and
  `[历史行情（OHLCV）]` resolve. A colliding label contributes all its ids.

`extract_citation_ids()` is left unchanged (backward compatibility + existing tests).

### 3. Source table — `graph/evidence.py`

`render_source_table()`'s first column ("编号") renders the item's `display_label` when
present, else the current `[S#]`, wrapped in `[...]` and `|`-escaped like other cells.
The column set, headers, ordering, unknown-id filtering, and link sanitization are
unchanged (per the parent spec's non-goals).

### 4. Report assembly — `api/reporting.py`

`build_markdown_report()` replaces `extract_citation_ids(content)` with
`extract_cited_evidence_ids(content, evidence_items)`. Per-section and global source
tables are otherwise unchanged; they already consume the returned id list.

### 5. Validator — `graph/report_validator.py`

`_citation_warnings()` replaces `extract_citation_ids(text)` with
`extract_cited_evidence_ids(text, evidence_items)`. Consequence: the "无效引用" warning
disappears, because the resolver returns only known ids (unmatched tokens are silently
ignored). The "未发现来源引用" warning is retained (empty result on a non-empty section
that has evidence). This is an accepted simplification — in label mode the validator
cannot distinguish an invented label from a typo'd one, and name/number correction
remains the validator's primary job.

## Testing

- `extract_cited_evidence_ids`: label token → correct id; `[S#]` token → same id
  (dual-mode); unknown token ignored; a label shared by two items → both ids in
  first-seen order; order preserved and deduped; a markdown-link label that is not a
  known label is ignored.
- `render_source_table`: "编号" shows the label; falls back to `[S#]` when no label;
  columns/headers unchanged; unknown ids still filtered; links still sanitized.
- `api/reporting.build_markdown_report`: a report citing `[历史行情（OHLCV）]` yields a
  source-table row.
- `report_validator._citation_warnings`: a label-cited section produces no
  "未发现来源引用" warning; a non-empty section with evidence but no recognizable
  citation still warns.
- `get_citation_instruction`: assert it instructs copying the bracketed label and still
  forbids invention; drop the `[S#]` assertion.

## Non-goals

- Do not change vendor-routing order or source registration metadata.
- Do not rewrite `S#` ids in stored historical report text.
- Do not alter source-table columns, link sanitization, or report export endpoints.
- Do not restore per-token "invalid citation id" validation warnings.
