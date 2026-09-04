"""腾讯 ETF 实时快照:IOPV / 单位净值 / 折溢价率。

**这是 IOPV 在本项目里唯一的数据源。** AKShare 停用后实时 IOPV 与折溢价率彻底断供
(docs/data-sources.md 7.2 表格里唯一的实质损失),这个模块把它补回来。

刻意**不**登记到 ``get_etf_profile``:腾讯只给实时快照,没有份额/规模/前十成分/历史净值
序列,而 ``route_to_vendor`` 是链首成功即停 —— 放在链首会把 Tushare 那份更完整的画像
永久挤掉。两者是互补关系,所以走独立方法 ``get_etf_realtime``。

字段位置为 2026-09-04 实测(510300 / 159241 / 588000 三只交叉验证):
第 3 位现价、第 61 位品种标记、第 78 位 IOPV、第 81 位单位净值。腾讯第 78 位与东财
``f441`` 完全一致(4.6744 = 4.6744),第 81 位等于东财 ``lsjz`` 的 ``DWJZ``。
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from .akshare_utils import display_symbol, is_a_share, is_etf_code, to_bare_code, to_prefixed_code
from .errors import NoMarketDataError
from .tencent_utils import fetch_text, parse_quote_fields

_QUOTE_URL = "https://qt.gtimg.cn/q="

# 按 ~ 切开后的下标(实测)
_IDX_NAME = 1
_IDX_PRICE = 3
_IDX_PREV_CLOSE = 4
_IDX_TIMESTAMP = 30
_IDX_KIND = 61
_IDX_IOPV = 78
_IDX_NAV = 81

# 第 61 位的品种标记:ETF/LOF 是场内基金,GP-A 是 A 股个股。
_FUND_KINDS = {"ETF", "LOF"}


def _to_float(raw: str) -> float | None:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _format_timestamp(raw: str) -> str:
    """``20260904103758`` → ``2026-09-04 10:37:58``。

    IOPV 只在盘中有效,agent 必须一眼看出快照时点;裸数字串容易被误读成别的东西。
    解析不了就原样返回,不猜。
    """
    raw = (raw or "").strip()
    try:
        return datetime.strptime(raw, "%Y%m%d%H%M%S").strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return raw


def get_etf_realtime(
    symbol: Annotated[str, "mainland China listed ETF/fund code, e.g. 510300 or 510300.SS"],
    curr_date: Annotated[str, "current date, yyyy-mm-dd (unused; snapshot is live)"] = None,
) -> str:
    """返回场内基金的实时 IOPV / 单位净值 / 折溢价率快照。

    非基金代码、上游品种标记不是基金、价格或 IOPV 为 0(停牌/异常)、上游空响应,
    统统抛 ``NoMarketDataError`` —— 让 ``route_to_vendor`` 跳到下一档或返回
    NO_DATA_AVAILABLE 哨兵,绝不返回可能被当成真实价格的 0 值。
    """
    if not is_a_share(symbol):
        raise NoMarketDataError(symbol, symbol, "not a mainland symbol for Tencent")

    code = to_bare_code(symbol)
    if not is_etf_code(code):
        raise NoMarketDataError(
            symbol, code, "not a mainland China listed ETF/fund (code range)"
        )

    label = display_symbol(symbol)
    prefixed = to_prefixed_code(symbol).lower()
    fields = parse_quote_fields(fetch_text(f"{_QUOTE_URL}{prefixed}", encoding="gbk"))

    if len(fields) <= _IDX_NAV:
        raise NoMarketDataError(
            symbol, code, f"Tencent returned {len(fields)} fields, expected at least {_IDX_NAV + 1}"
        )

    kind = fields[_IDX_KIND].strip().upper()
    if kind and kind not in _FUND_KINDS:
        # 代码段判断说是基金,上游说不是 —— 以上游为准,别把股票快照当 ETF 报出去。
        raise NoMarketDataError(
            symbol, code, f"Tencent reports instrument kind {kind!r}, not a listed fund"
        )

    price = _to_float(fields[_IDX_PRICE])
    iopv = _to_float(fields[_IDX_IOPV])
    nav = _to_float(fields[_IDX_NAV])
    prev_close = _to_float(fields[_IDX_PREV_CLOSE])

    # 零值拦截(docs/data-sources.md 9.3.1 的硬要求):停牌或上游异常时腾讯会返回 0,
    # 把 0 当价格报出去等于伪造数据。
    if not price or not iopv:
        raise NoMarketDataError(
            symbol, code, "Tencent returned a zero price/IOPV (suspended or upstream error)"
        )

    premium_pct = (price - iopv) / iopv * 100

    lines = [
        f"## {label} ETF Realtime Snapshot (Tencent)",
        "",
        f"- Name: {fields[_IDX_NAME]}",
        f"- Snapshot time: {_format_timestamp(fields[_IDX_TIMESTAMP])}",
        f"- Last price: {price:.4f}",
        f"- IOPV (indicative optimized portfolio value): {iopv:.4f}",
        f"- Premium/discount vs IOPV: {premium_pct:+.2f}%",
    ]
    if nav:
        lines.append(f"- Unit NAV (T-1): {nav:.4f}")
    if prev_close:
        lines.append(f"- Previous close: {prev_close:.4f}")
    lines += [
        "",
        "Premium/discount is computed as (last price - IOPV) / IOPV. A positive value "
        "means the fund trades above the value of its underlying basket (premium), a "
        "negative value means it trades below (discount). IOPV is a live intraday "
        "estimate; unit NAV is the T-1 official value.",
    ]
    return "\n".join(lines)
