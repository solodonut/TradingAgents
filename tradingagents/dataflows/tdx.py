"""Optional TDX adapter placeholder for vendor routing.

TDX access in this workspace is exposed through an MCP server, not through a
runtime Python dependency available to TradingAgents. Registering this adapter
lets production configs express a ``tdx`` fallback without crashing: unless a
future runtime implementation is added, the router skips it cleanly.
"""

from __future__ import annotations

from .errors import VendorNotConfiguredError


def get_etf_profile(symbol: str, curr_date: str | None = None) -> str:
    raise VendorNotConfiguredError(
        "TDX runtime adapter is not configured; available in this workspace via MCP only."
    )
