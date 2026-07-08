"""Assemble the pre-fetched data block pushed into analyst prompts."""

from __future__ import annotations


def build_prefetch_block(prefetched, *, want_news: bool, want_quote: bool) -> str:
    if not prefetched:
        return ""

    missing = set(prefetched.get("missing") or [])
    lines: list[str] = []

    if want_quote:
        quote = prefetched.get("quote")
        if quote:
            lines.append(
                f"- 当前行情快照(预取):最新价 {quote['last_price']}(交易日 {quote['trade_date']})。"
            )
        elif "intraday" in missing:
            lines.append("- ⚠️ 分时/行情快照本次预取暂缺,不可用——请勿臆测价格。")

    if want_news:
        news_text = prefetched.get("news_text")
        if news_text:
            lines.append("- 预取新闻(直接使用,无需再调用工具):\n" + str(news_text))
        elif "news" in missing:
            lines.append("- ⚠️ 新闻本次预取暂缺,不可用——请如实说明缺失,不要编造。")

    if not lines:
        return ""
    return "\n\n【预取数据(本次分析开始前已抓取)】\n" + "\n".join(lines) + "\n"
