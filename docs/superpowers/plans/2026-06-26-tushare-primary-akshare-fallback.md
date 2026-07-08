# Tushare Primary, AKShare Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Tushare Pro as the primary mainland China data source, with AKShare as fallback and supplement.

**Architecture:** Add focused Tushare vendor modules under `tradingagents/dataflows/`, register them in the existing `route_to_vendor()` abstraction, and change the default China vendor chain to `tushare,akshare` for price, indicators, and fundamentals. Tushare token handling, cache, error mapping, and WebUI health checks stay isolated from agent logic.

**Tech Stack:** Python 3.10+, pandas, stockstats, tushare SDK, pytest, ruff, existing TradingAgents vendor router.

---

## File Structure

- Create `tradingagents/dataflows/tushare_utils.py`
  - Owns token lookup, lazy Tushare client creation, Tushare cache helpers, symbol conversion, error classification, and a retry/call wrapper.
- Create `tradingagents/dataflows/tushare_stock.py`
  - Owns Tushare daily OHLCV retrieval for A shares and mainland ETFs/funds.
- Create `tradingagents/dataflows/tushare_indicator.py`
  - Owns Tushare-backed local `stockstats` indicator computation.
- Create `tradingagents/dataflows/tushare_fundamentals.py`
  - Owns Tushare ETF/fund reports, A-share financial statements, and ETF statement not-applicable responses.
- Modify `tradingagents/dataflows/interface.py`
  - Registers `tushare` and preserves explicit `tushare,akshare` order for mainland symbols.
- Modify `tradingagents/default_config.py`
  - Makes Tushare the default primary vendor for China price, indicators, and fundamentals.
- Modify `.env.example`
  - Documents `TUSHARE_TOKEN`.
- Modify `api/service_health.py`
  - Adds a Tushare health probe.
- Modify `pyproject.toml` and `uv.lock`
  - Adds the Tushare SDK dependency if it is not already installed.
- Modify tests:
  - `tests/test_china_only_data_sources.py`
  - `tests/test_vendor_routing.py`
  - `tests/test_vendor_errors.py`
  - `tests/test_tushare_dataflows.py`
  - `tests/webui/test_routes_health.py`

---

### Task 1: Dependency And Default Vendor Routing

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `tradingagents/default_config.py`
- Modify: `tradingagents/dataflows/interface.py`
- Modify: `.env.example`
- Test: `tests/test_china_only_data_sources.py`
- Test: `tests/test_vendor_routing.py`

- [ ] **Step 1: Write failing default-config test**

In `tests/test_china_only_data_sources.py`, update `test_default_config_uses_domestic_china_data_sources_only` to assert the new default chain:

```python
@pytest.mark.unit
def test_default_config_uses_domestic_china_data_sources_only():
    assert DEFAULT_CONFIG["domestic_china_only"] is True
    assert DEFAULT_CONFIG["data_vendors"]["core_stock_apis"] == "tushare,akshare"
    assert DEFAULT_CONFIG["data_vendors"]["technical_indicators"] == "tushare,akshare"
    assert DEFAULT_CONFIG["data_vendors"]["fundamental_data"] == "tushare,akshare"
    assert DEFAULT_CONFIG["data_vendors"]["news_data"] == "akshare"
    assert DEFAULT_CONFIG["data_vendors"]["macro_data"] == "disabled"
    assert DEFAULT_CONFIG["data_vendors"]["prediction_markets"] == "disabled"
```

- [ ] **Step 2: Write failing explicit-order router test**

Add this test to `tests/test_vendor_routing.py` inside `VendorRoutingTests`:

```python
def test_explicit_tushare_chain_is_not_reordered_by_akshare_auto_route(self):
    set_config({"data_vendors": {"core_stock_apis": "tushare,akshare"}})
    calls: list[str] = []

    def tushare(symbol, *a, **k):
        calls.append("tushare")
        return "TS_DATA"

    def akshare(symbol, *a, **k):
        calls.append("akshare")
        return "AK_DATA"

    with self._route({"tushare": tushare, "akshare": akshare}):
        result = interface.route_to_vendor(
            "get_stock_data",
            "159241",
            "2026-06-01",
            "2026-06-20",
        )

    self.assertEqual(result, "TS_DATA")
    self.assertEqual(calls, ["tushare"])
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
pytest tests/test_china_only_data_sources.py::test_default_config_uses_domestic_china_data_sources_only tests/test_vendor_routing.py::VendorRoutingTests::test_explicit_tushare_chain_is_not_reordered_by_akshare_auto_route -v
```

Expected:

- Config test fails because defaults still say `akshare`.
- Router test fails because `akshare_auto_route` moves AKShare first.

- [ ] **Step 4: Add Tushare dependency**

In `pyproject.toml`, add the dependency in the `[project].dependencies` list near the other data dependencies:

```toml
    "tushare>=1.4.21",
```

Then run:

```bash
uv lock
```

Expected:

- `uv.lock` updates with the Tushare package and its transitive dependencies.

- [ ] **Step 5: Update default config and environment example**

In `tradingagents/default_config.py`, change only the `data_vendors` defaults and nearby comments:

```python
    "data_vendors": {
        "core_stock_apis": "tushare,akshare",      # Options: tushare, akshare, alpha_vantage, yfinance
        "technical_indicators": "tushare,akshare", # Options: tushare, akshare, alpha_vantage, yfinance
        "fundamental_data": "tushare,akshare",     # Options: tushare, akshare, alpha_vantage, yfinance
        "news_data": "akshare",                    # Options: akshare, alpha_vantage, yfinance
        "macro_data": "disabled",                  # Options: fred, disabled
        "prediction_markets": "disabled",          # Options: polymarket, disabled
    },
```

In `.env.example`, add this near the FRED data-source section:

```bash
# Tushare Pro token for mainland China market data.
#TUSHARE_TOKEN=
```

- [ ] **Step 6: Preserve explicit Tushare order in the router**

In `tradingagents/dataflows/interface.py`, update the auto-route block so AKShare only moves first when the explicit chain does not already contain `tushare`:

