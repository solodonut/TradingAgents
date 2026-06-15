"""Bridges TradingAgentsGraph.stream() to SSE events via a background thread."""

import time

# section field name -> (agent name, team)
REPORT_SECTIONS: dict[str, tuple[str, str]] = {
    "market_report": ("market_analyst", "analyst"),
    "sentiment_report": ("social_analyst", "analyst"),
    "news_report": ("news_analyst", "analyst"),
    "fundamentals_report": ("fundamentals_analyst", "analyst"),
    "investment_plan": ("research_manager", "research"),
    "trader_investment_plan": ("trader", "trading"),
    "final_trade_decision": ("portfolio_manager", "portfolio"),
}


def chunk_to_events(chunk: dict, seen: set[str]) -> list[dict]:
    """Translate one LangGraph stream chunk into SSE event dicts.

    Each event dict has shape {"event": <type>, "data": <payload>}.
    Mutates ``seen`` to track which report sections were already emitted.
    """
    events: list[dict] = []
    for section, (agent, team) in REPORT_SECTIONS.items():
        content = chunk.get(section)
        if not content or section in seen:
            continue
        seen.add(section)
        events.append(
            {"event": "agent_status", "data": {"agent": agent, "team": team, "status": "done"}}
        )
        events.append(
            {
                "event": "report_section",
                "data": {"section": section, "content": content},
            }
        )
        events.append(
            {
                "event": "message",
                "data": {"agent": agent, "team": team, "content": content, "ts": int(time.time())},
            }
        )
    return events
