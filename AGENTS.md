# AGENTS.md

TradingAgents: multi-agent LLM trading framework built on **LangGraph**. Python core
package + Typer CLI + FastAPI backend (`api/`) + Next.js frontend (`webui/`).

## Setup & commands

- Requires **Python >= 3.10** (uses `X | None` union syntax; fails on 3.9). The
  system `python` may be 3.9 — use a 3.10+ venv/conda env.
- Dependency lockfile is `uv.lock` (use `uv`). `requirements.txt` is just `.`
  (installs this package); the real dependency list lives in `pyproject.toml`.
- Install for development: `pip install -e ".[dev]"` (adds ruff, pytest, httpx).
  Optional extras: `.[bedrock]` for AWS Bedrock.
- Lint: `ruff check .` — config in `pyproject.toml`. Line length 100 but **E501 is
  ignored** (formatter owns layout); whole-repo `ruff format` is intentionally NOT
  adopted yet (avoids mass merge conflicts). `**/__init__.py` ignores F401 (re-exports).
- Run CLI: `tradingagents` or `python -m cli.main`.
- Run a single analysis from code: `python main.py` (uses `DEFAULT_CONFIG`).

## Testing

- Run all: `pytest`. There is **no CI workflow and no pre-commit** — run lint/tests manually.
- Markers (`--strict-markers` is on, so unknown markers error):
  - `unit` — mocked, no network, no real keys (the vast majority).
  - `smoke` — import/route-registration sanity (`tests/webui/test_smoke.py`).
  - `integration` — **only** `tests/test_deepseek_reasoning.py`; needs a real
    `DEEPSEEK_API_KEY`, auto-skips otherwise.
- `pytest` is safe with no API keys: `conftest.py` autouse fixtures inject
  `"placeholder"` keys and reset the global `dataflows` config between tests.
  No external service is required for the default run.
- Single test: `pytest tests/webui/test_runner.py::test_name`. Subset: `pytest -m unit`,
  `pytest tests/webui/`. CI-style: `pytest -m "not integration"`.
- `scripts/smoke_structured_output.py <provider>` exercises real structured-output
  calls against a live provider (costs money; needs that provider's key).

## Architecture

- **Entrypoint**: `TradingAgentsGraph` in `tradingagents/graph/trading_graph.py`.
  `ta.propagate(ticker, date)` returns `(final_state, signal)`. Config flows through
  `DEFAULT_CONFIG` in `tradingagents/default_config.py` (single source of truth).
- **Pipeline** (LangGraph `StateGraph`): 4 analysts (market, sentiment, news,
  fundamentals — each a ReAct tool-call loop, run sequentially by default) →
  bull/bear researcher debate → Research Manager → Trader → 3-way risk debate
  (aggressive/conservative/neutral) → Portfolio Manager → `final_trade_decision`.
- **Package layout** under `tradingagents/`: `agents/` (agent factories, tool
  functions in `agents/utils/`, Pydantic `schemas.py`, state TypedDicts), `graph/`
  (orchestration, checkpoint, reflection, signal extraction), `dataflows/` (data
  vendor abstraction), `llm_clients/` (provider abstraction).
- **Data access**: never call yfinance/AKShare/FRED/etc. directly from agent code.
  All data goes through `dataflows/interface.py::route_to_vendor()`, which returns a
  `NO_DATA_AVAILABLE: ...` sentinel string (never raises) so agents report
  unavailability instead of fabricating values. Add a source by registering it in
  `VENDOR_METHODS`. Vendors: yfinance, Alpha Vantage, AKShare (auto-routed for
  China A-shares `.SS`/`.SZ`), FRED, Polymarket, StockTwits, Reddit.
- **LLM access**: all instantiation goes through `llm_clients/factory.py::create_llm_client()`.
  `llm_clients/model_catalog.py` (`MODEL_OPTIONS`) is the single registry for CLI
  dropdowns and model validation — add new providers/models there. `openai_client.py`
  covers all OpenAI-compatible providers (DeepSeek, Qwen, GLM, MiniMax, Groq,
  OpenRouter, Ollama, etc.).

## Key conventions & gotchas

- **Config is a process-level singleton.** `TradingAgentsGraph.__init__` calls
  `dataflows.config.set_config()` which deep-merges; the last call wins globally.
  Tests reset it via the autouse `_isolate_config` fixture.
- **Memory / learning**: `agents/utils/memory.py` appends each decision to
  `~/.tradingagents/memory/trading_memory.md` as `pending`, then on the *next* run for
  the same ticker fetches realized returns, runs an LLM reflection, and injects past
  context into the Portfolio Manager prompt. Override path with `TRADINGAGENTS_MEMORY_LOG_PATH`.
- **Checkpoint resume** is opt-in (`--checkpoint` / `checkpoint_enabled`). SQLite at
  `~/.tradingagents/cache/checkpoints/<TICKER>.db`.
- **Anti-hallucination**: instrument identity is resolved once from yfinance and injected
  into every analyst prompt; market price claims are grounded via `get_verified_market_snapshot`.
- **Structured output**: Research Manager, Trader, Portfolio Manager, Sentiment Analyst use
  `bind_structured()` + `invoke_structured_or_freetext()` (native structured output with
  freetext fallback). Schemas in `tradingagents/agents/schemas.py`.
- **Env config**: any `TRADINGAGENTS_*` var overrides the matching `DEFAULT_CONFIG` key with
  type-aware coercion (see `.env.example`). LLM provider keys also live in `.env`.
  Azure uses `.env.enterprise`.
- **Non-deterministic by design** — same ticker+date can differ run to run (LLM sampling +
  live news/social data). Not a bug. See README "Reproducibility".
- Commit style: Conventional Commits (`feat(scope):`, `test(scope):`). Maintain `CHANGELOG.md`
  (Keep a Changelog format, SemVer; version in `pyproject.toml`).

## WebUI (`api/` + `webui/`)

- API dev: `scripts/dev.sh` (starts API+web with the correct interpreters), or manually
  `.venv/bin/python -m uvicorn api.main:app --reload --port 8000`. Use the `.venv` binary
  explicitly — a bare `uvicorn`/`python3` on PATH may resolve to an unrelated Python (e.g. a
  Framework/conda env with NumPy-1.x wheels that crash against this project's NumPy 2.x).
  Frontend needs Node >=20.9 (Next.js 16). Entrypoint `api/main.py`; routes in
  `api/routes/`; LangGraph→SSE bridge in `api/runner.py`; SQLite history in `api/store.py`
  (`~/.tradingagents/webui.db`). CORS allows `localhost:3000` only. Single-user invariant:
  one run at a time (409 if busy).
- Tests inject a fake graph via `app.state.graph_factory`; no running server or real graph needed.
- Frontend: `cd webui && npm run dev` (Next.js 16, React 19, Tailwind 4). **`webui/AGENTS.md`
  warns this Next.js version has breaking changes vs training data — read
  `node_modules/next/dist/docs/` before writing frontend code.**

<!-- KARPATHY-GUIDELINES:START -->

## Coding Guidelines

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

### 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

### 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.
<!-- KARPATHY-GUIDELINES:END -->