```python
    if config.get("akshare_auto_route", True) and "akshare" in VENDOR_METHODS[method]:
        symbol = args[0] if args else kwargs.get("symbol") or kwargs.get("ticker")
        explicit_vendor_names = {v.lower() for v in explicit}
        if (
            isinstance(symbol, str)
            and _is_a_share_symbol(symbol)
            and "tushare" not in explicit_vendor_names
        ):
            vendor_chain = ["akshare"] + [v for v in vendor_chain if v != "akshare"]
```

- [ ] **Step 7: Run tests to verify routing change passes**

Run:

```bash
pytest tests/test_china_only_data_sources.py::test_default_config_uses_domestic_china_data_sources_only tests/test_vendor_routing.py::VendorRoutingTests::test_explicit_tushare_chain_is_not_reordered_by_akshare_auto_route -v
```

Expected: both tests pass. The router test uses a patched `VENDOR_METHODS` entry, so it verifies order-preservation before the real Tushare modules exist.

- [ ] **Step 8: Commit**

Run:

```bash
git add pyproject.toml uv.lock .env.example tradingagents/default_config.py tradingagents/dataflows/interface.py tests/test_china_only_data_sources.py tests/test_vendor_routing.py
git commit -m "feat(data): prefer tushare for china defaults"
```

---

### Task 2: Tushare Utility Layer

**Files:**
- Create: `tradingagents/dataflows/tushare_utils.py`
- Test: `tests/test_vendor_errors.py`
- Test: `tests/test_tushare_dataflows.py`

- [ ] **Step 1: Write failing utility tests**

Create `tests/test_tushare_dataflows.py` with these imports and tests:

```python
from unittest import mock

import pandas as pd
import pytest

from tradingagents.dataflows.errors import VendorNotConfiguredError, VendorRateLimitError


@pytest.mark.unit
def test_tushare_client_requires_token(monkeypatch):
    from tradingagents.dataflows import tushare_utils

    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    tushare_utils.reset_tushare_client()

    with pytest.raises(VendorNotConfiguredError):
        tushare_utils.get_tushare_client()


@pytest.mark.unit
def test_tushare_client_uses_env_token_without_logging_it(monkeypatch):
    from tradingagents.dataflows import tushare_utils

    client = object()
    pro_api = mock.Mock(return_value=client)
    monkeypatch.setenv("TUSHARE_TOKEN", "secret-token")
    monkeypatch.setattr(tushare_utils.ts, "set_token", mock.Mock())
    monkeypatch.setattr(tushare_utils.ts, "pro_api", pro_api)
    tushare_utils.reset_tushare_client()

    assert tushare_utils.get_tushare_client() is client
    tushare_utils.ts.set_token.assert_called_once_with("secret-token")
    pro_api.assert_called_once()


@pytest.mark.unit
def test_tushare_call_maps_permission_message_to_rate_limit():
    from tradingagents.dataflows.tushare_utils import call_tushare

    def denied():
        raise Exception("抱歉，您没有访问该接口的权限，权限的具体详情访问")

    with pytest.raises(VendorRateLimitError):
        call_tushare(denied)


@pytest.mark.unit
def test_tushare_cached_call_round_trips_dataframe(tmp_path, monkeypatch):
    from tradingagents.dataflows import tushare_utils

    monkeypatch.setattr(
        "tradingagents.dataflows.config.get_config",
        lambda: {"data_cache_dir": str(tmp_path)},
    )
    calls = 0

    def fetch():
        nonlocal calls
        calls += 1
        return pd.DataFrame([{"a": 1}])

    first = tushare_utils.cached_call("unit/key", 3600, fetch)
    second = tushare_utils.cached_call("unit/key", 3600, fetch)

    assert calls == 1
    pd.testing.assert_frame_equal(first, second)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_tushare_dataflows.py::test_tushare_client_requires_token tests/test_tushare_dataflows.py::test_tushare_client_uses_env_token_without_logging_it tests/test_tushare_dataflows.py::test_tushare_call_maps_permission_message_to_rate_limit tests/test_tushare_dataflows.py::test_tushare_cached_call_round_trips_dataframe -v
```

Expected: import failure because `tushare_utils.py` does not exist.

- [ ] **Step 3: Create `tushare_utils.py`**

Create `tradingagents/dataflows/tushare_utils.py`:

