"""Pydantic request/response contracts for the WebUI API."""

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

AssetType = Literal["stock", "crypto"]
AnalystName = Literal["market", "social", "news", "fundamentals"]
Decision = Literal["Buy", "Overweight", "Hold", "Underweight", "Sell"]
RunStatus = Literal["running", "completed", "error"]


class AnalysisRequest(BaseModel):
    ticker: str
    trade_date: str
    asset_type: AssetType = "stock"
    analysts: list[AnalystName] = Field(
        default_factory=lambda: ["market", "social", "news", "fundamentals"]
    )
    research_depth: Literal[1, 3, 5] = 3
    output_language: str = "Chinese"
    llm_provider: Optional[str] = None
    deep_think_llm: Optional[str] = None
    quick_think_llm: Optional[str] = None

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
    decision: Optional[Decision]
    status: RunStatus
    created_at: str


class RunResult(BaseModel):
    run_id: str
    ticker: str
    trade_date: str
    asset_type: str
    decision: Optional[Decision]
    status: RunStatus
    config: dict
    result: Optional[dict]
    created_at: str
    completed_at: Optional[str]


class ConfigOptions(BaseModel):
    analysts: list[dict]
    research_depth: list[dict]
    languages: list[str]
    configured_provider: Optional[str]
    configured_deep_llm: Optional[str]
    configured_quick_llm: Optional[str]
