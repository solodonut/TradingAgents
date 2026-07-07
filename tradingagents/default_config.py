import os

_TRADINGAGENTS_HOME = os.path.join(os.path.expanduser("~"), ".tradingagents")

# Single source of truth for env-var → config-key overrides. To expose
# a new config key for environment-based override, add a row here — no
# entry-point script changes required. Coercion is driven by the type
# of the existing default, so users can keep writing plain strings in
# their .env file.
_ENV_OVERRIDES = {
    "TRADINGAGENTS_LLM_PROVIDER":         "llm_provider",
    "TRADINGAGENTS_DEEP_THINK_LLM":       "deep_think_llm",
    "TRADINGAGENTS_QUICK_THINK_LLM":      "quick_think_llm",
    "TRADINGAGENTS_LLM_BACKEND_URL":      "backend_url",
    "TRADINGAGENTS_OUTPUT_LANGUAGE":      "output_language",
    "TRADINGAGENTS_MAX_DEBATE_ROUNDS":    "max_debate_rounds",
    "TRADINGAGENTS_MAX_RISK_ROUNDS":      "max_risk_discuss_rounds",
    "TRADINGAGENTS_CHECKPOINT_ENABLED":   "checkpoint_enabled",
    "TRADINGAGENTS_BENCHMARK_TICKER":     "benchmark_ticker",
    "TRADINGAGENTS_TEMPERATURE":          "temperature",
    "TRADINGAGENTS_DOMESTIC_CHINA_ONLY":  "domestic_china_only",
    "TRADINGAGENTS_LLM_MAX_RETRIES":      "llm_max_retries",
    "TRADINGAGENTS_LLM_REQUEST_TIMEOUT":  "llm_request_timeout",
    "TRADINGAGENTS_REPORT_VALIDATION_ENABLED": "report_validation_enabled",
    "TRADINGAGENTS_LOG_ENABLED":          "log_enabled",
    "TRADINGAGENTS_LOG_DIR":              "log_dir",
    "TRADINGAGENTS_LOG_TRUNCATE_CHARS":   "log_truncate_chars",
}


def _coerce(value: str, reference):
    """Coerce env-var string to the type of the existing default value."""
    if isinstance(reference, bool):
        return value.strip().lower() in ("true", "1", "yes", "on")
    if isinstance(reference, int) and not isinstance(reference, bool):
        return int(value)
    if isinstance(reference, float):
        return float(value)
    return value


def _apply_env_overrides(config: dict) -> dict:
    """Apply TRADINGAGENTS_* env vars to the config dict in-place."""
    for env_var, key in _ENV_OVERRIDES.items():
        raw = os.environ.get(env_var)
        if raw is None or raw == "":
            continue
        config[key] = _coerce(raw, config.get(key))
    return config


