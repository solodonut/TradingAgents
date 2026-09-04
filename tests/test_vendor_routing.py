"""Vendor router must respect the configured chain and never silently hide a
broken primary.

Regressions for #988 (explicit single-vendor config still fell back to others),
#289 (fallback ran for unchosen vendors), and #989 (serious primary failures
were swallowed without a trace).
"""
import copy
import unittest
from unittest import mock

import pytest

import tradingagents.dataflows.config as config_module
import tradingagents.default_config as default_config
from tradingagents.dataflows import interface
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.errors import VendorNotConfiguredError
from tradingagents.dataflows.symbol_utils import NoMarketDataError
from tradingagents.dataflows.tushare_stock import get_stock_data as get_tushare_stock


def _reset_config():
    # Hard reset: set_config() merges, so empty DEFAULT dicts (e.g. tool_vendors)
    # don't clear keys leaked by other tests. Replace the global outright.
    config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)


def _no_data(symbol, *a, **k):
    raise NoMarketDataError(symbol, symbol, "no rows")


def _returns(value):
    def impl(symbol, *a, **k):
        return value
    return impl


def _raises(exc):
    def impl(symbol, *a, **k):
        raise exc
    return impl


@pytest.mark.unit
class VendorRoutingTests(unittest.TestCase):
    def setUp(self):
        _reset_config()

    def tearDown(self):
        _reset_config()

    def _route(self, vendors_for_get_stock_data):
        return mock.patch.dict(
            interface.VENDOR_METHODS,
            {"get_stock_data": vendors_for_get_stock_data},
            clear=False,
        )

    def test_explicit_single_vendor_does_not_fall_back(self):
        # #988: with yfinance pinned, a healthy alpha_vantage must NOT be used.
        set_config({"data_vendors": {"core_stock_apis": "yfinance"}})
        av = mock.Mock(side_effect=_returns("AV_DATA"))
        with self._route({"yfinance": _no_data, "alpha_vantage": av}):
            result = interface.route_to_vendor("get_stock_data", "FAKE", "2026-01-01", "2026-01-10")
        self.assertIn("NO_DATA_AVAILABLE", result)
        av.assert_not_called()  # the unchosen vendor was never tried

    def test_explicit_multi_vendor_falls_back_within_chain(self):
        # Listing both vendors opts in to ordered fallback.
        set_config({"data_vendors": {"core_stock_apis": "yfinance,alpha_vantage"}})
        with self._route({"yfinance": _no_data, "alpha_vantage": _returns("AV_DATA")}):
            result = interface.route_to_vendor("get_stock_data", "AAPL", "2026-01-01", "2026-01-10")
        self.assertEqual(result, "AV_DATA")

    def test_primary_error_is_logged_not_masked(self):
        # #989: primary errors + fallback no-data -> NO_DATA, but the failure
        # must be visible in logs (broken primary not hidden).
        set_config({"data_vendors": {"core_stock_apis": "yfinance,alpha_vantage"}})
        with self._route({"yfinance": _raises(ValueError("boom")), "alpha_vantage": _no_data}), \
                self.assertLogs("tradingagents.dataflows.interface", level="WARNING") as cm:
            result = interface.route_to_vendor("get_stock_data", "AAPL", "2026-01-01", "2026-01-10")
        self.assertIn("NO_DATA_AVAILABLE", result)
        joined = "\n".join(cm.output)
        self.assertIn("boom", joined)            # the real error surfaced in logs
        self.assertIn("yfinance", joined)

    def test_unknown_configured_vendor_raises(self):
        set_config({"data_vendors": {"core_stock_apis": "bogus_vendor"}})
        with self.assertRaises(ValueError) as ctx:
            interface.route_to_vendor("get_stock_data", "AAPL", "2026-01-01", "2026-01-10")
        self.assertIn("bogus_vendor", str(ctx.exception))

    def test_disabled_vendor_returns_explicit_sentinel_without_calling_provider(self):
        set_config({"data_vendors": {"macro_data": "disabled"}})
        fred = mock.Mock(return_value="FRED_DATA")
        with mock.patch.dict(
            interface.VENDOR_METHODS,
            {"get_macro_indicators": {"fred": fred}},
            clear=False,
        ):
            result = interface.route_to_vendor("get_macro_indicators", "cpi", "2026-06-01", 30)
        self.assertIn("DATA_SOURCE_DISABLED", result)
        self.assertIn("get_macro_indicators", result)
        fred.assert_not_called()

    def test_default_sentinel_uses_all_vendors(self):
        # No explicit choice ("default") keeps the resilient full-chain behavior.
        set_config({"data_vendors": {"core_stock_apis": "default"}})
        with self._route({"yfinance": _no_data, "alpha_vantage": _returns("AV_DATA")}):
            result = interface.route_to_vendor("get_stock_data", "AAPL", "2026-01-01", "2026-01-10")
        self.assertEqual(result, "AV_DATA")

    def test_akshare_is_fully_unregistered(self):
        # AKShare is globally disabled: it must not be selectable by any config,
        # and no method may keep an AKShare implementation to fall back onto.
        self.assertNotIn("akshare", interface.VENDOR_LIST)
        for method, vendors in interface.VENDOR_METHODS.items():
            self.assertNotIn("akshare", vendors, msg=f"{method} still registers akshare")

    def test_a_share_symbol_does_not_reorder_the_configured_chain(self):
        # AKShare used to be prepended for mainland tickers regardless of config.
        # No per-market reordering survives: the chain is exactly what was set.
        set_config({"data_vendors": {"core_stock_apis": "amazingdata,tushare"}})
        calls = []

        def amazingdata(symbol, *a, **k):
            calls.append("amazingdata")
            return "AD_DATA"

        def tushare(symbol, *a, **k):
            calls.append("tushare")
            return "TS_DATA"

        with self._route({"amazingdata": amazingdata, "tushare": tushare}):
            result = interface.route_to_vendor(
                "get_stock_data",
                "159241",
                "2026-06-01",
                "2026-06-20",
            )

        self.assertEqual(result, "AD_DATA")
        self.assertEqual(calls, ["amazingdata"])

    def test_production_tushare_price_not_configured_falls_back_to_next_vendor(self):
        set_config({"data_vendors": {"core_stock_apis": "tushare,amazingdata"}})

        with mock.patch.dict(
            interface.VENDOR_METHODS["get_stock_data"],
            {"amazingdata": _returns("AD_DATA")},
            clear=False,
        ), mock.patch(
            "tradingagents.dataflows.tushare_stock.get_tushare_client",
            side_effect=VendorNotConfiguredError("TUSHARE_TOKEN is not configured."),
        ), self.assertLogs("tradingagents.dataflows.interface", level="WARNING") as cm:
            result = interface.route_to_vendor(
                "get_stock_data",
                "159241",
                "2026-06-01",
                "2026-06-20",
            )

        self.assertEqual(result, "AD_DATA")
        joined = "\n".join(cm.output)
        self.assertIn("tushare", joined)
        self.assertIn("not configured", joined)

    def test_get_etf_profile_routes_to_tushare(self):
        tushare = mock.Mock(side_effect=_returns("ETF_PROFILE"))
        with mock.patch.dict(
            interface.VENDOR_METHODS,
            {"get_etf_profile": {"tushare": tushare}},
            clear=False,
        ):
            result = interface.route_to_vendor("get_etf_profile", "510300", "2026-06-01")
        self.assertEqual(result, "ETF_PROFILE")
        tushare.assert_called_once()

    def test_default_tool_vendors_use_resilient_etf_and_news_chains(self):
        config = interface.get_config()
        self.assertEqual(config["tool_vendors"]["get_etf_profile"], "tushare,longbridge")
        self.assertEqual(config["tool_vendors"]["get_news"], "eastmoney,tushare")

    def test_production_get_etf_profile_falls_back_from_tushare_to_longbridge(self):
        calls = []

        def tushare(symbol, *a, **k):
            calls.append("tushare")
            raise NoMarketDataError(symbol, symbol, "tushare down")

        def longbridge(symbol, *a, **k):
            calls.append("longbridge")
            return "LONGBRIDGE_ETF_PROFILE"

        with mock.patch.dict(
            interface.VENDOR_METHODS,
            {"get_etf_profile": {"tushare": tushare, "longbridge": longbridge}},
            clear=False,
        ):
            result = interface.route_to_vendor("get_etf_profile", "159241", "2026-07-03")

        self.assertEqual(result, "LONGBRIDGE_ETF_PROFILE")
        self.assertEqual(calls, ["tushare", "longbridge"])

    def test_production_get_news_uses_eastmoney_before_tushare(self):
        calls = []

        def tushare(symbol, *a, **k):
            calls.append("tushare")
            return "TUSHARE_NEWS"

        def eastmoney(symbol, *a, **k):
            calls.append("eastmoney")
            return "EM_NEWS"

        with mock.patch.dict(
            interface.VENDOR_METHODS,
            {"get_news": {"tushare": tushare, "eastmoney": eastmoney}},
            clear=False,
        ):
            result = interface.route_to_vendor("get_news", "159241", "2026-06-26", "2026-07-03")

        self.assertEqual(result, "EM_NEWS")
        self.assertEqual(calls, ["eastmoney"])

    def test_news_error_string_allows_fallback(self):
        set_config({"tool_vendors": {"get_news": "eastmoney,longbridge"}})

        with mock.patch.dict(
            interface.VENDOR_METHODS,
            {
                "get_news": {
                    "eastmoney": _returns("Error fetching news for 159241.SZ: down"),
                    "longbridge": _returns("LONG_BRIDGE_NEWS"),
                }
            },
            clear=False,
        ):
            result = interface.route_to_vendor("get_news", "159241", "2026-06-26", "2026-07-03")

        self.assertEqual(result, "LONG_BRIDGE_NEWS")

    def test_production_vendor_methods_include_tushare_defaults(self):
        methods = [
            "get_stock_data",
            "get_indicators",
            "get_fundamentals",
            "get_balance_sheet",
            "get_cashflow",
            "get_income_statement",
        ]

        for method in methods:
            with self.subTest(method=method):
                self.assertIn("tushare", interface.VENDOR_METHODS[method])
        self.assertIs(interface.VENDOR_METHODS["get_stock_data"]["tushare"], get_tushare_stock)
        self.assertIn("tushare", interface.VENDOR_METHODS["get_etf_profile"])
        self.assertIn("tdx", interface.VENDOR_METHODS["get_etf_profile"])
        self.assertIn("longbridge", interface.VENDOR_METHODS["get_etf_profile"])
        self.assertIn("longbridge", interface.VENDOR_METHODS["get_news"])


if __name__ == "__main__":
    unittest.main()
