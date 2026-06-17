"""Pydantic request/response contracts for the WebUI API."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

AssetType = Literal["stock", "crypto"]
AnalystName = Literal["market", "social", "news", "fundamentals"]
Decision = Literal["Buy", "Overweight", "Hold", "Underweight", "Sell"]
RunStatus = Literal["running", "completed", "error", "cancelled"]


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


ChatRole = Literal["user", "assistant"]
PortfolioSource = Literal["vision", "manual"]


class PortfolioHolding(BaseModel):
    ticker: str
    name: str | None = None
    shares: float | None = None
    avg_cost: float | None = None
    market_value: float | None = None
    weight: float | None = None
    action: Literal["buy", "sell"] | None = None
    trade_date: str | None = None


class ChatRequest(BaseModel):
    message: str


class ChatSessionCreate(BaseModel):
    run_id: str | None = None


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
    title: str | None
    created_at: str
    updated_at: str


class PortfolioExtractResponse(BaseModel):
    holdings: list[PortfolioHolding] = Field(default_factory=list)
    source: PortfolioSource
