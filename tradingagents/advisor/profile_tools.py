"""Session-profile tools: fact confirmation + enforced position sizing."""

from __future__ import annotations

import json
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

    return [propose_session_facts]
