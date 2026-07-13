# Readable Report Source Citations Design

## Goal

Replace opaque report citations such as `[S1]` with the registered data-source name,
such as `[AKShare]`, wherever tool output is presented to the agents and final report.

## Scope

- Keep `S#` identifiers inside the evidence registry for deduplication, report validation,
  source-table lookup, and persisted run data.
- Change the human-facing evidence prefix generated for tool results to use
  `source_name`.
- Preserve the existing per-section and report-wide source tables, including safe links.
- Use a stable readable fallback when an evidence item has no source name.

## Design

`EvidenceRegistry` remains the owner of internal citation IDs. `prefix_with_evidence()`
will resolve the registered evidence item for the supplied ID and render its source name
in brackets. For example, an evidence record with `id="S1"` and
`source_name="AKShare"` produces `## [AKShare] get_stock_data: 600519`.

The registry ID is not exposed in the report body. Existing source-table rendering and
validation continue to operate on `S#` IDs and require no behavior change.

If a legacy or incomplete evidence item cannot resolve a non-empty source name, the
prefix falls back to the current `[S#]` form so attribution is never silently removed.

## Testing

- Update provenance unit tests to assert a registered `AKShare` item renders as
  `[AKShare]`.
- Keep coverage that IDs are assigned and evidence records persist unchanged.
- Add a fallback assertion for an unavailable source name.

## Non-goals

- Do not change vendor-routing order or source registration metadata.
- Do not replace IDs in stored historical report text.
- Do not alter source-table columns, link sanitization, or report export endpoints.
