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


def test_enqueue_request_normalizes_tickers():
    from api.schemas import EnqueueRequest

    req = EnqueueRequest(tickers=[" nvda ", "AAPL", "nvda", ""], trade_date="2024-05-10")
    assert req.tickers == ["NVDA", "AAPL"]


def test_enqueue_request_rejects_empty_tickers():
    import pytest
    from pydantic import ValidationError

    from api.schemas import EnqueueRequest

    with pytest.raises(ValidationError):
        EnqueueRequest(tickers=[" ", ""], trade_date="2024-05-10")


def test_queue_state_shape():
    from api.schemas import QueueItem, QueueState

    item = QueueItem(
        run_id="r1", ticker="NVDA", status="pending",
        queue_position=1, created_at="2024-05-10T00:00:00+00:00",
    )
    state = QueueState(running=None, pending=[item])
    assert state.pending[0].ticker == "NVDA"
    assert state.running is None
