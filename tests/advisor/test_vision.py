import base64
import json

from langchain_core.messages import AIMessage

from tradingagents.advisor.vision import (
    build_vision_message,
    extract_holdings,
    merge_portfolio_rows,
    parse_holdings_json,
)


class _FakeVisionLLM:
    def __init__(self, content):
        self._content = content

    def invoke(self, messages):
        return AIMessage(content=self._content)


def test_build_vision_message_has_image_and_text():
    msg = build_vision_message(b"\x89PNG\r\n", mime="image/png")
    blocks = msg.content
    types = {b["type"] for b in blocks}
    assert types == {"image_url", "text"}
    img = next(b for b in blocks if b["type"] == "image_url")
    assert img["image_url"]["url"].startswith("data:image/png;base64,")
    decoded = base64.b64decode(img["image_url"]["url"].split(",", 1)[1])
    assert decoded == b"\x89PNG\r\n"


def test_parse_holdings_json_plain_array():
    raw = json.dumps([{"ticker": "AAPL", "shares": 10, "weight": 40}])
    holdings = parse_holdings_json(raw)
    assert holdings[0].ticker == "AAPL"
    assert holdings[0].shares == 10


def test_parse_holdings_json_fenced_code_block():
    raw = "```json\n[{\"ticker\": \"MSFT\"}]\n```"
    holdings = parse_holdings_json(raw)
    assert holdings[0].ticker == "MSFT"


def test_parse_holdings_json_unparseable_returns_empty():
    assert parse_holdings_json("sorry, I can't read this image") == []


def test_parse_holdings_json_accepts_wrapped_platform_payload():
    raw = json.dumps(
        {
            "holdings": [
                {
                    "证券代码": "159241.SZ",
                    "证券名称": "国防ETF",
                    "持仓数量": "1,200股",
                    "成本价": "1.23元",
                    "市值": "¥1,476.00",
                    "持仓占比": "12.5%",
                }
            ],
            "transactions": [
                {
                    "代码": "AAPL",
                    "操作": "买入",
                    "成交日期": "2026-06-18",
                    "成交数量": "10股",
                }
            ],
        }
    )

    holdings = parse_holdings_json(raw)

    assert [(h.ticker, h.name, h.shares, h.avg_cost, h.market_value, h.weight) for h in holdings[:1]] == [
        ("159241.SZ", "国防ETF", 1200, 1.23, 1476, 12.5),
    ]
    assert (holdings[1].ticker, holdings[1].action, holdings[1].trade_date, holdings[1].shares) == (
        "AAPL",
        "buy",
        "2026-06-18",
        10,
    )


def test_parse_holdings_json_extracts_array_from_surrounding_text():
    raw = '识别结果如下: [{"symbol":"msft","qty":"5 shares","portfolio_weight":"8%"}] 请确认。'

    holdings = parse_holdings_json(raw)

    assert holdings[0].ticker == "MSFT"
    assert holdings[0].shares == 5
    assert holdings[0].weight == 8


def test_parse_holdings_json_accepts_name_only_fund_platform_rows():
    raw = json.dumps(
        [
            {
                "名称": "天弘沪深300ETF联接A",
                "金额": "60,883.33",
                "昨日收益": "+542.30",
                "持有收益": "+6,030.84",
                "持有收益率": "+11.32%",
            },
            {
                "名称": "安信90天滚动持有债券A",
                "金额": "10,264.34",
                "昨日收益": "-2.83",
                "持有收益": "+264.34",
                "持有收益率": "+2.64%",
            },
        ]
    )

    holdings = parse_holdings_json(raw)

    assert [(h.ticker, h.name, h.market_value, h.daily_pnl, h.unrealized_pnl, h.return_rate) for h in holdings] == [
        ("天弘沪深300ETF联接A", "天弘沪深300ETF联接A", 60883.33, 542.3, 6030.84, 11.32),
        ("安信90天滚动持有债券A", "安信90天滚动持有债券A", 10264.34, -2.83, 264.34, 2.64),
    ]


