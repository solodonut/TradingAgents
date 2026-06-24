# IBM ICA Anthropic API Migration Design

Date: 2026-06-24
Status: Approved design, pending implementation

## Summary

Migrate the existing `ibm_ica` provider from OpenAI-compatible Chat Completions to the native Anthropic Messages API. Keep the public provider name and environment variable stable, restrict IBM ICA to Claude models, and route every IBM ICA-backed feature through one Anthropic client implementation.

## Problem

The current implementation registers `ibm_ica` in `OPENAI_COMPATIBLE_PROVIDERS`. LangChain therefore sends OpenAI Chat Completions requests to an ICA `/chat/completions` endpoint. IBM ICA no longer exposes Anthropic models through that compatibility path, so the configured Claude quick and deep models cannot be reached reliably.

ICA now expects Anthropic Messages API requests with:

```text
Base URL: https://api.nextgen-beta.ica.ibm.com/ica
Endpoint: POST /v1/messages
Auth: x-api-key: <IBM_ICA_API_KEY>
```

The root cause is transport classification, not the configured Claude model IDs: `ibm_ica` is constructed as `ChatOpenAI` when it must be constructed as `ChatAnthropic`.

## Goals

- Preserve the provider key `ibm_ica`.
- Preserve `IBM_ICA_API_KEY` as the only required ICA credential.
- Use Anthropic Messages request and response formats for every ICA model call.
- Default to `https://api.nextgen-beta.ica.ibm.com/ica` and allow endpoint overrides.
- Restrict the ICA model catalog and health-check fallbacks to Claude models.
- Apply the migration uniformly to TradingAgents, Advisor Chat, screenshot extraction, report export, deferred reflection, and startup health checks.
- Preserve structured output and tool calling through LangChain's Anthropic integration.
- Provide clear errors for missing credentials and incompatible configuration.

## Non-goals

- Do not change native provider `anthropic` or its `ANTHROPIC_API_KEY` behavior.
- Do not change OpenAI, Google, Bedrock, or other provider implementations.
- Do not preserve GPT, Gemini, or Granite access under `ibm_ica`.
- Do not introduce automatic model-family transport switching.
- Do not change Agent prompts, graph topology, or quick/deep role assignments.
- Do not add true token streaming as part of this migration.

## Considered Approaches

### 1. Replace the existing `ibm_ica` transport

Create an ICA-specific Anthropic client and route the existing provider key to it.

Advantages:

- Matches the requested one-provider, Claude-only behavior.
- Leaves existing application configuration unchanged.
- Gives every entry point the same transport through the existing factory.
- Removes the obsolete OpenAI compatibility path instead of keeping dead behavior.

Trade-off:

- Existing users who selected non-Claude ICA models must switch providers.

This is the selected approach.

### 2. Add `ibm_ica_anthropic` and preserve `ibm_ica`

Advantages:

- Avoids changing the behavior of an existing provider key.

Trade-offs:

- Leaves two ICA configurations and an unusable legacy default.
- Requires users to edit existing environment configuration.
- Conflicts with the requirement to move IBM ICA completely to Anthropic format.

Rejected.

### 3. Select transport from the model family

Advantages:

- Could retain GPT, Gemini, Granite, and Claude behind one provider name.

Trade-offs:

- Introduces model-name routing and two wire protocols under one provider.
- Makes error handling, health checks, and custom model IDs ambiguous.
- Conflicts with the Claude-only requirement.

Rejected.

## Architecture

### Provider factory

`create_llm_client()` will treat `ibm_ica` as a native branch before consulting the OpenAI-compatible registry:

```text
create_llm_client(provider="ibm_ica")
  → IbmIcaAnthropicClient
  → NormalizedChatAnthropic
  → Anthropic SDK
  → POST https://api.nextgen-beta.ica.ibm.com/ica/v1/messages
```

`ibm_ica` will be removed from `OPENAI_COMPATIBLE_PROVIDERS`. This prevents accidental Chat Completions construction and makes `is_openai_compatible("ibm_ica")` false.

### ICA client

Add `IbmIcaAnthropicClient` alongside `AnthropicClient` in `anthropic_client.py`. It will reuse `NormalizedChatAnthropic` and the native Anthropic structured-output/tool-calling behavior.

The client resolves configuration as follows:

```text
Base URL:
  explicit base_url / TRADINGAGENTS_LLM_BACKEND_URL
  → IBM_ICA_BASE_URL
  → https://api.nextgen-beta.ica.ibm.com/ica

API key:
  IBM_ICA_API_KEY
```

The key is passed to `ChatAnthropic(api_key=...)`. The Anthropic SDK emits it as `x-api-key` and supplies the standard `anthropic-version` header. The application will not copy the ICA key into `ANTHROPIC_API_KEY`.

If `IBM_ICA_API_KEY` is missing, client construction raises a provider-specific `ValueError` naming that environment variable before making a network request.

### Model catalog

Keep bare ICA model IDs. The quick and deep catalogs become Claude-only:

```text
quick:
  claude-haiku-4-5
  claude-sonnet-4-6

deep:
  claude-opus-4-8
  claude-opus-4-7
  claude-sonnet-4-6
```

Keep `Custom model ID` in both menus so a newly released or tenant-specific Claude ID can be used before the catalog is updated.

`ibm_ica` remains an any-model validator provider because local validation cannot know a tenant's complete Claude catalog. Documentation and menu candidates define the supported family; the ICA endpoint remains the final authority for custom IDs.

