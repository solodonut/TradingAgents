"""East Money direct-search A-share news — same-source fallback for AKShare.

``akshare.stock_news_em`` is a thin wrapper over East Money's public search
endpoint (``search-api-web.eastmoney.com``). AKShare breaks at the *library*
level far more often than East Money goes down: an interface rename, a pandas
parse change, a version drift. When that happens the underlying source is still
alive, so this module talks to the endpoint directly and lets the router fall
through from ``akshare`` to ``eastmoney`` without losing Chinese company/ETF
news.

It mirrors the public contract of ``akshare_news.get_news`` exactly — same
arguments, same ``## <label> News`` output shape, same look-ahead-safe window,
the same ``NoMarketDataError`` for non-A-shares and ``Error fetching news``
sentinel on failure — so ``route_to_vendor`` swaps vendors transparently.

Because it hits the *same backend* as AKShare, it only covers library-level
AKShare failures, not an East Money outage — the two fail together when the
source itself is down. A genuinely different source (Sina, CCTV, ...) is what
covers that case.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Annotated

import pandas as pd
import requests
from dateutil.relativedelta import relativedelta

from .akshare_utils import ak_retry, cached_call, display_symbol, is_a_share, to_bare_code
from .config import get_config
from .errors import NoMarketDataError

# Same intraday volatility / de-dup rationale as akshare_news: a 1-hour cache
# collapses the repeated calls a single analysis run makes.
_NEWS_TTL_SECONDS = 3600

_SEARCH_URL = "https://search-api-web.eastmoney.com/search/jsonp"
# East Money wraps every keyword hit in <em>…</em> highlight markup; strip it.
_EM_TAG = re.compile(r"</?em>")


def _strip_em(text: str) -> str:
    return _EM_TAG.sub("", text) if isinstance(text, str) else text


def _fetch_eastmoney_news(code: str, limit: int) -> pd.DataFrame:
    """Fetch the East Money article feed for ``code`` as a DataFrame.

    The endpoint returns JSONP (``x({...})``); we unwrap the callback and parse
    the ``result.cmsArticleWebOld`` list. Ran through ``ak_retry`` by the caller
    so it inherits the proxy bypass and transient-network retry ladder.
    """
    params = {
        "cb": "x",
        "type": "cmsArticleWebOld",
        "client": "web",
        "clientType": "web",
        "clientVersion": "curr",
        "param": json.dumps(
            {
                "uid": "",
                "keyword": code,
                "type": ["cmsArticleWebOld"],
                "pageIndex": 1,
                "pageSize": limit,
                "preTag": "",
                "postTag": "",
            }
        ),
    }
    resp = requests.get(
        _SEARCH_URL,
        params=params,
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://so.eastmoney.com/"},
        timeout=15,
    )
    resp.raise_for_status()
    # The JSONP response has no charset; requests would guess ISO-8859-1 and
    # mangle the Chinese titles. Force UTF-8 before reading .text.
    resp.encoding = "utf-8"
    raw = resp.text
    body = raw[raw.find("(") + 1 : raw.rfind(")")]
    payload = json.loads(body)
    items = (payload.get("result") or {}).get("cmsArticleWebOld") or []
    return pd.DataFrame(items)


def get_news(
    ticker: Annotated[str, "A-share ticker (600519, 600519.SS, ...)"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """Return A-share company/ETF news (East Money) within the requested window.

    Same return contract as ``akshare_news.get_news``: a
    ``## <label> News, from <start> to <end>`` document with one ``###`` block
    per article. Articles outside the window are dropped so a backtest never
    sees news published after its current date.
    """
    if not is_a_share(ticker):
        # Not an East Money company-news symbol: raise so route_to_vendor falls
        # back to the next configured vendor (e.g. longbridge) instead of
        # returning a placeholder that would short-circuit the chain.
        raise NoMarketDataError(ticker, "not an A-share; no East Money company news")

    code = to_bare_code(ticker)
    label = display_symbol(ticker)
    article_limit = get_config()["news_article_limit"]

    try:
        df = cached_call(
            f"em_news_{code}",
            _NEWS_TTL_SECONDS,
            lambda: ak_retry(lambda: _fetch_eastmoney_news(code, article_limit)),
        )
    except Exception as e:
        return f"Error fetching news for {label}: {str(e)}"

    if df is None or df.empty:
        return f"No news found for {label}"

    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")

    df = df.copy()
    df["_pub"] = pd.to_datetime(df.get("date"), errors="coerce")

    news_str = ""
    kept = 0
    for _, row in df.iterrows():
        pub = row["_pub"]
        if pd.notna(pub) and not (start_dt <= pub.to_pydatetime() <= end_dt + relativedelta(days=1)):
            continue
        title = _strip_em(row.get("title", "无标题"))
        source = row.get("mediaName", "未知来源")
        content = _strip_em(row.get("content", ""))
        link = row.get("url", "")

        news_str += f"### {title} (source: {source})\n"
        if isinstance(content, str) and content.strip():
            news_str += f"{content.strip()}\n"
        if isinstance(link, str) and link.strip():
            news_str += f"Link: {link.strip()}\n"
        news_str += "\n"
        kept += 1
        if kept >= article_limit:
            break

    if kept == 0:
        return f"No news found for {label} between {start_date} and {end_date}"

    return f"## {label} News, from {start_date} to {end_date}:\n\n{news_str}"