```python
"""Tushare Pro vendor helpers: token setup, caching, symbols, and errors."""

from __future__ import annotations

import contextlib
import logging
import os
import re
import time
from collections.abc import Callable
from typing import TypeVar

import pandas as pd
import requests
import tushare as ts

from .akshare_utils import display_symbol, is_a_share, is_etf_code, to_bare_code
from .errors import VendorNotConfiguredError, VendorRateLimitError

logger = logging.getLogger(__name__)

T = TypeVar("T")
_CLIENT = None

_RATE_OR_PERMISSION_PATTERNS = (
    "没有访问该接口的权限",
    "权限",
    "积分",
    "每分钟最多访问",
    "超过每分钟",
    "访问次数",
    "抱歉",
)

_NETWORK_ERRORS = (
    requests.exceptions.ConnectionError,
    requests.exceptions.ProxyError,
    requests.exceptions.Timeout,
    requests.exceptions.ChunkedEncodingError,
)


class TushareNotConfiguredError(VendorNotConfiguredError):
    """Tushare was selected but TUSHARE_TOKEN is missing or unusable."""


class TushareRateLimitError(VendorRateLimitError):
    """Tushare refused the request due to permission, points, or throttling."""


def reset_tushare_client() -> None:
    """Clear the cached Tushare client, primarily for tests."""
    global _CLIENT
    _CLIENT = None


def get_tushare_client():
    """Return a lazily initialized Tushare Pro client."""
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT

    token = os.getenv("TUSHARE_TOKEN", "").strip()
    if not token:
        raise TushareNotConfiguredError("TUSHARE_TOKEN environment variable is not set.")

    ts.set_token(token)
    _CLIENT = ts.pro_api()
    return _CLIENT


def call_tushare(func: Callable[[], T]) -> T:
    """Call Tushare and map common vendor messages into router-aware errors."""
    try:
        return func()
    except VendorNotConfiguredError:
        raise
    except VendorRateLimitError:
        raise
    except _NETWORK_ERRORS:
        raise
    except Exception as exc:
        message = str(exc)
        if any(pattern in message for pattern in _RATE_OR_PERMISSION_PATTERNS):
            raise TushareRateLimitError(message) from exc
        if "token" in message.lower():
            raise TushareNotConfiguredError("Tushare token is invalid or rejected.") from exc
        raise


def _cache_dir() -> str:
    """Return the Tushare cache directory."""
    from .config import get_config

    base = get_config().get("data_cache_dir") or os.path.join(
        os.path.expanduser("~"), ".tradingagents", "cache"
    )
    path = os.path.join(base, "tushare")
    os.makedirs(path, exist_ok=True)
    return path


def cached_call(key: str, ttl_seconds: int, func: Callable[[], T]) -> T:
    """Return a cached DataFrame for key or fetch and cache a fresh value."""
    safe_key = re.sub(r"[^A-Za-z0-9_.\\-]", "_", key)
    cache_file = os.path.join(_cache_dir(), f"{safe_key}.pkl")

    if os.path.exists(cache_file):
        age = time.time() - os.path.getmtime(cache_file)
        if age < ttl_seconds:
            try:
                return pd.read_pickle(cache_file)
            except Exception as exc:
                logger.warning("Tushare cache unreadable (%s), refetching: %s", cache_file, exc)

    result = func()
    with contextlib.suppress(Exception):
        if isinstance(result, pd.DataFrame):
            result.to_pickle(cache_file)
    return result


def to_ts_code(symbol: str) -> str:
    """Convert a mainland symbol to Tushare ts_code form."""
    label = display_symbol(symbol)
    code, suffix = label.split(".")
    exchange = "SH" if suffix == "SS" else suffix
    return f"{code}.{exchange}"


def is_mainland_symbol(symbol: str) -> bool:
    """Return True for mainland A-share or listed fund symbols."""
    return is_a_share(symbol)


def is_fund_symbol(symbol: str) -> bool:
    """Return True for mainland listed fund/ETF symbols."""
    return is_etf_code(to_bare_code(symbol))
```

- [ ] **Step 4: Run utility tests**

Run:

```bash
pytest tests/test_tushare_dataflows.py::test_tushare_client_requires_token tests/test_tushare_dataflows.py::test_tushare_client_uses_env_token_without_logging_it tests/test_tushare_dataflows.py::test_tushare_call_maps_permission_message_to_rate_limit tests/test_tushare_dataflows.py::test_tushare_cached_call_round_trips_dataframe -v
```

Expected: all four tests pass.

- [ ] **Step 5: Add hierarchy tests for Tushare named errors**

In `tests/test_vendor_errors.py`, import the Tushare errors inside the test and add:

```python
    def test_tushare_named_errors_subclass_generic_bases(self):
        from tradingagents.dataflows.tushare_utils import (
            TushareNotConfiguredError,
            TushareRateLimitError,
        )

        self.assertTrue(issubclass(TushareRateLimitError, VendorRateLimitError))
        self.assertTrue(issubclass(TushareNotConfiguredError, VendorNotConfiguredError))
        self.assertTrue(issubclass(TushareNotConfiguredError, ValueError))
```

- [ ] **Step 6: Run hierarchy test**

Run:

```bash
pytest tests/test_vendor_errors.py::HierarchyTests::test_tushare_named_errors_subclass_generic_bases -v
```

Expected: pass.

- [ ] **Step 7: Commit**

Run:

```bash
git add tradingagents/dataflows/tushare_utils.py tests/test_tushare_dataflows.py tests/test_vendor_errors.py
git commit -m "feat(data): add tushare utility layer"
```

---

### Task 3: Tushare Price Data And Vendor Registration

**Files:**
- Create: `tradingagents/dataflows/tushare_stock.py`
- Modify: `tradingagents/dataflows/interface.py`
- Test: `tests/test_tushare_dataflows.py`
- Test: `tests/test_vendor_routing.py`

- [ ] **Step 1: Add failing stock normalization tests**

Append these tests to `tests/test_tushare_dataflows.py`:

```python
@pytest.mark.unit
def test_tushare_stock_normalizes_fund_daily(monkeypatch):
    from tradingagents.dataflows import tushare_stock

    raw = pd.DataFrame(
        [
            {
                "trade_date": "20260619",
                "open": 1.01,
                "high": 1.05,
                "low": 1.00,
                "close": 1.04,
                "vol": 1000,
                "amount": 1234.5,
            }
        ]
    )
    client = mock.Mock()
    client.fund_daily.return_value = raw
    monkeypatch.setattr(tushare_stock, "get_tushare_client", lambda: client)
    monkeypatch.setattr(tushare_stock, "call_tushare", lambda func: func())
    monkeypatch.setattr(tushare_stock, "cached_call", lambda _key, _ttl, func: func())

    result = tushare_stock.get_stock_data("159241", "2026-06-01", "2026-06-20")

    assert "Stock data for 159241.SZ (Tushare Pro)" in result
    assert "Date,Open,High,Low,Close,Volume,Amount" in result
    assert "2026-06-19,1.01,1.05,1.0,1.04,1000,1234.5" in result
    client.fund_daily.assert_called_once()


@pytest.mark.unit
def test_tushare_stock_normalizes_a_share_daily(monkeypatch):
    from tradingagents.dataflows import tushare_stock

    raw = pd.DataFrame(
        [
            {
                "trade_date": "20260619",
                "open": 10.0,
                "high": 10.5,
                "low": 9.8,
                "close": 10.2,
                "vol": 2000,
                "amount": 3000,
            }
        ]
    )
    client = mock.Mock()
    client.daily.return_value = raw
    monkeypatch.setattr(tushare_stock, "get_tushare_client", lambda: client)
    monkeypatch.setattr(tushare_stock, "call_tushare", lambda func: func())
    monkeypatch.setattr(tushare_stock, "cached_call", lambda _key, _ttl, func: func())

    result = tushare_stock.get_stock_data("600519", "2026-06-01", "2026-06-20")

    assert "Stock data for 600519.SS (Tushare Pro)" in result
    assert "2026-06-19,10.0,10.5,9.8,10.2,2000,3000" in result
    client.daily.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_tushare_dataflows.py::test_tushare_stock_normalizes_fund_daily tests/test_tushare_dataflows.py::test_tushare_stock_normalizes_a_share_daily -v
```

