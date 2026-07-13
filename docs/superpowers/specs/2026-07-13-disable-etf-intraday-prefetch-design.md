# Disable ETF intraday analysis prefetch

## Goal

Prevent TradingAgents analysis runs from requesting `get_etf_intraday` while
preserving the dataflow function and diagnostics registration for explicit use.

## Design

`tradingagents.dataflows.prefetch.prefetch_snapshot()` will prefetch only
`news`, `indicators`, and `fundamentals`. It will not include an `intraday`
category or invoke `_fetch_intraday()`. `SnapshotSummary.for_context()` will
therefore not produce a prefetch quote for new analysis runs.

The Tushare implementation, vendor mapping, and diagnostics catalog remain
unchanged. Existing database rows are historical snapshots and are not deleted.

## Verification

A regression test will install an `_fetch_intraday()` sentinel that raises if
called, then assert a normal prefetch succeeds, writes only the three remaining
categories, and has no quote. The focused prefetch and WebUI graph-factory
tests will pass.
