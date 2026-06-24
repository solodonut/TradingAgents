# IBM ICA Anthropic API Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route the existing Claude-only `ibm_ica` provider through Anthropic Messages at `https://api.nextgen-beta.ica.ibm.com/ica/v1/messages` with `IBM_ICA_API_KEY` sent as `x-api-key`.

**Architecture:** Reclassify `ibm_ica` as a native provider in the central LLM factory and implement it as an `AnthropicClient` specialization. Remove the obsolete OpenAI-compatible registration and error adapter, restrict health-check candidates to Claude, and keep every business entry point unchanged so TradingAgents and Chat inherit the migration through the factory.

**Tech Stack:** Python 3.10+, LangChain Anthropic, Anthropic Python SDK, httpx MockTransport, pytest, Ruff.

---

## File Map

| File | Responsibility in this change |
|---|---|
| `tradingagents/llm_clients/anthropic_client.py` | Add ICA Base URL/key resolution on top of `NormalizedChatAnthropic` |
| `tradingagents/llm_clients/factory.py` | Route `ibm_ica` to the Anthropic-backed client |
| `tradingagents/llm_clients/openai_client.py` | Remove ICA from the OpenAI-compatible registry and delete obsolete Chat Completions error handling |
| `tradingagents/llm_clients/model_catalog.py` | Keep only Claude models in ICA quick/deep candidates |
| `cli/utils.py` | Change the CLI ICA Base URL to `/ica` |
| `tests/test_ibm_ica_anthropic.py` | Verify real wire path and headers with an intercepted HTTP request |
| `tests/test_provider_registry.py` | Verify ICA is not OpenAI-compatible |
| `tests/test_openai_compatible_provider.py` | Remove obsolete ICA Chat Completions error tests |
| `tests/test_model_health_check.py` | Update Claude-only candidate expectations |
| `tests/test_model_validation.py` | Verify ICA custom Claude IDs remain accepted |
| `tests/test_ollama_base_url.py` | Verify the CLI ICA URL independently of Ollama behavior |
| `.env.example` | Document the new Anthropic Base URL |
| `README.md`, `README_AShare.md`, `docs/llm-api-architecture.md`, `CHANGELOG.md` | Replace obsolete OpenAI-compatible ICA guidance |

### Task 1: Prove the Anthropic wire contract

**Files:**
- Create: `tests/test_ibm_ica_anthropic.py`
- Modify: `tradingagents/llm_clients/anthropic_client.py`
- Modify: `tradingagents/llm_clients/factory.py`

- [ ] **Step 1: Write the failing factory and HTTP contract tests**

Create `tests/test_ibm_ica_anthropic.py` with tests equivalent to:

```python
import json

import httpx
import pytest

from tradingagents.llm_clients.anthropic_client import IbmIcaAnthropicClient
from tradingagents.llm_clients.factory import create_llm_client


def _message_response(model: str) -> dict:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [{"type": "text", "text": "ok"}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }


@pytest.mark.unit
def test_factory_routes_ibm_ica_to_anthropic_client(monkeypatch):
    monkeypatch.setenv("IBM_ICA_API_KEY", "test-ica-key")
    client = create_llm_client("ibm_ica", "claude-haiku-4-5")
    assert isinstance(client, IbmIcaAnthropicClient)


@pytest.mark.unit
def test_ibm_ica_sends_anthropic_messages_request(monkeypatch):
    monkeypatch.setenv("IBM_ICA_API_KEY", "test-ica-key")
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_message_response("claude-haiku-4-5"))

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    llm = create_llm_client(
        "ibm_ica",
        "claude-haiku-4-5",
        http_client=http_client,
    ).get_llm()

    assert llm.invoke("ping").content == "ok"
    request = captured["request"]
    assert str(request.url) == "https://api.nextgen-beta.ica.ibm.com/ica/v1/messages"
    assert request.headers["x-api-key"] == "test-ica-key"
    assert request.headers["anthropic-version"] == "2023-06-01"
    assert "authorization" not in request.headers
    assert captured["body"]["model"] == "claude-haiku-4-5"
    assert "messages" in captured["body"]


@pytest.mark.unit
def test_ibm_ica_base_url_env_override(monkeypatch):
    monkeypatch.setenv("IBM_ICA_API_KEY", "test-ica-key")
    monkeypatch.setenv("IBM_ICA_BASE_URL", "https://tenant.example/ica")
    llm = create_llm_client("ibm_ica", "claude-haiku-4-5").get_llm()
    assert str(llm.anthropic_api_url) == "https://tenant.example/ica"


@pytest.mark.unit
def test_ibm_ica_explicit_base_url_wins(monkeypatch):
    monkeypatch.setenv("IBM_ICA_API_KEY", "test-ica-key")
    monkeypatch.setenv("IBM_ICA_BASE_URL", "https://env.example/ica")
    llm = create_llm_client(
        "ibm_ica",
        "claude-haiku-4-5",
        base_url="https://explicit.example/ica",
    ).get_llm()
    assert str(llm.anthropic_api_url) == "https://explicit.example/ica"


@pytest.mark.unit
def test_ibm_ica_does_not_fall_back_to_anthropic_key(monkeypatch):
    monkeypatch.delenv("IBM_ICA_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "wrong-provider-key")
    with pytest.raises(ValueError, match="IBM_ICA_API_KEY"):
        create_llm_client("ibm_ica", "claude-haiku-4-5")
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_ibm_ica_anthropic.py
```

