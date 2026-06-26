"""The vendor data-error hierarchy: every "vendor couldn't return usable data"
condition derives from VendorError, so the router catches base types and any
vendor slots in without new handling.
"""
import copy
import importlib
import sys
import unittest
from unittest import mock

import pytest
import requests

import tradingagents.dataflows.config as config_module
import tradingagents.default_config as default_config
from tradingagents.dataflows import akshare_utils, interface
from tradingagents.dataflows.alpha_vantage_common import (
    AlphaVantageNotConfiguredError,
    AlphaVantageRateLimitError,
)
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.errors import (
    NoMarketDataError,
    VendorError,
    VendorNotConfiguredError,
    VendorRateLimitError,
)
from tradingagents.dataflows.fred import FredNotConfiguredError


@pytest.mark.unit
class HierarchyTests(unittest.TestCase):
    def test_all_conditions_derive_from_vendor_error(self):
        for cls in (NoMarketDataError, VendorRateLimitError, VendorNotConfiguredError):
            self.assertTrue(issubclass(cls, VendorError))

    def test_not_configured_is_still_a_value_error(self):
        # Back-compat: existing `except ValueError` callers keep working.
        self.assertTrue(issubclass(VendorNotConfiguredError, ValueError))

    def test_vendor_named_errors_subclass_the_generic_bases(self):
        self.assertTrue(issubclass(AlphaVantageRateLimitError, VendorRateLimitError))
        self.assertTrue(issubclass(AlphaVantageNotConfiguredError, VendorNotConfiguredError))
        self.assertTrue(issubclass(FredNotConfiguredError, VendorNotConfiguredError))
        # ... and therefore still ValueErrors
        self.assertTrue(issubclass(FredNotConfiguredError, ValueError))

    def test_tushare_named_errors_subclass_generic_bases(self):
        from tradingagents.dataflows.tushare_utils import (
            TushareNotConfiguredError,
            TushareRateLimitError,
        )

        self.assertTrue(issubclass(TushareNotConfiguredError, VendorNotConfiguredError))
        self.assertTrue(issubclass(TushareRateLimitError, VendorRateLimitError))
        self.assertTrue(issubclass(TushareNotConfiguredError, ValueError))

    def test_symbol_utils_reexports_no_market_data_error(self):
        from tradingagents.dataflows.symbol_utils import (
            NoMarketDataError as ReExported,
        )
        self.assertIs(ReExported, NoMarketDataError)

    def test_tushare_import_fallback_only_handles_missing_tushare_package(self):
        import tradingagents.dataflows.tushare_utils as tushare_utils

        original_import = __import__
        sys.modules.pop("tushare", None)

        def _raise_nested_missing(name, *args, **kwargs):
            if name == "tushare":
                raise ModuleNotFoundError("No module named 'tushare.extra'", name="tushare.extra")
            return original_import(name, *args, **kwargs)

        with mock.patch("builtins.__import__", side_effect=_raise_nested_missing), \
                self.assertRaises(ModuleNotFoundError) as ctx:
            importlib.reload(tushare_utils)

        self.assertEqual(ctx.exception.name, "tushare.extra")
        importlib.reload(tushare_utils)


