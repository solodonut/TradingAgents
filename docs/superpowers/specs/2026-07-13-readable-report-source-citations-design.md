# Readable Report Source Citations Design

## Goal

Replace opaque report citations such as `[S1]` with the registered data or purpose name,
such as `[历史行情（OHLCV）]`, wherever tool output is presented to the agents and final
report.

## Scope

- Keep `S#` identifiers inside the evidence registry for deduplication, report validation,
  source-table lookup, and persisted run data.
- Change the human-facing evidence prefix generated for tool results to use a
  display label derived from the evidence item’s data/purpose.
- Preserve the existing per-section and report-wide source tables, including safe links.
- Use a stable readable fallback when an evidence item has no source name.

## Design

`EvidenceRegistry` remains the owner of internal citation IDs. `prefix_with_evidence()`
will resolve the registered evidence item for the supplied ID and render its readable
data/purpose label in brackets. For the 159915 analysis, examples include
`[历史行情（OHLCV）]`, `[已验证市场快照]`, `[10 日 EMA]`, `[MACD 柱状图（macdh）]`,
`[资产负债表]`, `[现金流量表]`, `[利润表]`, and `[综合基本面]`.

The display label is metadata distinct from the vendor name. `source_name` continues to
identify the provider in the source tables (for example AKShare or a configured vendor),
while the visible inline label identifies what the evidence represents. Indicator labels
must include their requested parameter where applicable: `10 日 EMA`, `200 日 SMA`,
`50 日 SMA`, `MACD`, `ATR`, `RSI`, `VWMA`, `布林带整体数据（boll）`,
`布林下轨（boll_lb）`, and `布林上轨（boll_ub）`.

The labels are assigned at evidence-registration time, not by the run-specific `S#`
number. The required mapping is:

| Evidence type | Inline label |
| --- | --- |
| Historical OHLCV | `历史行情（OHLCV）` |
| Verified market snapshot | `已验证市场快照` |
| EMA / SMA | `<周期> 日 EMA` / `<周期> 日 SMA` |
| Technical indicator | `MACD 柱状图（macdh）`, `布林带整体数据（boll）`, `MACD`, `ATR`, `RSI`, `VWMA`, `布林下轨（boll_lb）`, or `布林上轨（boll_ub）` as applicable |
| Balance sheet | `资产负债表` |
| Cash-flow statement | `现金流量表` |
| Income statement | `利润表` |
| Comprehensive fundamentals | `综合基本面` |

The registry ID is not exposed in the report body. Existing source-table rendering and
validation continue to operate on `S#` IDs and require no behavior change.

If a legacy or incomplete evidence item cannot resolve a non-empty display label, the
prefix falls back to its existing title, then the current `[S#]` form, so attribution is
never silently removed.

## Testing

- Update provenance unit tests to assert a historical OHLCV item renders as
  `[历史行情（OHLCV）]` and a technical indicator renders its named metric.
- Keep coverage that IDs are assigned and evidence records persist unchanged.
- Add a fallback assertion for an unavailable display label.

## Non-goals

- Do not change vendor-routing order or source registration metadata.
- Do not replace IDs in stored historical report text.
- Do not alter source-table columns, link sanitization, or report export endpoints.