Expected: import failures because `tushare_stock.py` does not exist.

- [ ] **Step 3: Create `tushare_stock.py`**

Create `tradingagents/dataflows/tushare_stock.py`:

```python
"""Tushare Pro mainland China OHLCV price data."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

import pandas as pd

from .errors import NoMarketDataError
from .stockstats_utils import MAX_OHLCV_STALE_DAYS
from .tushare_utils import (
    cached_call,
    call_tushare,
    display_symbol,
    get_tushare_client,
    is_fund_symbol,
    is_mainland_symbol,
    to_ts_code,
)

_PRICE_TTL_SECONDS = 6 * 3600
_COLUMN_MAP = {
    "trade_date": "Date",
    "open": "Open",
    "high": "High",
    "low": "Low",
    "close": "Close",
    "vol": "Volume",
    "amount": "Amount",
}


def _normalize_frame(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.rename(columns=_COLUMN_MAP).copy()
    df["Date"] = pd.to_datetime(df["Date"], format="%Y%m%d", errors="coerce")
    df = df.dropna(subset=["Date"]).sort_values("Date").set_index("Date")
    keep = [c for c in ("Open", "High", "Low", "Close", "Volume", "Amount") if c in df.columns]
    df = df[keep]
    for col in ("Open", "High", "Low", "Close", "Amount"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").round(4)
    if "Volume" in df.columns:
        df["Volume"] = pd.to_numeric(df["Volume"], errors="coerce")
    return df


def _fetch_daily(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    ts_code = to_ts_code(symbol)
    start = start_date.replace("-", "")
    end = end_date.replace("-", "")
    client = get_tushare_client()

    def fetch():
        if is_fund_symbol(symbol):
            return client.fund_daily(ts_code=ts_code, start_date=start, end_date=end)
        return client.daily(ts_code=ts_code, start_date=start, end_date=end)

    key = f"daily_{ts_code}_{start}_{end}"
    return cached_call(key, _PRICE_TTL_SECONDS, lambda: call_tushare(fetch))


def get_stock_data(
    symbol: Annotated[str, "Mainland ticker (600519, 600519.SS, 159241, ...)"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    if not is_mainland_symbol(symbol):
        raise NoMarketDataError(symbol, symbol, "not a mainland China symbol for Tushare")

    datetime.strptime(start_date, "%Y-%m-%d")
    datetime.strptime(end_date, "%Y-%m-%d")
    label = display_symbol(symbol)

    raw = _fetch_daily(symbol, start_date, end_date)
    if raw is None or raw.empty:
        raise NoMarketDataError(symbol, label, f"no rows between {start_date} and {end_date}")

    data = _normalize_frame(raw)
    if data.empty:
        raise NoMarketDataError(symbol, label, f"no usable rows between {start_date} and {end_date}")

    latest = data.index.max().normalize()
    requested = pd.to_datetime(end_date).normalize()
    stale_days = (requested - latest).days
    if stale_days > MAX_OHLCV_STALE_DAYS:
        raise NoMarketDataError(
            symbol,
            label,
            f"latest row is {latest.date()}, {stale_days} days before the requested {requested.date()} (stale) — refusing to use it",
        )

    header = f"# Stock data for {label} (Tushare Pro) from {start_date} to {end_date}\n"
    header += f"# Total records: {len(data)}\n"
    header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    return header + data.to_csv()
```

- [ ] **Step 4: Register Tushare stock import and method**

In `tradingagents/dataflows/interface.py`, add this import:

```python
from .tushare_stock import get_stock_data as get_tushare_stock
```

Add `tushare` to `VENDOR_LIST`:

```python
VENDOR_LIST = [
    "yfinance",
    "fred",
    "polymarket",
    "alpha_vantage",
    "tushare",
    "akshare",
]
```

Add Tushare entries:

```python
"get_stock_data": {
    "alpha_vantage": get_alpha_vantage_stock,
    "yfinance": get_YFin_data_online,
    "tushare": get_tushare_stock,
    "akshare": get_akshare_stock,
},
```

- [ ] **Step 5: Run price tests**

Run:

```bash
pytest tests/test_tushare_dataflows.py::test_tushare_stock_normalizes_fund_daily tests/test_tushare_dataflows.py::test_tushare_stock_normalizes_a_share_daily -v
```

Expected: pass.

- [ ] **Step 6: Run router fallback smoke test with stock registration**

Run:

```bash
pytest tests/test_vendor_routing.py::VendorRoutingTests::test_explicit_tushare_chain_is_not_reordered_by_akshare_auto_route -v
```

Expected: pass.

- [ ] **Step 7: Commit**

Run:

```bash
git add tradingagents/dataflows/tushare_stock.py tradingagents/dataflows/interface.py tests/test_tushare_dataflows.py tests/test_vendor_routing.py
git commit -m "feat(data): add tushare price vendor"
```

---

### Task 4: Tushare Technical Indicators

**Files:**
- Create: `tradingagents/dataflows/tushare_indicator.py`
- Modify: `tradingagents/dataflows/interface.py`
- Test: `tests/test_tushare_dataflows.py`

- [ ] **Step 1: Add failing indicator test**

Append this test to `tests/test_tushare_dataflows.py`:

```python
@pytest.mark.unit
def test_tushare_indicator_uses_local_stockstats(monkeypatch):
    from tradingagents.dataflows import tushare_indicator

    frame = pd.DataFrame(
        {
            "Date": pd.date_range("2026-06-01", periods=15, freq="D"),
            "Open": [1.0 + i / 100 for i in range(15)],
            "High": [1.1 + i / 100 for i in range(15)],
            "Low": [0.9 + i / 100 for i in range(15)],
            "Close": [1.0 + i / 100 for i in range(15)],
            "Volume": [1000 + i for i in range(15)],
        }
    )
    monkeypatch.setattr(tushare_indicator, "_load_tushare_ohlcv", lambda symbol, curr_date: frame)

    result = tushare_indicator.get_indicators("159241", "close_10_ema", "2026-06-15", 3)

    assert "## close_10_ema values from 2026-06-12 to 2026-06-15" in result
    assert "2026-06-15:" in result
    assert "10 EMA" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/test_tushare_dataflows.py::test_tushare_indicator_uses_local_stockstats -v
```

