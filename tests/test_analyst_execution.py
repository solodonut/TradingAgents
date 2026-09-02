import unittest

from tradingagents.agents.utils.agent_states import AgentState
from tradingagents.graph.analyst_execution import (
    ANALYST_NODE_SPECS,
    AnalystWallTimeTracker,
    build_analyst_execution_plan,
    get_initial_analyst_node,
    iter_state_messages,
    sync_analyst_tracker_from_chunk,
)


class AnalystExecutionPlanTests(unittest.TestCase):
    def test_build_plan_preserves_selected_order(self):
        plan = build_analyst_execution_plan(["news", "market"], concurrency_limit=2)

        self.assertEqual([spec.key for spec in plan.specs], ["news", "market"])
        self.assertEqual(plan.concurrency_limit, 2)
        self.assertEqual(plan.specs[0].agent_node, "News Analyst")
        self.assertEqual(plan.specs[0].tool_node, "tools_news")
        self.assertEqual(plan.specs[0].clear_node, "Msg Clear News")

    def test_each_analyst_gets_its_own_message_channel(self):
        # Concurrent analysts must not share a ReAct scratchpad, so every spec
        # names a distinct channel (and AgentState must declare each one).
        keys = [spec.messages_key for spec in ANALYST_NODE_SPECS.values()]
        self.assertEqual(len(keys), len(set(keys)))
        for key in keys:
            self.assertIn(key, AgentState.__annotations__)

    def test_waves_batch_specs_by_concurrency_limit(self):
        selected = ["market", "social", "news", "fundamentals"]

        serial = build_analyst_execution_plan(selected, concurrency_limit=1)
        self.assertEqual(
            [[spec.key for spec in wave] for wave in serial.waves],
            [["market"], ["social"], ["news"], ["fundamentals"]],
        )

        paired = build_analyst_execution_plan(selected, concurrency_limit=2)
        self.assertEqual(
            [[spec.key for spec in wave] for wave in paired.waves],
            [["market", "social"], ["news", "fundamentals"]],
        )

        wide = build_analyst_execution_plan(selected, concurrency_limit=4)
        self.assertEqual(
            [[spec.key for spec in wave] for wave in wide.waves],
            [["market", "social", "news", "fundamentals"]],
        )

    def test_concurrency_limit_above_analyst_count_yields_one_wave(self):
        plan = build_analyst_execution_plan(["market", "news"], concurrency_limit=99)

        self.assertEqual([[spec.key for spec in wave] for wave in plan.waves], [["market", "news"]])

    def test_rejects_unknown_analyst_keys(self):
        with self.assertRaises(ValueError):
            build_analyst_execution_plan(["market", "macro"])

    def test_requires_positive_concurrency_limit(self):
        with self.assertRaises(ValueError):
            build_analyst_execution_plan(["market"], concurrency_limit=0)

    def test_get_initial_analyst_node_uses_plan_metadata(self):
        plan = build_analyst_execution_plan(["fundamentals", "news"])

        self.assertEqual(
            get_initial_analyst_node(plan),
            "Fundamentals Analyst",
        )

    def test_social_key_displays_as_sentiment_analyst(self):
        # The wire key stays "social" for saved-config back-compat, but the
        # user-visible agent_node label must match the v0.2.5 rename so the
        # wall-time summary and any future consumer of agent_node says
        # "Sentiment Analyst" rather than the legacy "Social Analyst".
        plan = build_analyst_execution_plan(["social"])
        spec = plan.specs[0]
        self.assertEqual(spec.key, "social")
        self.assertEqual(spec.agent_node, "Sentiment Analyst")
        self.assertEqual(spec.report_key, "sentiment_report")


