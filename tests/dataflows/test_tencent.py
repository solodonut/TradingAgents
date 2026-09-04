"""腾讯 ``qt.gtimg.cn`` / ``web.ifzq.gtimg.cn`` vendor 单测。不触网。

fixture 是 2026-09-04 从上游抓的真实响应(``tests/dataflows/fixtures/``),只 mock
网络边界(``tencent_utils.fetch_text``),解析与格式化走真实代码路径。

字段位置来自实测(见 docs/data-sources.md 第 8.1 节):按 ``~`` 切开 88 个字段后
第 78 位是 IOPV、第 81 位是单位净值、第 61 位是品种标记("ETF" / "GP-A")。
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
def etf_quote():
    return _fixture("tencent_quote_sh510300.txt")


@pytest.fixture
def stock_quote():
    return _fixture("tencent_quote_sh600519.txt")


# --------------------------------------------------------------------------
# get_etf_realtime
# --------------------------------------------------------------------------


def test_etf_realtime_reports_iopv_nav_and_price(etf_quote):
    """IOPV / 单位净值 / 现价三项都出现在报告里,取值来自实测字段位置。

    数值是 fixture(2026-09-04 10:37:58 快照)里的真实值。写死而不是从同样的下标反算,
    否则下标取错时测试会跟着一起错、什么也测不出来。
    """
    from tradingagents.dataflows import tencent_etf

    with mock.patch.object(tencent_etf, "fetch_text", return_value=etf_quote):
        out = tencent_etf.get_etf_realtime("510300")

    assert "4.6468" in out, "IOPV(第 78 位)应出现在报告里"
    assert "4.6188" in out, "单位净值(第 81 位)应出现在报告里"
    assert "4.6450" in out, "现价(第 3 位)应出现在报告里"
    assert "沪深300ETF华泰柏瑞" in out


def test_etf_realtime_computes_discount_premium_from_iopv(etf_quote):
    """折溢价率 = (现价 - IOPV) / IOPV。现价 4.645 / IOPV 4.6468 → -0.04%。

    这个期望值同时被上游交叉验证过:腾讯第 77 位(它自己算的折溢价率)在这份 fixture 里
    也是 -0.04,说明我们的公式与上游口径一致。用自算值是为了公式透明可审计。
    """
    from tradingagents.dataflows import tencent_etf

    with mock.patch.object(tencent_etf, "fetch_text", return_value=etf_quote):
        out = tencent_etf.get_etf_realtime("510300")

    assert "-0.04%" in out, f"缺折溢价率,实际输出:\n{out}"


def test_etf_realtime_rejects_non_fund_symbol():
    """个股代码必须抛 NoMarketDataError,让路由跳到下一档而不是返回股票快照。"""
    from tradingagents.dataflows import tencent_etf

    with pytest.raises(NoMarketDataError):
        tencent_etf.get_etf_realtime("600519")


def test_etf_realtime_formats_snapshot_timestamp(etf_quote):
    """上游时间戳是紧凑串(20260904103758),要格式化再喂给 LLM。

    IOPV 只在盘中有效,agent 必须能一眼看出这份快照是什么时候的;裸数字串容易被误读。
    """
    from tradingagents.dataflows import tencent_etf

    with mock.patch.object(tencent_etf, "fetch_text", return_value=etf_quote):
        out = tencent_etf.get_etf_realtime("510300")

    assert "2026-09-04 10:37:58" in out, f"时间戳未格式化,实际输出:\n{out}"
    assert "20260904103758" not in out


def test_etf_realtime_rejects_when_upstream_type_is_not_a_fund(stock_quote):
    """即使代码看着像基金,上游品种标记(第 61 位)不是 ETF 也要拒绝。

    防的是「代码段判断」与上游真实品种不一致时把股票快照当 ETF 报出去。
    """
    from tradingagents.dataflows import tencent_etf

    with (
        mock.patch.object(tencent_etf, "fetch_text", return_value=stock_quote),
        pytest.raises(NoMarketDataError),
    ):
        tencent_etf.get_etf_realtime("510300")


def test_etf_realtime_rejects_zero_price_snapshot(etf_quote):
    """停牌/上游异常返回 0 价必须抛错,不能把 0 当成真实价格报出去。

    这是 docs/data-sources.md 9.3.1 的零值拦截硬要求 —— 反幻觉约定的一部分。
    """
    from tradingagents.dataflows import tencent_etf

    # 按下标改字段而不是字符串替换 —— 后者依赖 fixture 的具体价格,换一份快照就失效。
    fields = etf_quote.split('="', 1)[1].rstrip().rstrip(";").rstrip('"').split("~")
    fields[3] = "0.000"
    zeroed = f'v_sh510300="{"~".join(fields)}";'

    with (
        mock.patch.object(tencent_etf, "fetch_text", return_value=zeroed),
        pytest.raises(NoMarketDataError),
    ):
        tencent_etf.get_etf_realtime("510300")


def test_etf_realtime_rejects_empty_upstream_body():
    """上游返回空串(限频/被拦)时抛错,而不是解析出一堆空字段。"""
    from tradingagents.dataflows import tencent_etf

    with (
        mock.patch.object(tencent_etf, "fetch_text", return_value='v_sh510300="";'),
        pytest.raises(NoMarketDataError),
    ):
        tencent_etf.get_etf_realtime("510300")


# --------------------------------------------------------------------------
# get_stock_data (日K)
# --------------------------------------------------------------------------


def test_stock_data_returns_csv_with_ohlcv(etf_quote):
    """日K 输出与 tushare_stock 同形状:带说明 header 的 CSV,列名 Date/Open/High/Low/Close/Volume。

    注意上游 qfqday 每行顺序是 [日期, 开, **收**, 高, 低, 量] —— 收盘价在第 3 位,
    不是常见的 OHLC 顺序,写错会静默产生错误的高低价。
    """
    from tradingagents.dataflows import tencent_stock

    kline = _fixture("tencent_kline_sh510300.json")
    with mock.patch.object(tencent_stock, "fetch_text", return_value=kline):
        out = tencent_stock.get_stock_data("510300", "2026-08-20", "2026-09-04")

    assert "Date,Open,High,Low,Close,Volume" in out
    # 2026-08-20 上游是 ["2026-08-20","4.670","4.653","4.689","4.632","7488663.000"]
    # → 开 4.670 / 收 4.653 / 高 4.689 / 低 4.632
    assert "2026-08-20,4.670,4.689,4.632,4.653," in out, f"OHLC 顺序错,实际:\n{out}"


def test_stock_data_rejects_non_mainland_symbol():
    from tradingagents.dataflows import tencent_stock

    with pytest.raises(NoMarketDataError):
        tencent_stock.get_stock_data("AAPL", "2026-08-20", "2026-09-04")


def test_stock_data_raises_when_upstream_returns_no_rows():
    """上游 code=0 但 K 线为空 → NoMarketDataError,让路由继续找下一档。"""
    from tradingagents.dataflows import tencent_stock

    empty = '{"code":0,"msg":"","data":{"sh510300":{"qfqday":[]}}}'
    with (
        mock.patch.object(tencent_stock, "fetch_text", return_value=empty),
        pytest.raises(NoMarketDataError),
    ):
        tencent_stock.get_stock_data("510300", "2026-08-20", "2026-09-04")


def test_stock_data_filters_rows_outside_requested_window():
    """窗口外的行必须丢掉 —— 否则回测会看到 end_date 之后的价格。"""
    from tradingagents.dataflows import tencent_stock

    kline = _fixture("tencent_kline_sh510300.json")
    with mock.patch.object(tencent_stock, "fetch_text", return_value=kline):
        out = tencent_stock.get_stock_data("510300", "2026-08-20", "2026-08-25")

    assert "2026-08-25" in out
    assert "2026-08-26" not in out, f"泄漏了窗口外的未来数据:\n{out}"
