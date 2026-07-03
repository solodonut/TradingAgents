"""Optional Longbridge CLI adapters for vendor routing.

The project does not depend on the Longbridge Python SDK. When the ``longbridge``
CLI is installed and authenticated, these adapters return its output; otherwise
they raise ``VendorNotConfiguredError`` so the router can continue to the next
configured vendor.
"""

from __future__ import annotations

import shutil
import subprocess
from datetime import datetime

from .errors import NoMarketDataError, VendorNotConfiguredError
from .tushare_utils import display_symbol, is_fund_symbol, is_mainland_symbol, to_ts_code


def _symbol_for_longbridge(symbol: str) -> str:
    if is_mainland_symbol(symbol):
        return to_ts_code(symbol)
    return symbol


def _run_longbridge(args: list[str]) -> str:
    if shutil.which("longbridge") is None:
        raise VendorNotConfiguredError("longbridge CLI is not installed or not on PATH.")
    try:
        completed = subprocess.run(
            ["longbridge", *args],
            check=False,
            text=True,
            capture_output=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        raise VendorNotConfiguredError("longbridge CLI timed out.") from exc

    output = (completed.stdout or "").strip()
    error = (completed.stderr or "").strip()
    if completed.returncode != 0:
        raise VendorNotConfiguredError(error or f"longbridge exited {completed.returncode}")
    if not output:
        raise NoMarketDataError(args[-1] if args else "longbridge", detail="empty Longbridge output")
    return output


def get_news(ticker: str, start_date: str, end_date: str) -> str:
    symbol = _symbol_for_longbridge(ticker)
    output = _run_longbridge(["news", symbol, "--format", "json"])
    header = f"## {display_symbol(ticker)} News (Longbridge), latest articles"
    header += f"\n# Requested window: {start_date} to {end_date}"
    header += f"\n# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    return header + output


def get_etf_profile(symbol: str, curr_date: str | None = None) -> str:
    if not is_fund_symbol(symbol):
        raise NoMarketDataError(symbol, symbol, "not a mainland China listed ETF/fund")
    lb_symbol = _symbol_for_longbridge(symbol)
    parts = []
    for title, args in (
        ("Static Info", ["static", lb_symbol, "--format", "json"]),
        ("Quote", ["quote", lb_symbol, "--format", "json"]),
    ):
        try:
            parts.append(f"## {title}\n\n{_run_longbridge(args)}")
        except Exception:
            continue
    if not parts:
        raise NoMarketDataError(symbol, lb_symbol, "no Longbridge ETF profile data")
    header = f"# ETF Profile for {display_symbol(symbol)} (Longbridge)\n"
    header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    return header + "\n\n".join(parts)
