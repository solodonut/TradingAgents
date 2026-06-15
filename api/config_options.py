"""Assembles the option set shown in the frontend config card."""

from api.schemas import ConfigOptions
from tradingagents.default_config import DEFAULT_CONFIG

_ANALYSTS = [
    {"value": "market", "label": "市场分析师"},
    {"value": "social", "label": "情绪分析师"},
    {"value": "news", "label": "新闻分析师"},
    {"value": "fundamentals", "label": "基本面分析师"},
]

_DEPTH = [
    {"value": 1, "label": "浅 (1 轮)"},
    {"value": 3, "label": "中 (3 轮)"},
    {"value": 5, "label": "深 (5 轮)"},
]

_LANGUAGES = [
    "Chinese",
    "English",
    "Japanese",
    "Korean",
    "Spanish",
    "Portuguese",
    "French",
    "German",
    "Russian",
    "Arabic",
    "Hindi",
]


def build_config_options() -> ConfigOptions:
    return ConfigOptions(
        analysts=_ANALYSTS,
        research_depth=_DEPTH,
        languages=_LANGUAGES,
        configured_provider=DEFAULT_CONFIG.get("llm_provider"),
        configured_deep_llm=DEFAULT_CONFIG.get("deep_think_llm"),
        configured_quick_llm=DEFAULT_CONFIG.get("quick_think_llm"),
    )
