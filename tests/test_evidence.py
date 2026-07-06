import pytest

from tradingagents.graph.evidence import (
    EvidenceRegistry,
    extract_citation_ids,
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
    assert "| [S2] | AKShare | get_stock_data: 600519 | 2026-06-29..2026-07-06 | - |" in table
    assert "| [S1] | 财联社 | 半导体板块获政策支持 | 2026-07-01 | [打开](https://example.com/news/1) |" in table
    assert "S404" not in table
