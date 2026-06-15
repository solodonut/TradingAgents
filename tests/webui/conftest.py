"""WebUI-specific test configuration."""
import sys
from unittest.mock import MagicMock

if "tradingagents" not in sys.modules:
    sys.modules["tradingagents"] = MagicMock()
    sys.modules["tradingagents.dataflows"] = MagicMock()
    sys.modules["tradingagents.dataflows.config"] = MagicMock()
    sys.modules["tradingagents.dataflows.config"]._config = {}
    sys.modules["tradingagents.default_config"] = MagicMock()
    sys.modules["tradingagents.default_config"].DEFAULT_CONFIG = {}


import pytest


@pytest.fixture(autouse=True)
def _isolate_config():
    yield
