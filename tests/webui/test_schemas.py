import pytest
from pydantic import ValidationError

from api.schemas import AnalysisRequest


def test_analysis_request_defaults():
    req = AnalysisRequest(ticker="NVDA", trade_date="2024-05-10")
    assert req.asset_type == "stock"
    assert req.analysts == ["market", "social", "news", "fundamentals"]
    assert req.research_depth == 3
    assert req.output_language == "Chinese"
    assert req.llm_provider is None


def test_analysis_request_rejects_empty_analysts():
    with pytest.raises(ValidationError):
        AnalysisRequest(ticker="NVDA", trade_date="2024-05-10", analysts=[])


def test_research_depth_must_be_allowed_value():
    with pytest.raises(ValidationError):
        AnalysisRequest(ticker="NVDA", trade_date="2024-05-10", research_depth=2)