DEFAULT_CONFIG = _apply_env_overrides({
    "project_dir": os.path.abspath(os.path.join(os.path.dirname(__file__), ".")),
    "results_dir": os.getenv("TRADINGAGENTS_RESULTS_DIR", os.path.join(_TRADINGAGENTS_HOME, "logs")),
    "data_cache_dir": os.getenv("TRADINGAGENTS_CACHE_DIR", os.path.join(_TRADINGAGENTS_HOME, "cache")),
    "memory_log_path": os.getenv("TRADINGAGENTS_MEMORY_LOG_PATH", os.path.join(_TRADINGAGENTS_HOME, "memory", "trading_memory.md")),
    # Optional cap on the number of resolved memory log entries. When set,
    # the oldest resolved entries are pruned once this limit is exceeded.
    # Pending entries are never pruned. None disables rotation entirely.
    "memory_log_max_entries": None,
    # Detailed per-run structured logging (JSONL). One file per analysis.
    # log_dir defaults to ~/.tradingagents/run_logs/ (NOT results_dir's logs/).
    "log_enabled": True,
    "log_dir": os.getenv("TRADINGAGENTS_LOG_DIR", os.path.join(_TRADINGAGENTS_HOME, "run_logs")),
    "log_truncate_chars": 8000,
    # LLM settings
    "llm_provider": "ibm_ica",
    "deep_think_llm": "claude-opus-4-8",
    "quick_think_llm": "claude-haiku-4-5",
    # When None, each provider's client falls back to its own default endpoint
    # (api.openai.com for OpenAI, generativelanguage.googleapis.com for Gemini, ...).
    # The CLI overrides this per provider when the user picks one. Keeping a
    # provider-specific URL here would leak (e.g. OpenAI's /v1 was previously
    # being forwarded to Gemini, producing malformed request URLs).
    "backend_url": None,
    # Provider-specific thinking configuration
    "google_thinking_level": None,      # "high", "minimal", etc.
    "openai_reasoning_effort": None,    # "medium", "high", "low"
    "anthropic_effort": None,           # "high", "medium", "low"
    # Sampling temperature, forwarded to every provider when set. None leaves
    # each provider at its own default. Lower values reduce run-to-run
    # variation on models that honor it; reasoning models largely ignore it
    # and no setting makes LLM output bit-identical across runs (see README).
    "temperature": None,
    # Transient-failure resilience for LLM calls. Provider gateways (incl. the
    # IBM ICA / Cloudflare front) intermittently return 5xx/429; the underlying
    # SDK retries 408/409/429/>=500 with exponential backoff + jitter, but its
    # default budget (2) is too small to ride out a multi-second gateway blip,
    # so a single 502 in any node (e.g. a researcher's llm.invoke) crashes the
    # whole multi-agent run. Forwarded to every provider client as max_retries.
    # Override with TRADINGAGENTS_LLM_MAX_RETRIES.
    "llm_max_retries": 6,
    # Per-request timeout (seconds) forwarded to every provider client. Must be
    # non-None: langchain_anthropic treats default_request_timeout=None as a
    # *meaningful* value and hands the httpx client timeout=None (wait forever),
    # bypassing the Anthropic SDK's own 600s default. A gateway that accepts the
    # request but never sends a response body then hangs the call indefinitely,
    # and max_retries can't help because no APITimeoutError is ever raised. A
    # finite default bounds the hang so the retry budget (and ultimately a run
    # failure) can kick in. Override with TRADINGAGENTS_LLM_REQUEST_TIMEOUT.
    "llm_request_timeout": 300,
    # Checkpoint/resume: when True, LangGraph saves state after each node
    # so a crashed run can resume from the last successful step.
    "checkpoint_enabled": False,
    # Post-decision report validation: when True, a final graph node fact-checks
    # every report's instrument name and verifiable market numbers against the
    # resolved identity + verified snapshot, auto-correcting mismatches and
    # writing a summary to ``validation_report``. Override with
    # TRADINGAGENTS_REPORT_VALIDATION_ENABLED.
    "report_validation_enabled": True,
    # Output language for analyst reports and final decision
    # Internal agent debate stays in English for reasoning quality
    "output_language": "Chinese",
    # This deployment focuses on mainland China stocks and ETFs. Keep the
    # default data path domestic-first and do not expose overseas-only sources
    # such as Yahoo/FRED/Polymarket/StockTwits/Reddit unless explicitly
    # re-enabled by configuration.
    "domestic_china_only": True,
    # Debate and discussion settings
    "max_debate_rounds": 1,
    "max_risk_discuss_rounds": 1,
    "max_recur_limit": 100,
    "analyst_concurrency_limit": 1,
    # News / data fetching parameters
    # Increase for longer lookback strategies or to broaden macro coverage;
    # decrease to reduce token usage in agent prompts.
    "news_article_limit": 20,             # max articles per ticker (ticker-news)
    "global_news_article_limit": 10,      # max articles for global/macro news
    "global_news_lookback_days": 7,       # macro news lookback window
    # Search queries used by get_global_news for macro headlines. Extend or
    # replace to broaden geographic / sector coverage.
    "global_news_queries": [
        "中国人民银行 利率 LPR 流动性",
        "A股 上证 深证 沪深300 市场行情",
        "中国 GDP CPI PMI 经济数据 政策",
        "地缘政治 中美 贸易 关税 制裁",
        "原油 大宗商品 新能源 供应链",
    ],
    # Tushare 快讯 news() 的数据源列表(单次调用只能传一个 src,逐源合并)。
    # 可选:sina / wallstreetcn / 10jqka / eastmoney / yuncaijing 等。
    "tushare_news_flash_sources": ["sina", "wallstreetcn"],
    # Data vendor configuration
    # Category-level configuration (default for all tools in category).
    # The configured value is the exact vendor chain — requests are NOT silently
    # routed to vendors you didn't choose. For ordered fallback, list several,
    # e.g. "yfinance,alpha_vantage". "default" uses all available vendors.
    "data_vendors": {
        "core_stock_apis": "tushare,akshare",        # Options: alpha_vantage, yfinance, tushare, akshare
        "technical_indicators": "tushare,akshare",   # Options: alpha_vantage, yfinance, tushare, akshare
        "fundamental_data": "tushare,akshare",       # Options: alpha_vantage, yfinance, tushare, akshare
        "news_data": "akshare,longbridge",           # Options: alpha_vantage, yfinance, longbridge, akshare
        "macro_data": "disabled",            # Options: fred, disabled
        "prediction_markets": "disabled",    # Options: polymarket, disabled
    },
    # A-share auto-routing. When True, mainland A-share tickers (600519,
    # 600519.SS, sh600519, ...) are served by AKShare first for legacy
    # Yahoo/Alpha Vantage chains because those sources barely cover Chinese
    # financial statements. Explicit Tushare chains keep their configured
    # order, so the default "tushare,akshare" still tries Tushare before
    # falling back to AKShare. Non-A-share tickers are unaffected. Set False
    # to honor data_vendors for every market.
    "akshare_auto_route": True,
    # Tool-level configuration (takes precedence over category-level)
    "tool_vendors": {
        "get_news": "tushare,akshare,eastmoney",
        "get_global_news": "tushare,yfinance",
        "get_etf_profile": "akshare,tushare,tdx,longbridge",
    },
    # Benchmark for alpha calculation in the reflection layer.
    # ``benchmark_ticker`` (when set) overrides the suffix map for all
    # tickers; leave it None to use ``benchmark_map`` for auto-detection
    # based on the ticker's exchange suffix. SPY remains the US default
    # so the reflection label keeps reading "Alpha vs SPY" for US tickers
    # while non-US tickers get their regional index automatically.
    "benchmark_ticker": "399001.SZ",
    "benchmark_map": {
        ".NS":  "^NSEI",       # NSE India (Nifty 50)
        ".BO":  "^BSESN",      # BSE India (Sensex)
        ".T":   "^N225",       # Tokyo (Nikkei 225)
        ".HK":  "^HSI",        # Hong Kong (Hang Seng)
        ".L":   "^FTSE",       # London (FTSE 100)
        ".TO":  "^GSPTSE",     # Toronto (TSX Composite)
        ".AX":  "^AXJO",       # Australia (ASX 200)
        ".SS":  "000001.SS",   # Shanghai (SSE Composite)
        ".SZ":  "399001.SZ",   # Shenzhen (SZSE Component)
        "":     "SPY",         # default for US-listed tickers (no suffix)
    },
})
