"""Pydantic request/response contracts for the WebUI API."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

AssetType = Literal["stock", "crypto"]
AnalystName = Literal["market", "social", "news", "fundamentals"]
Decision = Literal["Buy", "Overweight", "Hold", "Underweight", "Sell"]
RunStatus = Literal["pending", "running", "completed", "error", "cancelled"]


class AnalysisRequest(BaseModel):
    ticker: str
    trade_date: str
    asset_type: AssetType = "stock"
    analysts: list[AnalystName] = Field(
        default_factory=lambda: ["market", "social", "news", "fundamentals"]
    )
    research_depth: Literal[1, 3, 5] = 3
    output_language: str = "Chinese"
    llm_provider: str | None = None
    deep_think_llm: str | None = None
    quick_think_llm: str | None = None

    @field_validator("analysts")
    @classmethod
    def _at_least_one_analyst(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("at least one analyst is required")
        return v


class EnqueueRequest(BaseModel):
    tickers: list[str]
    trade_date: str
    asset_type: AssetType = "stock"
    analysts: list[AnalystName] = Field(
        default_factory=lambda: ["market", "social", "news", "fundamentals"]
    )
    research_depth: Literal[1, 3, 5] = 3
    output_language: str = "Chinese"
    llm_provider: str | None = None
    deep_think_llm: str | None = None
    quick_think_llm: str | None = None

    @field_validator("tickers")
    @classmethod
    def _at_least_one_ticker(cls, v: list[str]) -> list[str]:
        seen: list[str] = []
        for raw in v:
            t = raw.strip().upper()
            if t and t not in seen:
                seen.append(t)
        if not seen:
            raise ValueError("at least one ticker is required")
        return seen

    @field_validator("analysts")
    @classmethod
    def _at_least_one_analyst(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("at least one analyst is required")
        return v


class QueueItem(BaseModel):
    run_id: str
    ticker: str
    status: RunStatus
    queue_position: int | None
    created_at: str


class QueueState(BaseModel):
    running: QueueItem | None
    pending: list[QueueItem]


class ReorderRequest(BaseModel):
    ordered_run_ids: list[str]


class HistorySummary(BaseModel):
    run_id: str
    ticker: str
    trade_date: str
    decision: Decision | None
    status: RunStatus
    created_at: str


class RunResult(BaseModel):
    run_id: str
    ticker: str
    trade_date: str
    asset_type: str
    decision: Decision | None
    status: RunStatus
    config: dict
    result: dict | None
    created_at: str
    completed_at: str | None


class ConfigOptions(BaseModel):
    analysts: list[dict]
    research_depth: list[dict]
    languages: list[str]
    configured_provider: str | None
    configured_deep_llm: str | None
    configured_quick_llm: str | None
    model_options: dict[str, list[tuple[str, str]]]


ChatRole = Literal["user", "assistant"]
PortfolioSource = Literal["vision", "manual"]


class PortfolioHolding(BaseModel):
    ticker: str
    name: str | None = None
    shares: float | None = None
    avg_cost: float | None = None
    current_price: float | None = None
    market_value: float | None = None
    weight: float | None = None
    unrealized_pnl: float | None = None
    return_rate: float | None = None
    daily_pnl: float | None = None
    daily_return_rate: float | None = None
    action: Literal["buy", "sell"] | None = None
    trade_date: str | None = None


class SessionProfile(BaseModel):
    available_capital: float | None = None
    capital_currency: str = "CNY"
    risk_tolerance: Literal["conservative", "balanced", "aggressive"] | None = None
    max_single_position_pct: float | None = None
    horizon: Literal["short", "medium", "long"] | None = None
    constraints: str | None = None
    confirmed_at: str | None = None


class ChatRequest(BaseModel):
    message: str
    chat_llm: str | None = None


class ChatSessionCreate(BaseModel):
    run_id: str | None = None
    run_ids: list[str] | None = None

    @model_validator(mode="after")
    def _one_report_field(self) -> "ChatSessionCreate":
        if self.run_id is not None and self.run_ids is not None:
            raise ValueError("provide run_id or run_ids, not both")
        return self


class ChatSessionReportsUpdate(BaseModel):
    run_ids: list[str] = Field(default_factory=list)


class ChatSessionUpdate(BaseModel):
    title: str

    @field_validator("title")
    @classmethod
    def _title_not_empty(cls, v: str) -> str:
        title = v.strip()
        if not title:
            raise ValueError("title cannot be empty")
        return title


class ChatSessionBulkDelete(BaseModel):
    session_ids: list[str]

    @field_validator("session_ids")
    @classmethod
    def _at_least_one_session(cls, v: list[str]) -> list[str]:
        ids = [session_id for session_id in v if session_id]
        if not ids:
            raise ValueError("at least one session_id is required")
        return ids


class ChatMessage(BaseModel):
    message_id: str
    session_id: str
    role: ChatRole
    content: str
    tool_calls: list[dict] = Field(default_factory=list)
    created_at: str


class ChatSession(BaseModel):
    session_id: str
    run_id: str | None
    run_ids: list[str] = Field(default_factory=list)
    title: str | None
    created_at: str
    updated_at: str


class PortfolioExtractResponse(BaseModel):
    holdings: list[PortfolioHolding] = Field(default_factory=list)
    source: PortfolioSource