def test_parse_holdings_json_treats_fund_amount_as_market_value_not_shares():
    raw = json.dumps(
        [
            {
                "name": "国泰黄金ETF联接A",
                "amount": "17,523.92",
                "yesterday_income": "-23.23",
                "holding_pnl": "+853.92",
                "holding_return_rate": "+5.12%",
            }
        ]
    )

    holdings = parse_holdings_json(raw)

    assert holdings[0].market_value == 17523.92
    assert holdings[0].shares is None
    assert holdings[0].daily_pnl == -23.23
    assert holdings[0].unrealized_pnl == 853.92
    assert holdings[0].return_rate == 5.12


def test_parse_holdings_json_accepts_combined_broker_columns():
    raw = json.dumps(
        [
            {
                "名称": "航空TH",
                "市值": "67,977.00",
                "盈亏": "-3,652.15",
                "持仓/可用": "58100 / 58100",
                "成本/现价": "1.233 / 1.170",
                "当日盈亏": "174.30",
                "当日盈亏率": "0.257%",
                "仓位": "63.9%",
            }
        ]
    )

    holdings = parse_holdings_json(raw)

    assert len(holdings) == 1
    holding = holdings[0]
    assert holding.ticker == "航空TH"
    assert holding.name == "航空TH"
    assert holding.market_value == 67977
    assert holding.unrealized_pnl == -3652.15
    assert holding.shares == 58100
    assert holding.avg_cost == 1.233
    assert holding.current_price == 1.17
    assert holding.daily_pnl == 174.3
    assert holding.daily_return_rate == 0.257
    assert holding.weight == 63.9


def test_extract_holdings_uses_llm():
    llm = _FakeVisionLLM(json.dumps([{"ticker": "AAPL", "shares": 5}]))
    holdings = extract_holdings(llm, b"img", mime="image/png")
    assert holdings[0].ticker == "AAPL"


def test_merge_portfolio_rows_overwrites_same_holding_and_appends_new_ticker():
    existing = parse_holdings_json(
        json.dumps(
            [
                {"ticker": "AAPL", "shares": 10, "avg_cost": 100},
                {"ticker": "MSFT", "shares": 3},
            ]
        )
    )
    incoming = parse_holdings_json(
        json.dumps(
            [
                {"ticker": "AAPL", "shares": 12, "avg_cost": 101},
                {"ticker": "NVDA", "shares": 2},
            ]
        )
    )

    merged = merge_portfolio_rows(existing, incoming)

    assert [(h.ticker, h.shares) for h in merged] == [
        ("AAPL", 12),
        ("MSFT", 3),
        ("NVDA", 2),
    ]
    assert merged[0].avg_cost == 101


def test_merge_portfolio_rows_overwrites_same_trade_date_and_appends_other_dates():
    existing = parse_holdings_json(
        json.dumps(
            [
                {"ticker": "AAPL", "action": "buy", "trade_date": "2026-06-17", "shares": 10},
                {"ticker": "AAPL", "action": "buy", "trade_date": "2026-06-18", "shares": 5},
            ]
        )
    )
    incoming = parse_holdings_json(
        json.dumps(
            [
                {"ticker": "AAPL", "action": "buy", "trade_date": "2026-06-17", "shares": 12},
                {"ticker": "AAPL", "action": "sell", "trade_date": "2026-06-19", "shares": 2},
            ]
        )
    )

    merged = merge_portfolio_rows(existing, incoming)

    assert [(h.ticker, h.action, h.trade_date, h.shares) for h in merged] == [
        ("AAPL", "buy", "2026-06-17", 12),
        ("AAPL", "buy", "2026-06-18", 5),
        ("AAPL", "sell", "2026-06-19", 2),
    ]


def test_merge_portfolio_rows_overwrites_trade_when_date_matches_even_if_action_differs():
    existing = parse_holdings_json(
        json.dumps(
            [
                {"ticker": "AAPL", "action": "buy", "trade_date": "2026-06-17", "shares": 10},
            ]
        )
    )
    incoming = parse_holdings_json(
        json.dumps(
            [
                {"ticker": "AAPL", "action": "sell", "trade_date": "2026-06-17", "shares": 4},
            ]
        )
    )

    merged = merge_portfolio_rows(existing, incoming)

    assert [(h.ticker, h.action, h.trade_date, h.shares) for h in merged] == [
        ("AAPL", "sell", "2026-06-17", 4),
    ]