Expected: import failure because `tushare_indicator.py` does not exist.

- [ ] **Step 3: Create `tushare_indicator.py`**

Create `tradingagents/dataflows/tushare_indicator.py`:

```python
"""Tushare Pro technical indicators computed locally with stockstats."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

import pandas as pd
from dateutil.relativedelta import relativedelta
from stockstats import wrap

from .akshare_indicator import _indicator_description
from .errors import NoMarketDataError
from .tushare_stock import _fetch_daily, _normalize_frame
from .tushare_utils import is_mainland_symbol

_SUPPORTED = (
    "close_50_sma", "close_200_sma", "close_10_ema",
    "macd", "macds", "macdh",
    "rsi", "boll", "boll_ub", "boll_lb", "atr", "vwma", "mfi",
)


def _load_tushare_ohlcv(symbol: str, curr_date: str) -> pd.DataFrame:
    curr_dt = pd.to_datetime(curr_date)
    start = (curr_dt - pd.DateOffset(years=5)).strftime("%Y-%m-%d")
    end = curr_dt.strftime("%Y-%m-%d")
    raw = _fetch_daily(symbol, start, end)
    if raw is None or raw.empty:
        raise NoMarketDataError(symbol, symbol, "Tushare returned no rows for indicators")
    data = _normalize_frame(raw).reset_index()
    data = data[data["Date"] <= curr_dt]
    if data.empty:
        raise NoMarketDataError(symbol, symbol, "no Tushare rows on/before curr_date")
    return data


def _bulk_indicator(symbol: str, indicator: str, curr_date: str) -> dict[str, str]:
    data = _load_tushare_ohlcv(symbol, curr_date)
    df = wrap(data)
    df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")
    df[indicator]
    result: dict[str, str] = {}
    for _, row in df.iterrows():
        value = row[indicator]
        result[row["Date"]] = "N/A" if pd.isna(value) else str(value)
    return result


def get_indicators(
    symbol: Annotated[str, "Mainland ticker (600519, 159241, ...)"],
    indicator: Annotated[str, "technical indicator to get the analysis and report of"],
    curr_date: Annotated[str, "The current trading date you are trading on, YYYY-mm-dd"],
    look_back_days: Annotated[int, "how many days to look back"],
) -> str:
    if not is_mainland_symbol(symbol):
        raise NoMarketDataError(symbol, symbol, "not a mainland China symbol for Tushare")
    if indicator not in _SUPPORTED:
        raise ValueError(f"Indicator {indicator} is not supported. Please choose from: {list(_SUPPORTED)}")

    end_date = curr_date
    curr_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    before = curr_dt - relativedelta(days=look_back_days)
    indicator_data = _bulk_indicator(symbol, indicator, curr_date)

    cursor = curr_dt
    ind_string = ""
    while cursor >= before:
        date_str = cursor.strftime("%Y-%m-%d")
        value = indicator_data.get(date_str, "N/A: Not a trading day (weekend or holiday)")
        ind_string += f"{date_str}: {value}\n"
        cursor = cursor - relativedelta(days=1)

    return (
        f"## {indicator} values from {before.strftime('%Y-%m-%d')} to {end_date}:\n\n"
        + ind_string
        + "\n\n"
        + _indicator_description(indicator)
    )
```

- [ ] **Step 4: Register indicator vendor**

In `tradingagents/dataflows/interface.py`, add this import:

```python
from .tushare_indicator import get_indicators as get_tushare_indicators
```

Then ensure this entry exists:

```python
"get_indicators": {
    "alpha_vantage": get_alpha_vantage_indicator,
    "yfinance": get_stock_stats_indicators_window,
    "tushare": get_tushare_indicators,
    "akshare": get_akshare_indicators,
},
```

- [ ] **Step 5: Run indicator test**

Run:

```bash
pytest tests/test_tushare_dataflows.py::test_tushare_indicator_uses_local_stockstats -v
```

Expected: pass.

- [ ] **Step 6: Commit**

Run:

```bash
git add tradingagents/dataflows/tushare_indicator.py tradingagents/dataflows/interface.py tests/test_tushare_dataflows.py
git commit -m "feat(data): compute tushare indicators locally"
```

---

### Task 5: Tushare Fundamentals And Statements

**Files:**
- Create: `tradingagents/dataflows/tushare_fundamentals.py`
- Modify: `tradingagents/dataflows/interface.py`
- Test: `tests/test_tushare_dataflows.py`

- [ ] **Step 1: Add failing ETF fundamentals and statement tests**

Append these tests to `tests/test_tushare_dataflows.py`:

```python
@pytest.mark.unit
def test_tushare_etf_fundamentals_include_basic_adj_and_portfolio(monkeypatch):
    from tradingagents.dataflows import tushare_fundamentals

    client = mock.Mock()
    client.fund_basic.return_value = pd.DataFrame([{"ts_code": "159241.SZ", "name": "国防ETF"}])
    client.fund_adj.return_value = pd.DataFrame([{"trade_date": "20260619", "adj_factor": 1.02}])
    client.fund_portfolio.return_value = pd.DataFrame(
        [{"end_date": "20260331", "symbol": "600519.SH", "mkv": 100.0, "amount": 10.0}]
    )
    client.fund_daily.return_value = pd.DataFrame([{"trade_date": "20260619", "close": 1.04}])
    monkeypatch.setattr(tushare_fundamentals, "get_tushare_client", lambda: client)
    monkeypatch.setattr(tushare_fundamentals, "call_tushare", lambda func: func())
    monkeypatch.setattr(tushare_fundamentals, "cached_call", lambda _key, _ttl, func: func())

    result = tushare_fundamentals.get_fundamentals("159241", "2026-06-19")

    assert "Fund/ETF Fundamentals for 159241.SZ (Tushare Pro)" in result
    assert "Fund Basic" in result
    assert "Recent Fund Daily Data" in result
    assert "Adjustment Factors" in result
    assert "Portfolio Holdings" in result
    assert "IOPV" not in result


@pytest.mark.unit
def test_tushare_etf_statements_are_not_applicable():
    from tradingagents.dataflows.tushare_fundamentals import (
        get_balance_sheet,
        get_cashflow,
        get_income_statement,
    )

    for result in (
        get_balance_sheet("159241", curr_date="2026-06-19"),
        get_income_statement("159241", curr_date="2026-06-19"),
        get_cashflow("159241", curr_date="2026-06-19"),
    ):
        assert "ETF/Fund" in result
        assert "not_applicable" in result


@pytest.mark.unit
def test_tushare_a_share_statement_filters_future_periods(monkeypatch):
    from tradingagents.dataflows import tushare_fundamentals

    client = mock.Mock()
    client.balancesheet.return_value = pd.DataFrame(
        [
            {"ann_date": "20260430", "end_date": "20260331", "total_assets": 100},
            {"ann_date": "20260731", "end_date": "20260630", "total_assets": 120},
        ]
    )
    monkeypatch.setattr(tushare_fundamentals, "get_tushare_client", lambda: client)
    monkeypatch.setattr(tushare_fundamentals, "call_tushare", lambda func: func())
    monkeypatch.setattr(tushare_fundamentals, "cached_call", lambda _key, _ttl, func: func())

    result = tushare_fundamentals.get_balance_sheet("600519", curr_date="2026-06-20")

    assert "2026-03-31" in result
    assert "2026-06-30" not in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_tushare_dataflows.py::test_tushare_etf_fundamentals_include_basic_adj_and_portfolio tests/test_tushare_dataflows.py::test_tushare_etf_statements_are_not_applicable tests/test_tushare_dataflows.py::test_tushare_a_share_statement_filters_future_periods -v
```

Expected: import failure because `tushare_fundamentals.py` does not exist.

- [ ] **Step 3: Create `tushare_fundamentals.py`**

Create `tradingagents/dataflows/tushare_fundamentals.py`:

```python
"""Tushare Pro mainland China fundamentals and statements."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

import pandas as pd

from .akshare_utils import display_symbol
from .errors import NoMarketDataError
from .tushare_utils import cached_call, call_tushare, get_tushare_client, is_fund_symbol, to_ts_code

_FUNDAMENTAL_TTL_SECONDS = 24 * 3600
_STATEMENT_METHODS = {
    "balance_sheet": "balancesheet",
    "income_statement": "income",
    "cashflow": "cashflow",
}


def _section(title: str, data: pd.DataFrame) -> str:
    if data is None or data.empty:
        return ""
    return f"\n## {title}\n\n" + data.to_csv(index=False)


def _fetch_optional(key: str, func):
    try:
        return cached_call(key, _FUNDAMENTAL_TTL_SECONDS, lambda: call_tushare(func))
    except Exception:
        return pd.DataFrame()


def _etf_statement_not_applicable(symbol: str, title: str, freq: str) -> str:
    label = display_symbol(symbol)
    header = f"# {title} for {label} (ETF/Fund, Tushare Pro, {freq})\n"
    header += "# Status: Not applicable to fund/ETF products\n"
    header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    return (
        header
        + "item,status,detail\n"
        + f"{title},not_applicable,"
        + "ETF/fund products do not publish operating-company financial statements; "
        + "use the Tushare fund/ETF fundamentals snapshot plus price and technical data.\n"
    )


def _fund_report(symbol: str, curr_date: str | None) -> str:
    label = display_symbol(symbol)
    ts_code = to_ts_code(symbol)
    client = get_tushare_client()
    end = (curr_date or pd.Timestamp.today().strftime("%Y-%m-%d")).replace("-", "")

    basic = _fetch_optional(
        f"fund_basic_{ts_code}",
        lambda: client.fund_basic(ts_code=ts_code),
    )
    daily = _fetch_optional(
        f"fund_daily_{ts_code}_{end}",
        lambda: client.fund_daily(ts_code=ts_code, end_date=end),
    ).head(5)
    adj = _fetch_optional(
        f"fund_adj_{ts_code}_{end}",
        lambda: client.fund_adj(ts_code=ts_code, end_date=end),
    ).head(5)
    portfolio = _fetch_optional(
        f"fund_portfolio_{ts_code}",
        lambda: client.fund_portfolio(ts_code=ts_code),
    ).head(20)

    if basic.empty and daily.empty and adj.empty and portfolio.empty:
        raise NoMarketDataError(symbol, label, "no Tushare fund fundamentals")

    header = f"# Fund/ETF Fundamentals for {label} (Tushare Pro)\n"
    header += "# Instrument type: Mainland China listed fund/ETF, not an operating company\n"
    header += "# Realtime IOPV, discount/premium, and order-book fields are not included in this Tushare tier\n"
    header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    result = header
    result += _section("Fund Basic", basic)
    result += _section("Recent Fund Daily Data", daily)
    result += _section("Adjustment Factors", adj)
    result += _section("Portfolio Holdings", portfolio)
    return result


def _statement_report(symbol: str, kind: str, title: str, freq: str, curr_date: str | None) -> str:
    label = display_symbol(symbol)
    ts_code = to_ts_code(symbol)
    client = get_tushare_client()
    method_name = _STATEMENT_METHODS[kind]
    method = getattr(client, method_name)
    raw = cached_call(
        f"{kind}_{ts_code}",
        _FUNDAMENTAL_TTL_SECONDS,
        lambda: call_tushare(lambda: method(ts_code=ts_code)),
    )
    if raw is None or raw.empty:
        raise NoMarketDataError(symbol, label, f"no Tushare {kind} data")

    data = raw.copy()
    date_column = "end_date" if "end_date" in data.columns else "ann_date"
    data[date_column] = pd.to_datetime(data[date_column], format="%Y%m%d", errors="coerce")
    if curr_date:
        cutoff = pd.Timestamp(curr_date)
        data = data[data[date_column] <= cutoff]
    if data.empty:
        raise NoMarketDataError(symbol, label, f"no {kind} periods on/before {curr_date}")

    data = data.sort_values(date_column, ascending=False)
    data[date_column] = data[date_column].dt.strftime("%Y-%m-%d")
    header = f"# {title} for {label} (A-share, Tushare Pro, {freq})\n"
    header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    return header + data.to_csv(index=False)


def get_fundamentals(
    ticker: Annotated[str, "Mainland ticker (600519, 159241, ...)"],
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
):
    if is_fund_symbol(ticker):
        return _fund_report(ticker, curr_date)

    label = display_symbol(ticker)
    ts_code = to_ts_code(ticker)
    client = get_tushare_client()
    basic = _fetch_optional(f"stock_basic_{ts_code}", lambda: client.stock_basic(ts_code=ts_code))
    indicators = _fetch_optional(f"fina_indicator_{ts_code}", lambda: client.fina_indicator(ts_code=ts_code)).head(8)
    if basic.empty and indicators.empty:
        raise NoMarketDataError(ticker, label, "no Tushare stock fundamentals")
    header = f"# Company Fundamentals for {label} (A-share, Tushare Pro)\n"
    header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    return header + _section("Stock Basic", basic) + _section("Financial Indicators", indicators)


def get_balance_sheet(
    ticker: Annotated[str, "Mainland ticker (600519, 159241, ...)"],
    freq: Annotated[str, "frequency hint, accepted for API parity"] = "quarterly",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
):
    if is_fund_symbol(ticker):
        return _etf_statement_not_applicable(ticker, "Balance Sheet", freq)
    return _statement_report(ticker, "balance_sheet", "Balance Sheet", freq, curr_date)


def get_income_statement(
    ticker: Annotated[str, "Mainland ticker (600519, 159241, ...)"],
    freq: Annotated[str, "frequency hint, accepted for API parity"] = "quarterly",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
):
    if is_fund_symbol(ticker):
        return _etf_statement_not_applicable(ticker, "Income Statement", freq)
    return _statement_report(ticker, "income_statement", "Income Statement", freq, curr_date)


def get_cashflow(
    ticker: Annotated[str, "Mainland ticker (600519, 159241, ...)"],
    freq: Annotated[str, "frequency hint, accepted for API parity"] = "quarterly",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
):
    if is_fund_symbol(ticker):
        return _etf_statement_not_applicable(ticker, "Cash Flow", freq)
    return _statement_report(ticker, "cashflow", "Cash Flow", freq, curr_date)
```