Expected: collection fails because `IbmIcaAnthropicClient` does not exist. This proves the test is exercising the missing transport.

- [ ] **Step 3: Implement the minimal ICA Anthropic client**

In `tradingagents/llm_clients/anthropic_client.py`, import `os`, define the default Base URL, and add:

```python
_IBM_ICA_DEFAULT_BASE_URL = "https://api.nextgen-beta.ica.ibm.com/ica"


class IbmIcaAnthropicClient(AnthropicClient):
    """Claude-only IBM ICA client using the Anthropic Messages API."""

    def __init__(self, model: str, base_url: str | None = None, **kwargs):
        resolved_base_url = (
            base_url
            or os.environ.get("IBM_ICA_BASE_URL")
            or _IBM_ICA_DEFAULT_BASE_URL
        )
        api_key = kwargs.get("api_key") or os.environ.get("IBM_ICA_API_KEY")
        if not api_key:
            raise ValueError(
                "API key for provider 'ibm_ica' is not set. "
                "Please set the IBM_ICA_API_KEY environment variable."
            )
        kwargs["api_key"] = api_key
        super().__init__(model, resolved_base_url, **kwargs)
```

In `tradingagents/llm_clients/factory.py`, add the native branch before importing `openai_client`:

```python
if provider_lower == "ibm_ica":
    from .anthropic_client import IbmIcaAnthropicClient
    return IbmIcaAnthropicClient(model, base_url, **kwargs)
```

- [ ] **Step 4: Run the HTTP contract tests and verify GREEN**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_ibm_ica_anthropic.py
```

Expected: all Task 1 tests pass and the mock transport observes `/ica/v1/messages` with `x-api-key`.

Run the native Anthropic isolation regression:

```bash
.venv/bin/python -m pytest -q tests/test_anthropic_effort.py tests/test_ibm_ica_anthropic.py
```

Expected: native Anthropic effort gating and ICA configuration tests both pass.

- [ ] **Step 5: Commit the native client slice**

```bash
git add tests/test_ibm_ica_anthropic.py \
        tradingagents/llm_clients/anthropic_client.py \
        tradingagents/llm_clients/factory.py
git commit -m "fix(llm): route IBM ICA through Anthropic messages"
```

### Task 2: Remove the obsolete OpenAI ICA path

**Files:**
- Modify: `tests/test_provider_registry.py`
- Modify: `tests/test_openai_compatible_provider.py`
- Modify: `tradingagents/llm_clients/openai_client.py`

- [ ] **Step 1: Write the failing registry expectation**

Add to `tests/test_provider_registry.py`:

```python
@pytest.mark.unit
def test_ibm_ica_is_not_openai_compatible():
    from tradingagents.llm_clients.openai_client import (
        OPENAI_COMPATIBLE_PROVIDERS,
        is_openai_compatible,
    )

    assert "ibm_ica" not in OPENAI_COMPATIBLE_PROVIDERS
    assert is_openai_compatible("ibm_ica") is False
