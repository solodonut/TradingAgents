"""Extract structured portfolio holdings from an uploaded screenshot."""

import base64
import json
import re

from langchain_core.messages import HumanMessage

from api.schemas import PortfolioHolding

_EXTRACT_INSTRUCTION = (
    "这是一张投资组合 / 交易记录截图。请逐行提取其中的持仓与交易记录。"
    "截图可能来自不同券商、银行、基金或加密货币平台,列名和排版不固定。"
    "先识别表格语义,再映射到统一字段。"
    "不要猜测看不清的股票/基金代码或数字;不确定的字段设为 null 或省略。"
    "若股票/基金代码看不清但名称清楚,输出 name,并可用名称作为 ticker/identifier;不要编造代码。"
    "遇到券商持仓表的“成本/现价”上下两行时,上面的数字是 avg_cost,下面的数字是 current_price。"
    "例如“1.233 / 1.170”必须输出 avg_cost=1.233,current_price=1.170,不要把 1.170 填到 avg_cost。"
    "遇到“持仓/可用”上下两行时,上面的数字是 shares。"
    "遇到基金平台“金额/昨日收益/持有收益/率”时,金额是 market_value,昨日收益是 daily_pnl,持有收益是 unrealized_pnl,持有收益率是 return_rate。"
    "交易流水必须尽量提取 trade_date,并用 action=buy 或 sell 标记买入/卖出。"
    "百分比去掉百分号后输出数值,金额和股数只输出数字。"
    "输出一个 JSON 数组,每个元素包含可识别到的字段:"
    "ticker(代码或名称标识)、name(名称)、shares(股数/份额)、avg_cost(成本价)、current_price(现价)、"
    "market_value(金额/市值)、weight(仓位占比百分比数值)、unrealized_pnl(持有盈亏/持有收益)、"
    "return_rate(持有收益率百分比数值)、daily_pnl(当日或昨日收益)、"
    "daily_return_rate(当日收益率百分比数值)、action(buy/sell,若为交易记录)、trade_date(交易日期)。"
    "无法识别的字段省略或设为 null。"
    "只输出 JSON 数组,不要其它文字。若无法识别任何持仓,输出空数组 []。"
)

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)
_JSON_DECODER = json.JSONDecoder()

_FIELD_ALIASES = {
    "ticker": [
        "ticker",
        "symbol",
        "code",
        "证券代码",
        "股票代码",
        "基金代码",
        "代码",
        "标的代码",
    ],
    "name": [
        "name",
        "security_name",
        "证券名称",
        "股票名称",
        "基金名称",
        "基金简称",
        "产品名称",
        "名称",
        "标的名称",
    ],
    "shares": [
        "shares",
        "qty",
        "quantity",
        "持仓数量",
        "持有数量",
        "成交数量",
        "数量",
        "股数",
        "份额",
    ],
    "avg_cost": [
        "avg_cost",
        "average_cost",
        "cost",
        "cost_price",
        "成本价",
        "成本",
        "持仓成本",
        "买入均价",
    ],
    "current_price": ["current_price", "price", "现价", "当前价", "最新价"],
    "market_value": [
        "market_value",
        "marketVal",
        "value",
        "amount_value",
        "amount",
        "holding_amount",
        "holding_value",
        "金额",
        "持有金额",
        "持仓金额",
        "市值",
        "持仓市值",
        "参考市值",
        "资产",
    ],
    "weight": [
        "weight",
        "ratio",
        "percent",
        "portfolio_weight",
        "持仓占比",
        "占比",
        "仓位占比",
        "仓位",
        "比例",
    ],
    "unrealized_pnl": [
        "unrealized_pnl",
        "holding_pnl",
        "profit",
        "pnl",
        "持有收益",
        "持仓收益",
        "持有盈亏",
        "持仓盈亏",
        "盈亏",
    ],
    "return_rate": [
        "return_rate",
        "holding_return_rate",
        "profit_rate",
        "持有收益率",
        "持仓收益率",
        "持有盈亏率",
        "收益率",
    ],
    "daily_pnl": [
        "daily_pnl",
        "day_pnl",
        "yesterday_income",
        "昨日收益",
        "当日收益",
        "当日盈亏",
        "昨日盈亏",
    ],
    "daily_return_rate": [
        "daily_return_rate",
        "day_return_rate",
        "当日收益率",
        "当日盈亏率",
        "昨日收益率",
    ],
    "action": ["action", "side", "type", "操作", "交易方向", "买卖方向", "业务类型"],
    "trade_date": ["trade_date", "date", "成交日期", "交易日期", "日期", "委托日期"],
}

_COMBINED_ALIASES = {
    ("shares",): ["持仓/可用", "持有/可用"],
    ("avg_cost", "current_price"): ["成本/现价", "成本价/现价", "成本/当前价"],
}

_ROW_LIST_KEYS = [
    "holdings",
    "positions",
    "portfolio",
    "transactions",
    "trades",
    "records",
    "data",
    "rows",
]


def build_vision_message(image_bytes: bytes, mime: str = "image/png") -> HumanMessage:
    b64 = base64.b64encode(image_bytes).decode()
    return HumanMessage(
        content=[
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            {"type": "text", "text": _EXTRACT_INSTRUCTION},
        ]
    )


def _load_json_loose(text: str):
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass

    for match in re.finditer(r"[\[{]", text):
        try:
            value, _ = _JSON_DECODER.raw_decode(text[match.start() :])
            return value
        except json.JSONDecodeError:
            continue
    raise ValueError("no JSON payload found")


