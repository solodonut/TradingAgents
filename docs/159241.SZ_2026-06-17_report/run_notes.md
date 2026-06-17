# TradingAgents 159241.SZ Run Notes

Run date: 2026-06-17
Analysis date: 2026-06-17
Ticker: 159241.SZ
Resolved identity: TianHong CNI Aerospace ETF, SHZ

## Result

- Full report saved to `docs/159241.SZ_2026-06-17_report/complete_report.md`.
- Portfolio decision saved to `docs/159241.SZ_2026-06-17_report/5_portfolio/decision.md`.
- Final extracted signal: `Underweight`.
- Portfolio Manager rating: `Underweight`.
- Portfolio Manager text recommendation: defensive `HOLD` / reduce to below benchmark weight.

## Commands Used

```bash
.venv/bin/pytest tests/test_symbol_utils.py tests/test_vendor_routing.py tests/test_cli_symbol_handling.py tests/test_symbol_normalization_paths.py -q
```

Result: 44 passed.

The successful analysis run used Python 3.10 in `.venv`, with yfinance fallback for price and technical data:

```python
config["akshare_auto_route"] = False
config["data_vendors"].update({
    "core_stock_apis": "yfinance",
    "technical_indicators": "yfinance",
    "fundamental_data": "yfinance",
})
```

## Findings

- The repository requires Python >= 3.10. The system `python` and `python3` are 3.9.13, so the run needs an explicit Python 3.10 interpreter or a 3.10 virtualenv.
- A fresh isolated `.venv` plus `pip install -e ".[dev]" akshare` was needed. `akshare` is required by the default A-share/ETF route but is not declared in `pyproject.toml`.
- The default AKShare route failed for `159241.SZ` during the first full run after 6 retries with `RemoteDisconnected`.
- That AKShare failure aborted the LangGraph run because `route_to_vendor()` re-raised the first real vendor error when no fallback returned data. This differs from the project guidance that unavailable data should become `NO_DATA_AVAILABLE`.
- yfinance can fetch `159241.SZ` OHLCV and technical indicator inputs, so the full workflow completed after disabling AKShare auto-route and explicitly using yfinance for price/technical/fundamental vendor categories.
- Some auxiliary data was unavailable but did not abort the workflow: StockTwits 404, Reddit 429 retries, missing FRED configuration, Polymarket connection reset, ETF financial statements unavailable.

## Usability Verdict

TradingAgents can complete a useful multi-agent ETF analysis for `159241.SZ`, and the generated report is readable and well structured. Out of the box, the default A-share route is fragile in this environment because AKShare is both undeclared as a dependency and able to abort the whole graph on network failure.