```

- [ ] **Step 2: Run it and verify RED**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_provider_registry.py::test_ibm_ica_is_not_openai_compatible
```

Expected: FAIL because `ibm_ica` is still registered as OpenAI-compatible.

- [ ] **Step 3: Delete obsolete OpenAI-specific production and tests**

From `openai_client.py`, remove:

- `_fetch_ica_models()`.
- `IbmIcaChatOpenAI`.
- The `ibm_ica` `ProviderSpec` entry.

Remove the tests in `tests/test_openai_compatible_provider.py` that instantiate `IbmIcaChatOpenAI` or assert the old Chat Completions error translations. Keep all generic OpenAI-compatible tests unchanged.

- [ ] **Step 4: Run registry and OpenAI-compatible tests**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/test_provider_registry.py \
  tests/test_openai_compatible_provider.py \
  tests/test_ibm_ica_anthropic.py
```

Expected: all tests pass; no test or production symbol references `IbmIcaChatOpenAI`.

- [ ] **Step 5: Commit the obsolete-path removal**

```bash
git add tradingagents/llm_clients/openai_client.py \
        tests/test_provider_registry.py \
        tests/test_openai_compatible_provider.py
git commit -m "refactor(llm): remove ICA chat completions path"
```

### Task 3: Restrict ICA to Claude and align the CLI

**Files:**
- Modify: `tests/test_model_health_check.py`
- Modify: `tests/test_model_validation.py`
- Modify: `tests/test_ollama_base_url.py`
- Modify: `tradingagents/llm_clients/model_catalog.py`
- Modify: `cli/utils.py`

- [ ] **Step 1: Add failing catalog and CLI assertions**

Add a catalog test in `tests/test_model_validation.py`:

```python
@pytest.mark.unit
def test_ibm_ica_catalog_is_claude_only():
    from tradingagents.llm_clients.model_catalog import get_model_options

    values = {
        value
        for mode in ("quick", "deep")
        for _label, value in get_model_options("ibm_ica", mode)
        if value != "custom"
    }
    assert values
    assert all(value.startswith("claude-") for value in values)
```

Add a CLI assertion in `tests/test_ollama_base_url.py`:

```python
@pytest.mark.unit
def test_ibm_ica_cli_uses_anthropic_base_url():
    from cli.utils import provider_default_url

    assert provider_default_url("ibm_ica") == "https://api.nextgen-beta.ica.ibm.com/ica"
```

Update `tests/test_model_health_check.py` expectations to require two quick candidates and three deep candidates, all beginning with `claude-`.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/test_model_validation.py \
  tests/test_model_health_check.py \
  tests/test_ollama_base_url.py
```

Expected: FAIL because GPT, Gemini, and Granite remain in the catalog and the CLI still returns `/ica/v1`.

- [ ] **Step 3: Make the catalog and CLI Claude-only**

Change `_ICA_MODELS` in `model_catalog.py` to:

```python
_ICA_MODELS = {
    "quick": [
        ("Claude 4.5 Haiku - Fast, cheap quick-thinking", "claude-haiku-4-5"),
        ("Claude 4.6 Sonnet - Balanced", "claude-sonnet-4-6"),
        ("Custom model ID", "custom"),
    ],
    "deep": [
        ("Claude 4.8 Opus - Latest flagship, deep reasoning", "claude-opus-4-8"),
        ("Claude 4.7 Opus - Previous flagship", "claude-opus-4-7"),
        ("Claude 4.6 Sonnet - Balanced reasoning", "claude-sonnet-4-6"),
        ("Custom model ID", "custom"),
    ],
}
```

Change the IBM ICA row in `cli/utils.py` to:

```python
("IBM ICA", "ibm_ica", "https://api.nextgen-beta.ica.ibm.com/ica"),
```

- [ ] **Step 4: Run the catalog, health-check, and CLI tests**

Run the Task 3 focused command again.

Expected: all tests pass and health checks probe only the configured Claude model plus Claude catalog candidates.

- [ ] **Step 5: Commit model and CLI alignment**