def _payload_rows(data) -> list[dict]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if not isinstance(data, dict):
        return []

    rows: list[dict] = []
    for key in _ROW_LIST_KEYS:
        value = data.get(key)
        if isinstance(value, list):
            rows.extend(item for item in value if isinstance(item, dict))
    if rows:
        return rows
    return [data]


def _first_value(item: dict, aliases: list[str]):
    for key in aliases:
        if key in item and item[key] not in (None, ""):
            return item[key]
    return None


def _clean_number(value):
    if value in (None, ""):
        return None
    if isinstance(value, int | float):
        return value
    text = str(value).replace(",", "").strip()
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    number = float(match.group(0))
    return int(number) if number.is_integer() else number


def _clean_numbers(value) -> list[float | int]:
    if value in (None, ""):
        return []
    if isinstance(value, int | float):
        return [value]
    text = str(value).replace(",", "").strip()
    numbers = []
    for raw in re.findall(r"-?\d+(?:\.\d+)?", text):
        number = float(raw)
        numbers.append(int(number) if number.is_integer() else number)
    return numbers


def _clean_action(value):
    if value in (None, ""):
        return None
    text = str(value).strip().lower()
    if text in {"buy", "b", "买", "买入", "申购", "加仓"} or "买入" in text:
        return "buy"
    if text in {"sell", "s", "卖", "卖出", "赎回", "减仓"} or "卖出" in text:
        return "sell"
    return value


def _normalize_item(item: dict) -> dict:
    normalized = dict(item)
    for fields, aliases in _COMBINED_ALIASES.items():
        value = _first_value(item, aliases)
        if value in (None, ""):
            continue
        numbers = _clean_numbers(value)
        for index, field in enumerate(fields):
            if normalized.get(field) in (None, "") and index < len(numbers):
                normalized[field] = numbers[index]

    for field, aliases in _FIELD_ALIASES.items():
        if normalized.get(field) in (None, ""):
            value = _first_value(item, aliases)
            if value not in (None, ""):
                normalized[field] = value

    if normalized.get("name") not in (None, ""):
        normalized["name"] = str(normalized["name"]).strip()
    if normalized.get("ticker") in (None, "") and normalized.get("name") not in (None, ""):
        normalized["ticker"] = normalized["name"]
    elif normalized.get("ticker") not in (None, ""):
        normalized["ticker"] = str(normalized["ticker"]).strip().upper()
    for field in [
        "shares",
        "avg_cost",
        "current_price",
        "market_value",
        "weight",
        "unrealized_pnl",
        "return_rate",
        "daily_pnl",
        "daily_return_rate",
    ]:
        normalized[field] = _clean_number(normalized.get(field))
    normalized["action"] = _clean_action(normalized.get("action"))
    return normalized


def parse_holdings_json(raw: str) -> list[PortfolioHolding]:
    """Parse the LLM's JSON reply; tolerate code fences; return [] on failure."""
    text = raw.strip()
    fenced = _FENCE_RE.search(text)
    if fenced:
        text = fenced.group(1).strip()
    try:
        data = _load_json_loose(text)
    except (json.JSONDecodeError, ValueError):
        return []

    holdings: list[PortfolioHolding] = []
    for item in _payload_rows(data):
        if not isinstance(item, dict) or not item.get("ticker"):
            item = _normalize_item(item) if isinstance(item, dict) else item
        else:
            item = _normalize_item(item)
        if not isinstance(item, dict) or not item.get("ticker"):
            continue
        try:
            holdings.append(PortfolioHolding(**item))
        except Exception:  # noqa: BLE001 — skip malformed rows, never fabricate
            continue
    return holdings


def _row_key(row: PortfolioHolding) -> tuple[str, ...]:
    ticker = row.ticker.strip().upper()
    if row.action is not None or row.trade_date is not None:
        return ("trade", ticker, row.trade_date or "")
    return ("holding", ticker)


def _normalized_row(row: PortfolioHolding) -> PortfolioHolding:
    data = row.model_dump()
    data["ticker"] = row.ticker.strip().upper()
    if isinstance(row.name, str):
        data["name"] = row.name.strip() or None
    return PortfolioHolding(**data)


def merge_portfolio_rows(
    existing: list[PortfolioHolding], incoming: list[PortfolioHolding]
) -> list[PortfolioHolding]:
    """Merge extracted rows into the current portfolio.

    Holdings overwrite by ticker. Trade rows overwrite only when ticker and
    trade date match; other dates remain as separate rows.
    """
    merged = [_normalized_row(row) for row in existing]
    index_by_key = {_row_key(row): i for i, row in enumerate(merged)}

    for row in incoming:
        normalized = _normalized_row(row)
        key = _row_key(normalized)
        if key in index_by_key:
            merged[index_by_key[key]] = normalized
        else:
            index_by_key[key] = len(merged)
            merged.append(normalized)
    return merged


def extract_holdings(llm, image_bytes: bytes, mime: str = "image/png") -> list[PortfolioHolding]:
    """Send the screenshot to a vision LLM and parse the structured reply."""
    msg = build_vision_message(image_bytes, mime=mime)
    response = llm.invoke([msg])
    content = response.content
    if isinstance(content, list):  # some providers return content blocks
        content = " ".join(
            b.get("text", "") for b in content if isinstance(b, dict)
        )
    return parse_holdings_json(content)
