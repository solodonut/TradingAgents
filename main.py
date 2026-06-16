from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph

# DEFAULT_CONFIG already applies TRADINGAGENTS_* env-var overrides
# (llm_provider, deep_think_llm, quick_think_llm, backend_url, etc.),
# so users can switch models or endpoints purely via .env without
# editing this script. Override individual keys here only when you
# want a hard-coded value that should ignore the environment.
config = DEFAULT_CONFIG.copy()

# Initialize with custom config
ta = TradingAgentsGraph(debug=True, config=config)

# forward propagate
# A股案例 159241.SZ（航空航天ETF天弘），经 akshare_auto_route 自动走 AKShare。
_, decision = ta.propagate("159241.SZ", "2026-06-12")
print(decision)

# Memorize mistakes and reflect
# ta.reflect_and_remember(1000) # parameter is the position returns
