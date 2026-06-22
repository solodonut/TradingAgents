"""Session-profile tools: fact confirmation + enforced position sizing."""

from __future__ import annotations

import json
import math
from collections.abc import Callable

from langchain_core.tools import BaseTool, tool

_RISK_VALUES = {"conservative", "balanced", "aggressive"}
_HORIZON_VALUES = {"short", "medium", "long"}
_CONFIRM_INSTRUCTION = (
    "已向用户弹出确认卡片，在用户确认前这些值未生效，不得据此计算。"
)


def create_profile_tools(*, load_profile: Callable[[], dict]) -> list[BaseTool]:
    """Build the profile tools. `load_profile` returns the confirmed profile dict."""

    @tool
    def propose_session_facts(
        available_capital: float | None = None,
        capital_currency: str | None = None,
        risk_tolerance: str | None = None,
        max_single_position_pct: float | None = None,
        horizon: str | None = None,
        constraints: str | None = None,
    ) -> str:
        """Propose key session facts for the user to confirm; does not take effect yet."""

        proposal: dict = {}
        if available_capital is not None:
            if available_capital < 0:
                raise ValueError("available_capital must be non-negative")
            proposal["available_capital"] = available_capital
        if capital_currency is not None:
            currency = capital_currency.strip()
            if not currency:
                raise ValueError("capital_currency must be nonblank")
            proposal["capital_currency"] = currency
        if risk_tolerance is not None:
            if risk_tolerance not in _RISK_VALUES:
                raise ValueError(f"risk_tolerance must be one of {_RISK_VALUES}")
            proposal["risk_tolerance"] = risk_tolerance
        if max_single_position_pct is not None:
            if not 0 < max_single_position_pct <= 100:
                raise ValueError("max_single_position_pct must be in (0, 100]")
            proposal["max_single_position_pct"] = max_single_position_pct
        if horizon is not None:
            if horizon not in _HORIZON_VALUES:
                raise ValueError(f"horizon must be one of {_HORIZON_VALUES}")
            proposal["horizon"] = horizon
        if constraints is not None:
            proposal["constraints"] = constraints

        if not proposal:
            raise ValueError("propose_session_facts requires at least one field")

        return json.dumps(
            {"proposal": proposal, "instruction": _CONFIRM_INSTRUCTION},
            ensure_ascii=False,
        )

    @tool
    def compute_position_sizing(
        ticker: str,
        price: float,
        target_weight_pct: float | None = None,
        target_amount: float | None = None,
    ) -> str:
        """Compute position size from the confirmed available capital. Required for any sizing."""

        if (target_weight_pct is None) == (target_amount is None):
            raise ValueError(
                "provide exactly one of target_weight_pct or target_amount"
            )
        if price <= 0:
            raise ValueError("price must be positive")

        profile = load_profile() or {}
        available_capital = profile.get("available_capital")
        if available_capital is None:
            return "NEED_CONFIRMATION: 缺少可用资金池，请先在参数面板确认"

        currency = profile.get("capital_currency") or "CNY"
        max_pct = profile.get("max_single_position_pct")

        if target_weight_pct is not None:
            weight = float(target_weight_pct)
            amount = available_capital * weight / 100
        else:
            amount = float(target_amount)
            weight = amount / available_capital * 100 if available_capital else 0.0

        shares = math.floor(amount / price)
        exceeds_max = max_pct is not None and weight > max_pct + 1e-9

        return json.dumps(
            {
                "ticker": ticker,
                "available_capital": available_capital,
                "capital_currency": currency,
                "target_weight_pct": round(weight, 2),
                "amount": round(amount, 2),
                "price": price,
                "shares": shares,
                "max_single_position_pct": max_pct,
                "exceeds_max": exceeds_max,
            },
            ensure_ascii=False,
        )

    return [propose_session_facts, compute_position_sizing]
