from tradingagents.agents.utils.prefetch_context import build_prefetch_block


def test_block_includes_news_and_quote():
    pf = {"news_text": "重要新闻...", "quote": {"last_price": 4.82, "trade_date": "2026-07-07"}, "missing": []}
    block = build_prefetch_block(pf, want_news=True, want_quote=True)
    assert "重要新闻" in block
    assert "4.82" in block


def test_block_marks_missing():
    pf = {"news_text": None, "quote": None, "missing": ["news", "intraday"]}
    block = build_prefetch_block(pf, want_news=True, want_quote=True)
    assert "暂缺" in block or "unavailable" in block.lower()


def test_block_empty_when_none():
    assert build_prefetch_block(None, want_news=True, want_quote=True) == ""
