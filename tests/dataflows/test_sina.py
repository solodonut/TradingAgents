"""新浪财经 vendor 单测(个股新闻 + 全局快讯)。不触网。

fixture 是 2026-09-04 从上游抓的真实响应,只 mock 网络边界,HTML/JSON 解析走真实代码。

⚠️ **新浪个股新闻对场内基金无效**(2026-09-04 实测):``vCB_AllNewsStock`` 会忽略基金
代码,给 510300 和 159241 返回的页面**字节完全相同**——都是通用大盘新闻,还夹带广告。
所以基金代码必须抛 ``NoMarketDataError`` 让路由回退到东财/Tushare。把通用大盘新闻当成
某只 ETF 的新闻喂给 agent,正是 AGENTS.md 禁止的那类编造。
"""

from __future__ import annotations

import pathlib
from unittest import mock

import pytest

from tradingagents.dataflows.errors import NoMarketDataError

pytestmark = pytest.mark.unit

_FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def _fixture(name: str) -> str:
    return (_FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture
def stock_news_html():
    return _fixture("sina_news_sh600519.html")


@pytest.fixture
def zhibo_feed():
    return _fixture("sina_zhibo_feed.json")


# --------------------------------------------------------------------------
# get_news —— 个股新闻
# --------------------------------------------------------------------------


def test_news_matches_shared_output_contract(stock_news_html):
    """输出形状与 eastmoney_news.get_news 一致,路由才能透明换源。"""
    from tradingagents.dataflows import sina_news

    with mock.patch.object(sina_news, "fetch_text", return_value=stock_news_html):
        out = sina_news.get_news("600519", "2026-09-02", "2026-09-04")

    assert out.startswith("## 600519.SS News, from 2026-09-02 to 2026-09-04:")
    assert "### " in out
    assert "8月白酒行业观察" in out


def test_news_includes_publish_time_per_article(stock_news_html):
    """每条新闻要带发布时间。

    docs/data-sources.md 8.2.6 指出东财模板丢了这个字段,agent 拿到新闻后无从判断新旧。
    新浪本身给了时间,不该在这里丢掉。
    """
    from tradingagents.dataflows import sina_news

    with mock.patch.object(sina_news, "fetch_text", return_value=stock_news_html):
        out = sina_news.get_news("600519", "2026-09-02", "2026-09-04")

    assert "2026-09-04 09:50" in out, f"缺发布时间,实际输出:\n{out[:600]}"


def test_news_drops_articles_outside_window(stock_news_html):
    """窗口外的文章必须丢掉 —— 回测不能看到当前日期之后的新闻。

    fixture 覆盖 09-02~09-04;只要 09-03~09-04 时,09-02 的条目不能出现。
    """
    from tradingagents.dataflows import sina_news

    with mock.patch.object(sina_news, "fetch_text", return_value=stock_news_html):
        out = sina_news.get_news("600519", "2026-09-03", "2026-09-04")

    assert "2026-09-04" in out
    assert "2026-09-02" not in out, f"泄漏了窗口外的新闻:\n{out}"


def test_news_sorted_newest_first(stock_news_html):
    """按时间倒序自排,不依赖页面顺序 —— 广告行会打乱上游的顺序。"""
    from tradingagents.dataflows import sina_news

    with mock.patch.object(sina_news, "fetch_text", return_value=stock_news_html):
        out = sina_news.get_news("600519", "2026-09-02", "2026-09-04")

    times = [line for line in out.splitlines() if line.startswith("### [")]
    stamps = [t.removeprefix("### [").split("]")[0] for t in times]
    assert stamps == sorted(stamps, reverse=True), f"未按时间倒序: {stamps[:6]}"


def test_news_filters_promo_rows(stock_news_html):
    """广告行(finance.sina.cn/app/... 推广链接)必须过滤掉。

    ETF 页实测夹 2 条这种行(「牛人一天赚5.7%！快看看TA买了什么？」),个股页当天没有,
    所以这里注入一条 —— 上游随时会插,不能靠 fixture 恰好没有来通过。
    """
    from tradingagents.dataflows import sina_news

    promo = (
        "&nbsp;&nbsp;&nbsp;&nbsp;2026-09-04&nbsp;09:59&nbsp;&nbsp;"
        "<a target='_blank' href='https://finance.sina.cn/app/boshi_home.shtml'>"
        "牛人一天赚5.7%！快看看TA买了什么？</a> <br>"
    )
    injected = stock_news_html.replace('<div class="datelist"><ul>',
                                       '<div class="datelist"><ul>' + promo, 1)

    with mock.patch.object(sina_news, "fetch_text", return_value=injected):
        out = sina_news.get_news("600519", "2026-09-02", "2026-09-04")

    assert "牛人一天赚" not in out, f"广告没被过滤:\n{out[:600]}"


def test_news_rejects_fund_symbol():
    """场内基金必须抛错 —— 上游对基金代码返回的是通用大盘新闻,不是该基金的新闻。"""
    from tradingagents.dataflows import sina_news

    with pytest.raises(NoMarketDataError):
        sina_news.get_news("510300", "2026-09-02", "2026-09-04")


def test_news_rejects_non_a_share():
    from tradingagents.dataflows import sina_news

    with pytest.raises(NoMarketDataError):
        sina_news.get_news("AAPL", "2026-09-02", "2026-09-04")


def test_news_raises_when_no_rows_parsed():
    """页面结构变了(解析不出任何行)要抛错,不能静默返回空报告。"""
    from tradingagents.dataflows import sina_news

    with (
        mock.patch.object(sina_news, "fetch_text", return_value="<html>nothing</html>"),
        pytest.raises(NoMarketDataError),
    ):
        sina_news.get_news("600519", "2026-09-02", "2026-09-04")


# --------------------------------------------------------------------------
# get_global_news —— 全局快讯
# --------------------------------------------------------------------------


def test_global_news_matches_shared_output_contract(zhibo_feed):
    """与 tushare_news.get_global_news 同形状,路由才能透明换源。"""
    from tradingagents.dataflows import sina_global_news

    with mock.patch.object(sina_global_news, "fetch_text", return_value=zhibo_feed):
        out = sina_global_news.get_global_news("2026-09-04", look_back_days=2, limit=20)

    assert out.startswith("## Global Market News, from 2026-09-02 to 2026-09-04:")
    assert "片山皋月将继续担任日本财务大臣" in out
    assert "2026-09-04 10:37:52" in out


def test_global_news_respects_limit(zhibo_feed):
    from tradingagents.dataflows import sina_global_news

    with mock.patch.object(sina_global_news, "fetch_text", return_value=zhibo_feed):
        out = sina_global_news.get_global_news("2026-09-04", look_back_days=2, limit=3)

    assert out.count("### ") == 3


def test_global_news_drops_items_outside_window(zhibo_feed):
    """fixture 全是 09-04 的条目;要 09-01 那天的应当一条都留不下。"""
    from tradingagents.dataflows import sina_global_news

    with mock.patch.object(sina_global_news, "fetch_text", return_value=zhibo_feed):
        out = sina_global_news.get_global_news("2026-09-01", look_back_days=1, limit=20)

    assert "No global news found" in out
    assert "片山皋月" not in out


def test_global_news_reports_error_when_upstream_unparseable():
    """上游给了非 JSON(限频页/维护页)时返回错误说明,不抛、不编造。"""
    from tradingagents.dataflows import sina_global_news

    with mock.patch.object(sina_global_news, "fetch_text", return_value="<html>429</html>"):
        out = sina_global_news.get_global_news("2026-09-04", look_back_days=2, limit=20)

    assert out.startswith("Error fetching global news")