```bash
git add tradingagents/llm_clients/model_catalog.py cli/utils.py \
        tests/test_model_validation.py tests/test_model_health_check.py \
        tests/test_ollama_base_url.py
git commit -m "fix(llm): restrict IBM ICA to Claude models"
```

### Task 4: Update configuration and documentation

**Files:**
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `README_AShare.md`
- Modify: `docs/llm-api-architecture.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Update configuration examples**

Replace the ICA example with:

```dotenv
# IBM ICA uses Anthropic Messages for Claude models.
#IBM_ICA_BASE_URL=https://api.nextgen-beta.ica.ibm.com/ica
```

Keep `IBM_ICA_API_KEY=` and the default quick/deep model IDs unchanged.

- [ ] **Step 2: Replace obsolete documentation claims**

Across the four Markdown files:

- Describe IBM ICA as Anthropic Messages compatible, not OpenAI compatible.
- Document final URL `/ica/v1/messages`.
- Document `x-api-key: IBM_ICA_API_KEY`.
- List only Claude model candidates.
- Remove the CLI/WebUI ICA endpoint discrepancy because both paths now use `/ica`.
- Update startup health-check count from nine requests to five default candidate requests: two quick plus three deep.
- Retain the warning that explicit legacy `/chat-models` URLs must be removed.

- [ ] **Step 3: Scan for stale claims and credentials**

Run:

```bash
rg -n "IBM ICA|ibm_ica|chat-models|chat/completions|GPT-5\.4|Gemini 3\.1|Granite 4" \
  README.md README_AShare.md .env.example docs tradingagents cli tests
```

Expected: `chat-models` and `chat/completions` occur only in migration history or tests explicitly describing the removed path. No current configuration guidance advertises non-Claude ICA models.

Run the credential scanner against changed documentation before staging it. Expected: zero HIGH findings.

- [ ] **Step 4: Commit documentation**

```bash
git add .env.example README.md README_AShare.md \
        docs/llm-api-architecture.md CHANGELOG.md
git commit -m "docs(llm): document ICA Anthropic messages API"
```

### Task 5: End-to-end regression verification

**Files:**
- Modify only files required to fix migration-caused regressions

- [ ] **Step 1: Run focused provider and Agent tests**

```bash
.venv/bin/python -m pytest -q \
  tests/test_ibm_ica_anthropic.py \
  tests/test_provider_registry.py \
  tests/test_openai_compatible_provider.py \
  tests/test_anthropic_effort.py \
  tests/test_model_validation.py \
  tests/test_model_health_check.py \
  tests/test_structured_agents.py \
  tests/advisor/test_vision.py \
  tests/webui/test_routes_chat.py
```

Expected: all focused tests pass without a network request.

- [ ] **Step 2: Run Ruff**

```bash
ruff check .
```

Expected: zero lint errors.

- [ ] **Step 3: Run the full non-integration suite**

```bash
.venv/bin/python -m pytest -m "not integration"
```

Expected: all tests pass; the real DeepSeek integration test is deselected or skipped.

- [ ] **Step 4: Verify the resolved client without sending a request**

```bash
.venv/bin/python - <<'PY'
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.llm_clients import create_llm_client

client = create_llm_client(
    DEFAULT_CONFIG["llm_provider"],
    DEFAULT_CONFIG["quick_think_llm"],
    DEFAULT_CONFIG.get("backend_url"),
)
llm = client.get_llm()
print(type(client).__name__)
print(type(llm).__name__)
print(llm.model_name)
print(llm.anthropic_api_url)
PY
```

Expected output identifies `IbmIcaAnthropicClient`, `NormalizedChatAnthropic`, `claude-haiku-4-5`, and `https://api.nextgen-beta.ica.ibm.com/ica`. Do not print the API key or the entire client object.

- [ ] **Step 5: Review the final diff**

```bash
git status --short
git diff HEAD~4 --stat
git diff HEAD~4 --check
```

Expected: only ICA transport, tests, model catalog, CLI URL, configuration, and documentation changes appear.

Do not run a live ICA smoke automatically. If the user explicitly requests it, send one minimal `ping` request through the migrated client and report the model, endpoint, HTTP result, and latency without exposing headers or credentials.