class AnalystWallTimeTrackerTests(unittest.TestCase):
    def test_records_wall_time_when_analyst_completes(self):
        plan = build_analyst_execution_plan(["market", "news"])
        tracker = AnalystWallTimeTracker(plan)

        tracker.mark_started("market", started_at=10.0)
        tracker.mark_completed("market", completed_at=13.5)

        self.assertEqual(tracker.get_wall_times(), {"market": 3.5})

    def test_formats_summary_in_plan_order(self):
        plan = build_analyst_execution_plan(["news", "market"])
        tracker = AnalystWallTimeTracker(plan)

        tracker.mark_started("market", started_at=20.0)
        tracker.mark_completed("market", completed_at=22.25)
        tracker.mark_started("news", started_at=10.0)
        tracker.mark_completed("news", completed_at=14.0)

        self.assertEqual(
            tracker.format_summary(),
            "Analyst wall time: News 4.00s | Market 2.25s",
        )

    def test_syncs_wall_time_from_sequential_chunks(self):
        plan = build_analyst_execution_plan(["market", "news"])
        tracker = AnalystWallTimeTracker(plan)

        sync_analyst_tracker_from_chunk(tracker, {}, now=10.0)
        self.assertEqual(tracker.get_wall_times(), {})

        sync_analyst_tracker_from_chunk(
            tracker,
            {"market_report": "done"},
            now=13.0,
        )
        self.assertEqual(tracker.get_wall_times(), {"market": 3.0})

        sync_analyst_tracker_from_chunk(
            tracker,
            {"market_report": "done", "news_report": "done"},
            now=18.0,
        )
        self.assertEqual(
            tracker.get_wall_times(),
            {"market": 3.0, "news": 5.0},
        )

    def test_starts_every_analyst_in_the_active_wave_at_once(self):
        # With a parallel wave there is no single "current" analyst: all of them
        # are already running, so all of them must be clocked from the same tick.
        plan = build_analyst_execution_plan(
            ["market", "social", "news", "fundamentals"],
            concurrency_limit=4,
        )
        tracker = AnalystWallTimeTracker(plan)

        sync_analyst_tracker_from_chunk(tracker, {}, now=100.0)
        # Only the fast one has landed; the other three keep their 100.0 start.
        sync_analyst_tracker_from_chunk(tracker, {"news_report": "done"}, now=104.0)
        sync_analyst_tracker_from_chunk(
            tracker,
            {
                "news_report": "done",
                "market_report": "done",
                "sentiment_report": "done",
                "fundamentals_report": "done",
            },
            now=109.0,
        )

        self.assertEqual(
            tracker.get_wall_times(),
            {"news": 4.0, "market": 9.0, "social": 9.0, "fundamentals": 9.0},
        )

    def test_later_waves_do_not_start_until_the_active_one_finishes(self):
        plan = build_analyst_execution_plan(
            ["market", "social", "news", "fundamentals"],
            concurrency_limit=2,
        )
        tracker = AnalystWallTimeTracker(plan)

        sync_analyst_tracker_from_chunk(tracker, {}, now=10.0)
        sync_analyst_tracker_from_chunk(
            tracker,
            {"market_report": "done", "sentiment_report": "done"},
            now=15.0,
        )
        sync_analyst_tracker_from_chunk(
            tracker,
            {
                "market_report": "done",
                "sentiment_report": "done",
                "news_report": "done",
                "fundamentals_report": "done",
            },
            now=18.0,
        )

        # Wave 2 was only clocked from 15.0, when wave 1 completed.
        self.assertEqual(
            tracker.get_wall_times(),
            {"market": 5.0, "social": 5.0, "news": 3.0, "fundamentals": 3.0},
        )


class IterStateMessagesTests(unittest.TestCase):
    def test_yields_shared_channel_then_every_analyst_channel(self):
        state = {
            "messages": ["shared"],
            "market_messages": ["m"],
            "social_messages": ["s"],
            "news_messages": ["n"],
            "fundamentals_messages": ["f"],
            "market_report": "not a message list",
        }

        self.assertEqual(
            list(iter_state_messages(state)),
            ["shared", "m", "s", "n", "f"],
        )

    def test_tolerates_missing_and_non_list_channels(self):
        self.assertEqual(list(iter_state_messages({})), [])
        self.assertEqual(list(iter_state_messages({"messages": None})), [])
