"""新浪 7×24 全球财经快讯(``zhibo.sina.com.cn/api/zhibo/feed``)—— ``get_global_news`` 链尾档。

接进来的理由是**境内可用性**:``get_global_news`` 现有三档 yfinance / alpha_vantage /
tushare,前两档在境内网络下不可用(docs/data-sources.md 第 4 节实测 🚫 / ⛔),实际上
只有 Tushare 一档在跑 —— 单点。新浪是可直接补上的境内替代(8.2.4),JSON 返回、
无需解析 HTML。

输出契约与 ``tushare_news.get_global_news`` 对齐:同签名、同 ``## Global Market News``
形状、同「失败返回说明字符串而不抛」的行为(全局新闻不针对单一标的,没有
``NoMarketDataError`` 语义可用)。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Annotated

from .config import get_config
from .sina_utils import fetch_text

_FEED_URL = "https://zhibo.sina.com.cn/api/zhibo/feed"

# 152 = 新浪财经 7×24 全球直播间。
_ZHIBO_ID = 152

# 上游单页上限;超过 limit 的部分在渲染阶段截断。
_PAGE_SIZE = 100


def _fetch_feed(page_size: int) -> list[dict]:
    payload = fetch_text(
        _FEED_URL,
        params={
            "page": 1,
            "page_size": page_size,
            "zhibo_id": _ZHIBO_ID,
            "tag_id": 0,
            "dire": "f",
            "dpc": 1,
        },
    )
    data = json.loads(payload)
    feed = ((data.get("result") or {}).get("data") or {}).get("feed") or {}
    return [item for item in (feed.get("list") or []) if isinstance(item, dict)]


def get_global_news(
    curr_date: Annotated[str, "Current date in yyyy-mm-dd format"],
    look_back_days: int | None = None,
    limit: int | None = None,
) -> str:
    """返回窗口内的全球财经快讯(新浪 7×24),按时间倒序。"""
    config = get_config()
    if look_back_days is None:
        look_back_days = config["global_news_lookback_days"]
    if limit is None:
        limit = config["global_news_article_limit"]

    curr_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    start_dt = curr_dt - timedelta(days=look_back_days)
    start_date = start_dt.strftime("%Y-%m-%d")
    # 含 curr_date 当天全天。
    window_end = curr_dt + timedelta(days=1)

    try:
        items = _fetch_feed(min(max(limit * 2, 20), _PAGE_SIZE))
    except Exception as e:
        # 与 tushare 版一致:全局新闻没有单标的语义,失败返回说明字符串而不抛,
        # 让 route_to_vendor 继续走链或让 agent 看到明确的失败原因。
        return f"Error fetching global news for {curr_date}: {e}"

    rows: list[tuple[datetime, str]] = []
    for item in items:
        text = (item.get("rich_text") or "").strip()
        if not text:
            continue
        try:
            published = datetime.strptime(item.get("create_time", ""), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        if not (start_dt <= published < window_end):
            continue
        block = f"### [{published:%Y-%m-%d %H:%M:%S}] {text} (source: 新浪财经 7×24)\n"
        url = (item.get("docurl") or "").strip()
        if url:
            block += f"Link: {url}\n"
        rows.append((published, block + "\n"))

    rows.sort(key=lambda r: r[0], reverse=True)

    body = ""
    for _, block in rows[:limit]:
        body += block

    if not body:
        return f"No global news found between {start_date} and {curr_date}"

    return f"## Global Market News, from {start_date} to {curr_date}:\n\n{body}"
