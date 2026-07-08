# WebUI Service Health Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add visible remote-service health checks to the TradingAgents WebUI.

**Architecture:** A new backend health module produces status events for LLM slots and data vendors, exposed by a FastAPI SSE route. The frontend consumes the stream, keeps the latest status table, and triggers checks on first load, analysis failure, and a button click.

**Tech Stack:** FastAPI, sse-starlette, pytest, Next.js 16, React 19, TypeScript, Tailwind, lucide-react.

---

### Task 1: Backend Health Stream

**Files:**
- Create: `api/service_health.py`
- Create: `api/routes/health.py`
- Modify: `api/main.py`
- Test: `tests/webui/test_routes_health.py`

- [ ] Write failing route tests for streaming LLM/data status and non-crashing failures.
- [ ] Implement service probes and SSE route.
- [ ] Include the health router in `api/main.py`.
- [ ] Run `pytest tests/webui/test_routes_health.py -v`.

### Task 2: Frontend Health Panel

**Files:**
- Modify: `webui/lib/types.ts`
- Modify: `webui/lib/api.ts`
- Create: `webui/components/ServiceHealthPanel.tsx`
- Modify: `webui/app/page.tsx`

- [ ] Add TypeScript types and stream helper.
- [ ] Add a compact status panel with manual check button.
- [ ] Trigger checks on mount and analysis failure.
- [ ] Run `cd webui && npm run lint` and `cd webui && npm run build`.
