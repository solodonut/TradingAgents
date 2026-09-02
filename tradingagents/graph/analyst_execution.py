from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from time import monotonic
from typing import Any


@dataclass(frozen=True)
class AnalystNodeSpec:
    key: str
    agent_node: str
    clear_node: str
    tool_node: str
    report_key: str
    messages_key: str


@dataclass(frozen=True)
class AnalystExecutionPlan:
    specs: list[AnalystNodeSpec]
    concurrency_limit: int
    # ``specs`` split into batches of at most ``concurrency_limit`` analysts.
    # Each wave runs as one LangGraph super-step; waves run back to back.
    waves: list[list[AnalystNodeSpec]]


ANALYST_NODE_SPECS: dict[str, AnalystNodeSpec] = {
    "market": AnalystNodeSpec(
        key="market",
        agent_node="Market Analyst",
        clear_node="Msg Clear Market",
        tool_node="tools_market",
        report_key="market_report",
        messages_key="market_messages",
    ),
    "social": AnalystNodeSpec(
        # Wire key stays "social" for saved-config back-compat; the
        # user-facing label is "Sentiment Analyst" to match the rename
        # that landed in v0.2.5 (sentiment_analyst now ingests news +
        # StockTwits + Reddit, not just social media).
        key="social",
        agent_node="Sentiment Analyst",
        clear_node="Msg Clear Sentiment",
        tool_node="tools_social",
        report_key="sentiment_report",
        messages_key="social_messages",
    ),
    "news": AnalystNodeSpec(
        key="news",
        agent_node="News Analyst",
        clear_node="Msg Clear News",
        tool_node="tools_news",
        report_key="news_report",
        messages_key="news_messages",
    ),
    "fundamentals": AnalystNodeSpec(
        key="fundamentals",
        agent_node="Fundamentals Analyst",
        clear_node="Msg Clear Fundamentals",
        tool_node="tools_fundamentals",
        report_key="fundamentals_report",
        messages_key="fundamentals_messages",
    ),
}

ANALYST_MESSAGE_KEYS: tuple[str, ...] = tuple(
    spec.messages_key for spec in ANALYST_NODE_SPECS.values()
)


def iter_state_messages(state: Mapping[str, Any]) -> Iterator[Any]:
    """Yield messages from the shared channel plus every analyst's private one.

    Consumers that used to scan ``state["messages"]`` for analyst tool calls
    must look at the private channels too, otherwise the analyst phase looks
    silent (see ``AgentState`` for why the channels are separate).
    """
    for key in ("messages", *ANALYST_MESSAGE_KEYS):
        messages = state.get(key)
        if isinstance(messages, list):
            yield from messages


def build_analyst_execution_plan(
    selected_analysts: Iterable[str],
    concurrency_limit: int = 1,
) -> AnalystExecutionPlan:
    if concurrency_limit < 1:
        raise ValueError("analyst concurrency limit must be >= 1")

    specs: list[AnalystNodeSpec] = []
    for analyst_key in selected_analysts:
        spec = ANALYST_NODE_SPECS.get(analyst_key)
        if spec is None:
            raise ValueError(f"unknown analyst key: {analyst_key}")
        specs.append(spec)

    if not specs:
        raise ValueError("at least one analyst must be selected")

    waves = [
        specs[start : start + concurrency_limit]
        for start in range(0, len(specs), concurrency_limit)
    ]
    return AnalystExecutionPlan(
        specs=specs,
        concurrency_limit=concurrency_limit,
        waves=waves,
    )


def get_initial_analyst_node(plan: AnalystExecutionPlan) -> str:
    return plan.specs[0].agent_node


class AnalystWallTimeTracker:
    def __init__(self, plan: AnalystExecutionPlan):
        self.plan = plan
        self._started_at: dict[str, float] = {}
        self._wall_times: dict[str, float] = {}

    def mark_started(self, analyst_key: str, started_at: float | None = None) -> None:
        if analyst_key not in ANALYST_NODE_SPECS:
            raise ValueError(f"unknown analyst key: {analyst_key}")
        self._started_at.setdefault(analyst_key, monotonic() if started_at is None else started_at)

    def mark_completed(
        self,
        analyst_key: str,
        completed_at: float | None = None,
    ) -> None:
        if analyst_key not in ANALYST_NODE_SPECS:
            raise ValueError(f"unknown analyst key: {analyst_key}")
        if analyst_key in self._wall_times:
            return
        started_at = self._started_at.get(analyst_key)
        if started_at is None:
            return
        finished_at = monotonic() if completed_at is None else completed_at
        self._wall_times[analyst_key] = max(0.0, finished_at - started_at)

    def get_wall_times(self) -> dict[str, float]:
        return dict(self._wall_times)

    def format_summary(self) -> str:
        parts = []
        for spec in self.plan.specs:
            duration = self._wall_times.get(spec.key)
            if duration is not None:
                label = spec.agent_node.removesuffix(" Analyst")
                parts.append(f"{label} {duration:.2f}s")
        if not parts:
            return "Analyst wall time: pending"
        return "Analyst wall time: " + " | ".join(parts)


def sync_analyst_tracker_from_chunk(
    tracker: AnalystWallTimeTracker,
    chunk: dict[str, str],
    now: float | None = None,
) -> None:
    current_time = monotonic() if now is None else now
    active_wave_found = False

    for wave in tracker.plan.waves:
        pending: list[AnalystNodeSpec] = []
        for spec in wave:
            if chunk.get(spec.report_key):
                tracker.mark_started(spec.key, started_at=current_time)
                tracker.mark_completed(spec.key, completed_at=current_time)
            else:
                pending.append(spec)

        # Every analyst still pending in the earliest unfinished wave is running
        # concurrently, so they all start now — not just the first one.
        if pending and not active_wave_found:
            for spec in pending:
                tracker.mark_started(spec.key, started_at=current_time)
            active_wave_found = True
