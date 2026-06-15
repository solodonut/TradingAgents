from api.runner import REPORT_SECTIONS, chunk_to_events


def test_report_section_chunk_emits_report_event():
    events = chunk_to_events({"market_report": "## Market\nUp"}, set())
    types = [e["event"] for e in events]
    assert "report_section" in types
    report = next(e for e in events if e["event"] == "report_section")
    assert report["data"]["section"] == "market_report"
    assert report["data"]["content"] == "## Market\nUp"


def test_report_section_also_emits_agent_done():
    events = chunk_to_events({"market_report": "x"}, set())
    statuses = [e for e in events if e["event"] == "agent_status"]
    assert any(
        e["data"]["agent"] == "market_analyst" and e["data"]["status"] == "done"
        for e in statuses
    )


def test_empty_report_field_is_ignored():
    events = chunk_to_events({"market_report": ""}, set())
    assert events == []


def test_already_seen_section_not_re_emitted():
    seen = {"market_report"}
    events = chunk_to_events({"market_report": "x"}, seen)
    assert events == []


def test_all_known_sections_have_agent_mapping():
    for section in REPORT_SECTIONS:
        assert section in REPORT_SECTIONS
        agent, team = REPORT_SECTIONS[section]
        assert isinstance(agent, str) and isinstance(team, str)
