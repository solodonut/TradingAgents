"""AKShare A-share company news.

The Yahoo news path (``yfinance_news.get_news_yfinance``) returns English
headlines that are nearly empty for mainland tickers. AKShare's
``stock_news_em`` returns the East Money individual-stock news feed in Chinese,
which is what an A-share analyst actually needs. This module mirrors the public
contract of ``get_news_yfinance`` — same arguments, same ``## <ticker> News``
output shape, same look-ahead-safe date window — so the router swaps vendors
transparently.

``stock_news_em`` does not accept a date range, so we fetch the latest feed and
filter locally to the requested ``[start_date, end_date]`` window, preventing
look-ahead leakage in backtests.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

import akshare as ak
import pandas as pd
from dateutil.relativedelta import relativedelta

from .akshare_utils import ak_retry, cached_call, display_symbol, is_a_share, to_bare_code
from .config import get_config
from .errors import NoMarketDataError

# The East Money news feed is intraday-volatile; a 1-hour cache de-dupes the
# repeated calls a single analysis run makes without freezing the feed.
_NEWS_TTL_SECONDS = 3600


def get_news(
    ticker: Annotated[str, "A-share ticker (600519, 600519.SS, ...)"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """Return A-share company news (East Money) within the requested window.

    Same return contract as ``yfinance_news.get_news_yfinance``: a
    ``## <ticker> News, from <start> to <end>`` document with one ``###``
    block per article. Articles outside the window are dropped so a backtest
    never sees news published after its current date.
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
            f"news_{code}",
            _NEWS_TTL_SECONDS,
            lambda: ak_retry(lambda: ak.stock_news_em(symbol=code)),
        )
    except Exception as e:
        return f"Error fetching news for {label}: {str(e)}"

    if df is None or df.empty:
        return f"No news found for {label}"

    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")

    df = df.copy()
    df["_pub"] = pd.to_datetime(df.get("发布时间"), errors="coerce")

    news_str = ""
    kept = 0
    for _, row in df.iterrows():
        pub = row["_pub"]
        if pd.notna(pub) and not (start_dt <= pub.to_pydatetime() <= end_dt + relativedelta(days=1)):
            continue
        title = row.get("新闻标题", "无标题")
        source = row.get("文章来源", "未知来源")
        content = row.get("新闻内容", "")
        link = row.get("新闻链接", "")

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
