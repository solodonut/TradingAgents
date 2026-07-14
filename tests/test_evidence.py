import pytest

from tradingagents.graph.evidence import (
    EvidenceRegistry,
    extract_citation_ids,
    extract_cited_evidence_ids,
    render_source_table,
)


@pytest.mark.unit
def test_register_allocates_stable_ids_and_dedupes():
    registry = EvidenceRegistry()

    first = registry.register(
        kind="news",
        source_name="财联社",
        title="半导体板块获政策支持",
        url="https://example.com/news/1",
        published_at="2026-07-01",
        vendor="akshare",
        tool_name="get_news",
        query={"ticker": "600519", "start_date": "2026-06-29", "end_date": "2026-07-06"},
        excerpt="政策支持增强。",
    )
    second = registry.register(
        kind="news",
        source_name="财联社",
        title="半导体板块获政策支持",
        url="https://example.com/news/1",
        published_at="2026-07-01",
        vendor="akshare",
        tool_name="get_news",
        query={"ticker": "600519", "start_date": "2026-06-29", "end_date": "2026-07-06"},
        excerpt="另一段摘要。",
    )
    third = registry.register(
        kind="market_data",
        source_name="AKShare",
        title="get_stock_data: 600519",
        vendor="akshare",
        tool_name="get_stock_data",
        query={"ticker": "600519", "start_date": "2026-06-29", "end_date": "2026-07-06"},
    )

    assert first == "S1"
    assert second == "S1"
    assert third == "S2"
    assert [item["id"] for item in registry.items] == ["S1", "S2"]
    assert registry.items[0]["excerpt"] == "政策支持增强。"


@pytest.mark.unit
def test_register_distinguishes_query_types_and_nested_order():
    registry = EvidenceRegistry()

    first = registry.register(
        kind="market_data",
        source_name="AKShare",
        title="get_stock_data: 600519",
        vendor="akshare",
        tool_name="get_stock_data",
        query={
            "ticker": 1,
            "filters": {"b": 2, "a": 1},
            "window": [{"y": 2, "x": 1}, {"x": 3, "y": 4}],
        },
    )
    second = registry.register(
        kind="market_data",
        source_name="AKShare",
        title="get_stock_data: 600519",
        vendor="akshare",
        tool_name="get_stock_data",
        query={
            "window": [{"x": 1, "y": 2}, {"y": 4, "x": 3}],
            "filters": {"a": 1, "b": 2},
            "ticker": 1,
        },
    )
    third = registry.register(
        kind="market_data",
        source_name="AKShare",
        title="get_stock_data: 600519",
        vendor="akshare",
        tool_name="get_stock_data",
        query={
            "ticker": "1",
            "filters": {"a": 1, "b": 2},
            "window": [{"x": 1, "y": 2}, {"y": 4, "x": 3}],
        },
    )

    assert first == "S1"
    assert second == "S1"
    assert third == "S2"
    assert [item["id"] for item in registry.items] == ["S1", "S2"]


@pytest.mark.unit
def test_constructor_skips_duplicate_seed_rows():
    registry = EvidenceRegistry(
        [
            {
                "id": "S7",
                "kind": "news",
                "source_name": "财联社",
                "title": "半导体板块获政策支持",
                "url": "https://example.com/news/1",
                "published_at": "2026-07-01",
                "vendor": "akshare",
                "tool_name": "get_news",
                "query": {"ticker": "600519"},
                "excerpt": "政策支持增强。",
            },
            {
                "id": "S8",
                "kind": "news",
                "source_name": "财联社",
                "title": "半导体板块获政策支持",
                "url": "https://example.com/news/1",
                "published_at": "2026-07-01",
                "vendor": "akshare",
                "tool_name": "get_news",
                "query": {"ticker": "600519"},
                "excerpt": "重复摘要。",
            },
        ]
    )

    assert [item["id"] for item in registry.items] == ["S7"]
    assert registry.items[0]["excerpt"] == "政策支持增强。"
    assert registry.register(
        kind="news",
        source_name="另一来源",
        title="新增证据",
        url="https://example.com/news/2",
        published_at="2026-07-02",
        vendor="akshare",
        tool_name="get_news",
        query={"ticker": "600519", "page": 2},
    ) == "S9"


@pytest.mark.unit
def test_constructor_keeps_ids_unique_when_missing_and_explicit_mix():
    registry = EvidenceRegistry(
        [
            {
                "kind": "news",
                "source_name": "财联社",
                "title": "半导体板块获政策支持",
                "url": "https://example.com/news/1",
                "published_at": "2026-07-01",
                "vendor": "akshare",
                "tool_name": "get_news",
                "query": {"ticker": "600519"},
                "excerpt": "政策支持增强。",
            },
            {
                "id": "S1",
                "kind": "market_data",
                "source_name": "AKShare",
                "title": "get_stock_data: 600519",
                "vendor": "akshare",
                "tool_name": "get_stock_data",
                "query": {"ticker": "600519"},
            },
        ]
    )

    assert [item["id"] for item in registry.items] == ["S2", "S1"]
    assert list(registry.by_id()) == ["S2", "S1"]


@pytest.mark.unit
def test_by_id_returns_copies():
    registry = EvidenceRegistry(
        [
            {
                "id": "S1",
                "kind": "news",
                "source_name": "财联社",
                "title": "半导体板块获政策支持",
                "url": "https://example.com/news/1",
                "published_at": "2026-07-01",
                "vendor": "akshare",
                "tool_name": "get_news",
                "query": {"ticker": "600519"},
                "excerpt": "政策支持增强。",
            }
        ]
    )

    snapshot = registry.by_id()
    snapshot["S1"]["excerpt"] = "changed"

    assert registry.items[0]["excerpt"] == "政策支持增强。"