@pytest.mark.unit
class RouterHandlesBaseTypesTests(unittest.TestCase):
    def setUp(self):
        config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)

    def tearDown(self):
        config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)

    def test_rate_limit_subclass_caught_by_base(self):
        # A vendor-named rate-limit error skips to the next vendor in the chain.
        set_config({"data_vendors": {"core_stock_apis": "alpha_vantage,yfinance"}})

        def _throttled(*a, **k):
            raise AlphaVantageRateLimitError("slow down")

        with mock.patch.dict(
            interface.VENDOR_METHODS,
            {"get_stock_data": {"alpha_vantage": _throttled, "yfinance": lambda *a, **k: "YF"}},
            clear=False,
        ):
            out = interface.route_to_vendor("get_stock_data", "AAPL", "2026-01-01", "2026-01-10")
        self.assertEqual(out, "YF")

    def test_not_configured_falls_through_to_next_vendor(self):
        set_config({"data_vendors": {"core_stock_apis": "alpha_vantage,yfinance"}})

        def _unconfigured(*a, **k):
            raise AlphaVantageNotConfiguredError("no key")

        with mock.patch.dict(
            interface.VENDOR_METHODS,
            {"get_stock_data": {"alpha_vantage": _unconfigured, "yfinance": lambda *a, **k: "YF"}},
            clear=False,
        ):
            out = interface.route_to_vendor("get_stock_data", "AAPL", "2026-01-01", "2026-01-10")
        self.assertEqual(out, "YF")

    def test_sole_unconfigured_vendor_surfaces_the_error(self):
        # With no fallback, the not-configured condition must surface (not vanish).
        set_config({"data_vendors": {"core_stock_apis": "alpha_vantage"}})

        def _unconfigured(*a, **k):
            raise AlphaVantageNotConfiguredError("no key")

        with mock.patch.dict(
            interface.VENDOR_METHODS,
            {"get_stock_data": {"alpha_vantage": _unconfigured}},
            clear=False,
        ), self.assertRaises(AlphaVantageNotConfiguredError):
            interface.route_to_vendor("get_stock_data", "AAPL", "2026-01-01", "2026-01-10")

    def test_sole_vendor_network_error_returns_unavailable_sentinel(self):
        # A transient connectivity failure from the only vendor (e.g. East Money
        # refusing the connection) must NOT crash the run: it degrades to an
        # explicit UNAVAILABLE sentinel so the agent reports the source as down.
        set_config({"data_vendors": {"core_stock_apis": "alpha_vantage"}})

        def _disconnected(*a, **k):
            raise requests.exceptions.ConnectionError(
                "('Connection aborted.', RemoteDisconnected('Remote end closed "
                "connection without response'))"
            )

        with mock.patch.dict(
            interface.VENDOR_METHODS,
            {"get_stock_data": {"alpha_vantage": _disconnected}},
            clear=False,
        ):
            out = interface.route_to_vendor("get_stock_data", "AAPL", "2026-01-01", "2026-01-10")
        self.assertIn("DATA_SOURCE_UNAVAILABLE", out)

    def test_sole_vendor_non_network_error_still_raises(self):
        # The network-sentinel path must NOT swallow genuine bugs: a non-network
        # exception from the sole vendor still surfaces loudly.
        set_config({"data_vendors": {"core_stock_apis": "alpha_vantage"}})

        def _bug(*a, **k):
            raise ValueError("unexpected parse failure")

        with mock.patch.dict(
            interface.VENDOR_METHODS,
            {"get_stock_data": {"alpha_vantage": _bug}},
            clear=False,
        ), self.assertRaises(ValueError):
            interface.route_to_vendor("get_stock_data", "AAPL", "2026-01-01", "2026-01-10")


@pytest.mark.unit
class AkShareRetryCircuitTests(unittest.TestCase):
    def tearDown(self):
        akshare_utils.reset_akshare_network_circuit()

    def test_network_failure_opens_short_circuit_for_repeated_calls(self):
        calls = 0

        def _disconnected():
            nonlocal calls
            calls += 1
            raise requests.exceptions.ConnectionError("Remote end closed connection")

        with mock.patch("tradingagents.dataflows.akshare_utils.time.sleep"), \
                self.assertRaises(requests.exceptions.ConnectionError):
            akshare_utils.ak_retry(_disconnected, max_retries=1, circuit_key="stock_zh_a_hist")

        self.assertEqual(calls, 2)

        with self.assertRaises(requests.exceptions.ConnectionError) as ctx:
            akshare_utils.ak_retry(_disconnected, max_retries=1, circuit_key="stock_zh_a_hist")

        self.assertEqual(calls, 2)
        self.assertIn("temporarily unavailable", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
