"""新浪财经个股新闻(``vCB_AllNewsStock``)—— ``get_news`` 链尾档。

接进来的理由是**上游独立性**:``get_news`` 现有两档 ``eastmoney,tushare`` 实测是同一个
上游(东财),链式 fallback 的冗余是假的(docs/data-sources.md 第 5 节)。新浪是真正
不同的上游,东财挂掉时这一档还能出数。实测新鲜度也更好(同一时刻新浪有当天条目,
东财搜索索引最新一条是两天前)—— 但那是单标的单日观测,不作为链序依据。

⚠️ **只支持个股,不支持场内基金。** 2026-09-04 实测:上游忽略基金代码,给 510300 和
159241 返回**字节完全相同**的通用大盘新闻页(还夹广告)。所以基金一律抛
``NoMarketDataError`` 回退东财/Tushare —— 把通用大盘新闻当成某只 ETF 的新闻,属于
AGENTS.md 明令禁止的编造。

输出契约与 ``eastmoney_news.get_news`` 对齐(同参数、同 ``## <label> News`` 形状、同
窗口过滤),额外**保留每条的发布时间** —— 东财那版丢了这个字段(8.2.6),agent 拿到
新闻后无从判断新旧。
"""

from __future__ import annotations

import html
import re
from datetime import datetime
from typing import Annotated

from .akshare_utils import display_symbol, is_a_share, is_etf_code, to_bare_code, to_prefixed_code
from .config import get_config
from .errors import NoMarketDataError
from .sina_utils import fetch_text

_NEWS_URL = "https://vip.stock.finance.sina.com.cn/corp/view/vCB_AllNewsStock.php"

# 老页面是 GB18030,响应头不带 charset。
_ENCODING = "gb18030"

# 新闻列表在 <div class="datelist"> 里,先切出这一块再逐行解析,免得匹配到页面其它链接。
_DATELIST = re.compile(r'<div class="datelist">(.*?)</div>', re.DOTALL)

# 每行形如:  2026-09-04&nbsp;09:50&nbsp;&nbsp;<a target='_blank' href='...'>标题</a> <br>
_ROW = re.compile(
    r"(\d{4}-\d{2}-\d{2})&nbsp;(\d{2}:\d{2})&nbsp;&nbsp;"
    r"<a[^>]*href='([^']+)'>(.*?)</a>",
    re.DOTALL,
)

# 推广行:链接指向 App/活动页而非新闻正文。ETF 页实测固定夹 2 条,个股页也可能插。
_PROMO = re.compile(r"finance\.sina\.c(?:n|om\.cn)/app/")


def _parse_rows(page: str) -> list[tuple[datetime, str, str]]:
    """解析出 ``(发布时间, 标题, 链接)`` 列表,已剔除推广行。"""
    block = _DATELIST.search(page)
    if not block:
        return []

    rows: list[tuple[datetime, str, str]] = []
    for date, time_str, url, title in _ROW.findall(block.group(1)):
        if _PROMO.search(url):
            continue
        title = html.unescape(re.sub(r"<[^>]+>", "", title)).strip()
        if not title:
            continue
        try:
            published = datetime.strptime(f"{date} {time_str}", "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        rows.append((published, title, url.strip()))
    return rows


def get_news(
    ticker: Annotated[str, "A-share stock ticker (600519, 600519.SS, ...)"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """返回窗口内的个股新闻(新浪),形状同 ``eastmoney_news.get_news``。"""
    if not is_a_share(ticker):
        raise NoMarketDataError(ticker, ticker, "not an A-share; no Sina company news")

    code = to_bare_code(ticker)
    if is_etf_code(code):
        # 上游对基金代码返回通用大盘新闻(实测两只不同 ETF 页面字节相同),不是该基金的
        # 新闻。抛错让 route_to_vendor 回退到能给 ETF 新闻的档。
        raise NoMarketDataError(
            ticker, code, "Sina company news does not cover listed funds (returns generic market news)"
        )

    label = display_symbol(ticker)
    article_limit = get_config()["news_article_limit"]

    page = fetch_text(
        _NEWS_URL,
        params={"symbol": to_prefixed_code(ticker).lower(), "Page": "1"},
        encoding=_ENCODING,
    )
    rows = _parse_rows(page)
    if not rows:
        raise NoMarketDataError(
            ticker, code, "Sina returned no parseable article rows (page structure may have changed)"
        )

    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    # 含 end_date 当天全天。
    end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59)

    # 自己按时间倒序:上游的页面顺序会被推广行打乱,不能依赖。
    rows.sort(key=lambda r: r[0], reverse=True)

    body = ""
    kept = 0
    for published, title, url in rows:
        if not (start_dt <= published <= end_dt):
            continue
        body += f"### [{published:%Y-%m-%d %H:%M}] {title} (source: 新浪财经)\n"
        if url:
            body += f"Link: {url}\n"
        body += "\n"
        kept += 1
        if kept >= article_limit:
            break

    if kept == 0:
        return f"No news found for {label} between {start_date} and {end_date}"

    return f"## {label} News, from {start_date} to {end_date}:\n\n{body}"