@pytest.mark.unit
def test_extract_citation_ids_preserves_first_seen_order():
    text = "事件改善 [S2]，成交放大 [S1]，重复引用 [S2]，非法 [S999]。"

    assert extract_citation_ids(text) == ["S2", "S1", "S999"]


@pytest.mark.unit
def test_render_source_table_uses_only_known_ids_and_links_urls():
    registry = EvidenceRegistry(
        [
            {
                "id": "S1",
                "kind": "news",
                "source_name": "财联社",
                "title": "半导体板块获政策支持",
                "url": "https://example.com/news/1",
                "published_at": "2026-07-01",
                "vendor": "akshare",
                "tool_name": "get_news",
                "query": {"ticker": "600519"},
                "excerpt": "政策支持增强。",
            },
            {
                "id": "S2",
                "kind": "market_data",
                "source_name": "AKShare",
                "title": "get_stock_data: 600519",
                "url": "",
                "published_at": "2026-06-29..2026-07-06",
                "vendor": "akshare",
                "tool_name": "get_stock_data",
                "query": {"ticker": "600519"},
                "excerpt": "",
            },
        ]
    )

    table = render_source_table(registry.items, ["S2", "S404", "S1"], heading="引用来源")

    assert "### 引用来源" in table
    # S2 is get_stock_data -> first column shows its readable display label.
    assert "| [历史行情（OHLCV）] | AKShare | get_stock_data: 600519 | 2026-06-29..2026-07-06 | - |" in table
    # S1 is get_news (no derived label) -> falls back to the [S#] id.
    assert "| [S1] | 财联社 | 半导体板块获政策支持 | 2026-07-01 | [打开](https://example.com/news/1) |" in table
    assert "S404" not in table


def _resolver_items():
    return [
        {"id": "S1", "display_label": "历史行情（OHLCV）", "title": "get_stock_data: 600519"},
        {"id": "S2", "display_label": "RSI", "title": "get_indicators: 600519 rsi"},
    ]


@pytest.mark.unit
def test_extract_cited_evidence_ids_resolves_label_token():
    assert extract_cited_evidence_ids("走强 [历史行情（OHLCV）]。", _resolver_items()) == ["S1"]


@pytest.mark.unit
def test_extract_cited_evidence_ids_resolves_title_token():
    assert extract_cited_evidence_ids("见 [get_indicators: 600519 rsi]。", _resolver_items()) == ["S2"]


@pytest.mark.unit
def test_extract_cited_evidence_ids_resolves_legacy_sharp_id_token():
    # Dual-mode: stored historical reports still cite [S#] directly.
    assert extract_cited_evidence_ids("超买 [S2]。", _resolver_items()) == ["S2"]


@pytest.mark.unit
def test_extract_cited_evidence_ids_ignores_unknown_token():
    assert extract_cited_evidence_ids("参见 [未知标签] 与 [S9]。", _resolver_items()) == []


@pytest.mark.unit
def test_extract_cited_evidence_ids_ignores_markdown_link_label():
    assert extract_cited_evidence_ids("点这里 [详情](https://example.com)。", _resolver_items()) == []


@pytest.mark.unit
def test_extract_cited_evidence_ids_collision_yields_all_ids_in_order():
    items = [
        {"id": "S1", "display_label": "资产负债表", "title": "get_balance_sheet: 600519"},
        {"id": "S2", "display_label": "资产负债表", "title": "get_balance_sheet: 000001"},
    ]

    assert extract_cited_evidence_ids("对比 [资产负债表]。", items) == ["S1", "S2"]


@pytest.mark.unit
def test_extract_cited_evidence_ids_preserves_first_seen_order_and_dedupes():
    assert extract_cited_evidence_ids("[RSI] 然后 [历史行情（OHLCV）] 再 [RSI]。", _resolver_items()) == [
        "S2",
        "S1",
    ]


@pytest.mark.unit
def test_render_source_table_first_column_falls_back_when_label_empty():
    # A registered get_news item derives no display label -> first column keeps [S#].
    registry = EvidenceRegistry()
    registry.register(
        kind="news",
        source_name="财联社",
        title="半导体板块获政策支持",
        url="https://example.com/news/1",
        published_at="2026-07-01",
        vendor="akshare",
        tool_name="get_news",
        query={"ticker": "600519"},
    )

    table = render_source_table(registry.items, ["S1"], heading="引用来源")

    assert "| [S1] | 财联社 | 半导体板块获政策支持 | 2026-07-01 | [打开](https://example.com/news/1) |" in table


@pytest.mark.unit
def test_render_source_table_first_column_escapes_pipe_in_label():
    items = [{"id": "S1", "display_label": "a|b", "title": "t", "source_name": "src"}]

    table = render_source_table(items, ["S1"], heading="引用来源")

    assert "| [a\\|b] | src |" in table


@pytest.mark.unit
def test_render_source_table_sanitizes_link_urls():
    registry = EvidenceRegistry(
        [
            {
                "id": "S1",
                "kind": "news",
                "source_name": "财联社",
                "title": "unsafe scheme",
                "url": "javascript:alert(1)",
            },
            {
                "id": "S2",
                "kind": "news",
                "source_name": "财联社",
                "title": "markdown delimiters",
                "url": "https://example.com/a)b|c?q=x y",
            },
        ]
    )

    table = render_source_table(registry.to_list(), ["S1", "S2"], heading="引用来源")

    assert "javascript:" not in table
    assert "| [S1] | 财联社 | unsafe scheme | - | - |" in table
    assert "[打开](https://example.com/a%29b%7Cc?q=x%20y)" in table
