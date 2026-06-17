"""Extract structured portfolio holdings from an uploaded screenshot."""

import base64
import json
import re

from langchain_core.messages import HumanMessage

from api.schemas import PortfolioHolding

_EXTRACT_INSTRUCTION = (
    "这是一张投资组合 / 交易记录截图。请提取其中的持仓与交易记录,"
    "输出一个 JSON 数组,每个元素包含可识别到的字段:"
    "ticker(代码)、name(名称)、shares(股数)、avg_cost(成本价)、"
    "market_value(市值)、weight(占比百分比数值)、action(buy/sell,若为交易记录)、"
    "trade_date(交易日期)。无法识别的字段省略或设为 null。"
    "只输出 JSON 数组,不要其它文字。若无法识别任何持仓,输出空数组 []。"
)

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def build_vision_message(image_bytes: bytes, mime: str = "image/png") -> HumanMessage:
    b64 = base64.b64encode(image_bytes).decode()
    return HumanMessage(
        content=[
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            {"type": "text", "text": _EXTRACT_INSTRUCTION},
        ]
    )


def parse_holdings_json(raw: str) -> list[PortfolioHolding]:
    """Parse the LLM's JSON reply; tolerate code fences; return [] on failure."""
    text = raw.strip()
    fenced = _FENCE_RE.search(text)
    if fenced:
        text = fenced.group(1).strip()
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    holdings: list[PortfolioHolding] = []
    for item in data:
        if not isinstance(item, dict) or not item.get("ticker"):
            continue
        try:
            holdings.append(PortfolioHolding(**item))
        except Exception:  # noqa: BLE001 — skip malformed rows, never fabricate
            continue
    return holdings


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