### Entry points

No business entry point should instantiate the ICA client directly.

- `TradingAgentsGraph` continues creating quick/deep clients through `create_llm_client()`.
- `real_chat_llm_factory()` continues using the configured quick model through the same factory.
- Advisor tools, report export, and vision extraction continue reusing the Chat model.
- Startup health checks continue calling the factory, but probe only Claude candidates.
- CLI continues using provider key `ibm_ica`, with its menu Base URL changed to `/ica`.

This keeps the migration inside the provider layer and catalog rather than duplicating Anthropic handling throughout the application.

## Request Behavior

Plain-text invocation uses the native Messages body:

```json
{
  "model": "claude-haiku-4-5",
  "max_tokens": 64000,
  "system": "...",
  "messages": [
    {"role": "user", "content": "..."}
  ]
}
```

The exact `max_tokens` value remains controlled by `ChatAnthropic` defaults or existing configuration; this migration does not add a new project-level token limit.

Tool-enabled Agents use Anthropic `tools` and `tool_use` blocks through `bind_tools()`. Structured Agents use `with_structured_output()` through the existing `structured.py` wrapper. The wrapper retains its current fallback: if a structured invocation fails, retry once as free text.

Screenshot extraction continues sending an image content block through `ChatAnthropic`. No separate vision provider is introduced.

## Error Handling

Remove the OpenAI-specific `IbmIcaChatOpenAI` behavior, including:

- Parsing `400 {'detail': 'Model not found'}` from Chat Completions.
- Fetching `{openai_base_url}/models` after that error.
- Matching the OpenAI gateway's guardrail `E001` response text.

The Anthropic client will preserve Anthropic SDK errors unless a stable ICA Anthropic error contract is observed and covered by tests. Missing Key and client configuration errors remain explicit local validation errors.

This avoids translating Anthropic failures using response shapes from an obsolete protocol.

## Compatibility and Migration

Existing configuration remains valid when it uses Claude:

```dotenv
TRADINGAGENTS_LLM_PROVIDER=ibm_ica
TRADINGAGENTS_QUICK_THINK_LLM=claude-haiku-4-5
TRADINGAGENTS_DEEP_THINK_LLM=claude-opus-4-8
IBM_ICA_API_KEY=<your-key>
```

Required changes for existing installations:

- Remove a legacy `IBM_ICA_BASE_URL` ending in `/ica/v1/chat-models` or replace it with `https://api.nextgen-beta.ica.ibm.com/ica`.
- Remove a `TRADINGAGENTS_LLM_BACKEND_URL` that points to an ICA Chat Completions route.
- Replace non-Claude `ibm_ica` model IDs with Claude IDs.

No automatic URL rewriting will be added. Silently modifying an explicit endpoint can hide configuration mistakes and make custom tenant URLs unpredictable.

## Files in Scope

Expected production changes:

- `tradingagents/llm_clients/anthropic_client.py`
- `tradingagents/llm_clients/factory.py`
- `tradingagents/llm_clients/openai_client.py`
- `tradingagents/llm_clients/model_catalog.py`
- `cli/utils.py`
- `.env.example`

Expected tests:

- New or updated ICA provider factory/client tests.
- Provider registry tests.
- API key mapping tests where required.
- Model catalog and health-check candidate tests.
- CLI provider endpoint tests.
- Existing structured Agent and Chat tests as regression coverage.

Expected documentation changes:

- `README.md`
- `README_AShare.md`
- `docs/llm-api-architecture.md`
- `CHANGELOG.md`

## Test Strategy

Implementation follows red-green-refactor.

1. Add a failing factory test asserting `ibm_ica` returns `IbmIcaAnthropicClient` and is no longer OpenAI-compatible.
2. Add failing client tests asserting:
   - Default Base URL is exactly `https://api.nextgen-beta.ica.ibm.com/ica`.
   - `IBM_ICA_BASE_URL` overrides the default.
   - Explicit `base_url` overrides the environment value.
   - `IBM_ICA_API_KEY` is passed as the Anthropic API key.
   - A missing Key raises before network access.
3. Add failing catalog tests asserting only Claude candidates remain.
4. Add a failing CLI test asserting the ICA menu URL is `/ica`.
5. Implement the minimum provider changes needed to pass each test.
6. Run focused LLM-client, catalog, structured-output, Chat, and vision tests.
7. Run `ruff check .` and the full non-integration test suite.

No live ICA request is required for the automated suite. If a live verification is run, it must be an explicit, minimal smoke request because it uses a real credential and may incur cost.

## Acceptance Criteria

- `create_llm_client("ibm_ica", ...)` returns an Anthropic-backed client.
- An ICA invocation targets `<resolved-base-url>/v1/messages` rather than any `/chat/completions` route.
- `IBM_ICA_API_KEY` is used as `x-api-key`; `ANTHROPIC_API_KEY` is not required.
- The default Base URL is `https://api.nextgen-beta.ica.ibm.com/ica` in core and CLI paths.
- The IBM ICA catalog and health-check candidates contain only Claude model IDs.
- TradingAgents analysis and Advisor Chat use the migrated client without entry-point-specific branches.
- Existing native Anthropic and other Provider tests remain green.
- Documentation contains no remaining claim that IBM ICA uses OpenAI-compatible Chat Completions.
- No credential value is logged, committed, or exposed in test output.