- [ ] **Step 4: Register fundamentals vendor**

In `tradingagents/dataflows/interface.py`, add these imports:

```python
from .tushare_fundamentals import (
    get_balance_sheet as get_tushare_balance_sheet,
    get_cashflow as get_tushare_cashflow,
    get_fundamentals as get_tushare_fundamentals,
    get_income_statement as get_tushare_income_statement,
)
```

Then ensure the Tushare entries exist:

```python
"get_fundamentals": {
    "alpha_vantage": get_alpha_vantage_fundamentals,
    "yfinance": get_yfinance_fundamentals,
    "tushare": get_tushare_fundamentals,
    "akshare": get_akshare_fundamentals,
},
"get_balance_sheet": {
    "alpha_vantage": get_alpha_vantage_balance_sheet,
    "yfinance": get_yfinance_balance_sheet,
    "tushare": get_tushare_balance_sheet,
    "akshare": get_akshare_balance_sheet,
},
"get_cashflow": {
    "alpha_vantage": get_alpha_vantage_cashflow,
    "yfinance": get_yfinance_cashflow,
    "tushare": get_tushare_cashflow,
    "akshare": get_akshare_cashflow,
},
"get_income_statement": {
    "alpha_vantage": get_alpha_vantage_income_statement,
    "yfinance": get_yfinance_income_statement,
    "tushare": get_tushare_income_statement,
    "akshare": get_akshare_income_statement,
},
```

- [ ] **Step 5: Run fundamentals tests**

Run:

```bash
pytest tests/test_tushare_dataflows.py::test_tushare_etf_fundamentals_include_basic_adj_and_portfolio tests/test_tushare_dataflows.py::test_tushare_etf_statements_are_not_applicable tests/test_tushare_dataflows.py::test_tushare_a_share_statement_filters_future_periods -v
```

Expected: pass.

- [ ] **Step 6: Add full registration test**

Add this test to `tests/test_vendor_routing.py`:

```python
def test_tushare_registered_for_china_core_methods(self):
    self.assertIn("tushare", interface.VENDOR_LIST)
    for method in (
        "get_stock_data",
        "get_indicators",
        "get_fundamentals",
        "get_balance_sheet",
        "get_cashflow",
        "get_income_statement",
    ):
        self.assertIn("tushare", interface.VENDOR_METHODS[method])
```

- [ ] **Step 7: Run registration test**

Run:

```bash
pytest tests/test_vendor_routing.py::VendorRoutingTests::test_tushare_registered_for_china_core_methods -v
```

Expected: pass.

- [ ] **Step 8: Commit**

Run:

```bash
git add tradingagents/dataflows/tushare_fundamentals.py tradingagents/dataflows/interface.py tests/test_tushare_dataflows.py tests/test_vendor_routing.py
git commit -m "feat(data): add tushare fundamentals vendor"
```

---

### Task 6: WebUI Health Check

**Files:**
- Modify: `api/service_health.py`
- Test: `tests/webui/test_routes_health.py`

- [ ] **Step 1: Add failing health tests**

Append these tests to `tests/webui/test_routes_health.py`:

```python
def test_data_probe_reports_missing_tushare_token(monkeypatch):
    from api.service_health import _probe_data_services

    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)

    statuses = list(
        _probe_data_services({"data_vendors": {"core_stock_apis": "tushare,akshare"}})
    )

    tushare = next(item for item in statuses if item["id"] == "data:tushare")
    assert tushare["status"] == "error"
    assert "TUSHARE_TOKEN" in tushare["message"]


def test_data_probe_reports_tushare_reachable(monkeypatch):
    from api.service_health import _probe_data_services

    monkeypatch.setenv("TUSHARE_TOKEN", "token")
    monkeypatch.setattr(
        "api.service_health._http_probe",
        lambda url, params=None: (True, "Reachable", 12),
    )

    statuses = list(
        _probe_data_services({"data_vendors": {"core_stock_apis": "tushare,akshare"}})
    )

    tushare = next(item for item in statuses if item["id"] == "data:tushare")
    assert tushare["status"] == "ok"
    assert tushare["latency_ms"] == 12
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/webui/test_routes_health.py::test_data_probe_reports_missing_tushare_token tests/webui/test_routes_health.py::test_data_probe_reports_tushare_reachable -v
```

Expected: failure because `data:tushare` is not emitted.

- [ ] **Step 3: Add Tushare health service**

In `api/service_health.py`, add this entry to `_DATA_SERVICES`:

```python
    "tushare": {
        "name": "Tushare Pro",
        "url": "https://api.tushare.pro",
        "params": {
            "api_name": "trade_cal",
            "params": "{}",
            "fields": "cal_date,is_open",
        },
        "env": "TUSHARE_TOKEN",
    },
```

Then update the API-key parameter handling in `_probe_data_services`:

```python
            if service_id == "fred":
                params["api_key"] = api_key
            elif service_id == "tushare":
                params["token"] = api_key
            else:
                params["apikey"] = api_key
```

- [ ] **Step 4: Run health tests**

Run:

```bash
pytest tests/webui/test_routes_health.py::test_data_probe_reports_missing_tushare_token tests/webui/test_routes_health.py::test_data_probe_reports_tushare_reachable -v
```

Expected: pass.

- [ ] **Step 5: Commit**

Run:

```bash
git add api/service_health.py tests/webui/test_routes_health.py
git commit -m "feat(webui): add tushare service health"
```

---

### Task 7: Fallback Behavior And Full Verification

**Files:**
- Modify: `tests/test_vendor_routing.py`
- Modify: `tests/test_tushare_dataflows.py`
- Modify: any Tushare module touched by fixes from this task

- [ ] **Step 1: Add fallback tests**

Add this test to `tests/test_vendor_routing.py`:

```python
def test_tushare_not_configured_falls_back_to_akshare(self):
    set_config({"data_vendors": {"core_stock_apis": "tushare,akshare"}})

    def tushare(*a, **k):
        from tradingagents.dataflows.tushare_utils import TushareNotConfiguredError

        raise TushareNotConfiguredError("no token")

    akshare = mock.Mock(return_value="AK_DATA")
    with self._route({"tushare": tushare, "akshare": akshare}):
        result = interface.route_to_vendor("get_stock_data", "159241", "2026-06-01", "2026-06-20")

    self.assertEqual(result, "AK_DATA")
    akshare.assert_called_once()
```

Add this test to `tests/test_tushare_dataflows.py`:

```python
@pytest.mark.unit
def test_tushare_stock_empty_frame_raises_no_market_data(monkeypatch):
    from tradingagents.dataflows import tushare_stock
    from tradingagents.dataflows.errors import NoMarketDataError

    client = mock.Mock()
    client.fund_daily.return_value = pd.DataFrame()
    monkeypatch.setattr(tushare_stock, "get_tushare_client", lambda: client)
    monkeypatch.setattr(tushare_stock, "call_tushare", lambda func: func())
    monkeypatch.setattr(tushare_stock, "cached_call", lambda _key, _ttl, func: func())

    with pytest.raises(NoMarketDataError):
        tushare_stock.get_stock_data("159241", "2026-06-01", "2026-06-20")
```

- [ ] **Step 2: Run fallback tests**

Run:

```bash
pytest tests/test_vendor_routing.py::VendorRoutingTests::test_tushare_not_configured_falls_back_to_akshare tests/test_tushare_dataflows.py::test_tushare_stock_empty_frame_raises_no_market_data -v
```

Expected: pass after prior tasks; fix any mismatch in error class imports or router registration.

- [ ] **Step 3: Run focused data/vendor test suite**

Run:

```bash
pytest tests/test_vendor_routing.py tests/test_vendor_errors.py tests/test_china_only_data_sources.py tests/test_tushare_dataflows.py tests/webui/test_routes_health.py -v
```

Expected: pass.

- [ ] **Step 4: Run lint on touched files**

Run:

```bash
ruff check tradingagents/dataflows/tushare_utils.py tradingagents/dataflows/tushare_stock.py tradingagents/dataflows/tushare_indicator.py tradingagents/dataflows/tushare_fundamentals.py tradingagents/dataflows/interface.py tradingagents/default_config.py api/service_health.py tests/test_tushare_dataflows.py tests/test_vendor_routing.py tests/test_vendor_errors.py tests/test_china_only_data_sources.py tests/webui/test_routes_health.py
```

Expected: pass.

- [ ] **Step 5: Run non-integration test suite if focused suite is green**

Run:

```bash
pytest -m "not integration"
```

Expected: pass. If unrelated existing failures appear, capture the failing test names and error summaries without broad refactors.

- [ ] **Step 6: Inspect final diff**

Run:

```bash
git diff --stat
git diff -- tradingagents/dataflows/interface.py tradingagents/default_config.py api/service_health.py
```

Expected:

- Tushare is added through the vendor abstraction only.
- Default vendor chains match the approved spec.
- News remains AKShare by default.
- No token appears in the diff.

- [ ] **Step 7: Commit final fixes**

Run:

```bash
git add tradingagents/dataflows tests api/service_health.py tradingagents/default_config.py .env.example pyproject.toml uv.lock
git commit -m "test(data): verify tushare fallback behavior"
```

---

## Final Verification

Run:

```bash
pytest tests/test_vendor_routing.py tests/test_vendor_errors.py tests/test_china_only_data_sources.py tests/test_tushare_dataflows.py tests/webui/test_routes_health.py -v
ruff check tradingagents/dataflows api/service_health.py tests/test_tushare_dataflows.py tests/test_vendor_routing.py tests/test_vendor_errors.py tests/test_china_only_data_sources.py tests/webui/test_routes_health.py
```

If time permits, also run:

```bash
pytest -m "not integration"
```

Do not run a real Tushare analysis as part of automated verification unless the user explicitly asks, because that may consume quota.
