# Startup Endpoint Cache Clear Design

## Goal

Every time the WebUI API starts, TradingAgents must clear local endpoint data caches before any analysis run can start. The UI must show task progress and block analysis actions until the startup cache clear succeeds.

## Scope

In scope:

- Clear endpoint local data caches under `DEFAULT_CONFIG["data_cache_dir"]`.
- Show startup cache clear progress in the WebUI.
- Block `POST /api/analysis`, `POST /api/queue`, and queue auto-advance until clearing completes.
- Report deletion progress, deleted file count, released bytes, and errors.

Out of scope:

- WebUI history database, chat history, reports, queue rows, and watchlist data.
- LangGraph checkpoint databases under `data_cache_dir/checkpoints/`.
- Manual cache clearing during normal application use.
- Changes to data vendor routing or endpoint fetch behavior.

## Chosen Approach

Use a dedicated backend startup task with status and SSE APIs. The task runs in the background so the API can start and the UI can observe progress, but a backend gate prevents any analysis or queued run from starting until the task reaches a successful completed state.

This keeps startup maintenance separate from service reachability checks while still allowing the frontend to display the task inside the existing Service Health system area as a `system` status item.

## Backend Design

Add a small startup cache clearing component, tentatively named `StartupCacheClearer`.

Responsibilities:

- Resolve the configured cache root from `DEFAULT_CONFIG["data_cache_dir"]`.
- Scan endpoint cache targets under that root.
- Exclude non-endpoint artifacts, especially `checkpoints/`.
- Delete files one by one and update in-memory progress after each step.
- Continue after individual deletion failures, recording path and error details.
- Publish a final status of `completed` or `error`.

State fields:

- `status`: `pending`, `running`, `completed`, or `error`.
- `phase`: short machine-readable phase such as `scanning`, `deleting`, `completed`, `error`.
- `message`: human-readable Chinese UI message.
- `current_path`: path currently being processed, redacted to a cache-relative display path.
- `processed_items`, `total_items`.
- `deleted_files`, `released_bytes`.
- `errors`: bounded list of failed cache-relative paths and messages.
- `started_at`, `completed_at`, `updated_at`.

Deletion target rules:

- Delete regular cache files under `data_cache_dir`.
- Delete known endpoint cache directories such as `akshare/`.
- Delete yfinance/stockstats CSV cache files in the cache root.
- Do not delete `checkpoints/`.
- Do not delete directories until their contents have been handled; remove empty endpoint cache directories only if that is safe and local to `data_cache_dir`.

Startup sequence:

1. FastAPI startup initializes the cache clearer and starts it in a background thread.
2. Store and scheduler can be initialized, but scheduler auto-advance must not launch runs while the cache clear is incomplete.
3. When the cache clear reaches `completed`, the backend calls `scheduler.advance()` so leftover pending queue items can proceed.
4. If the cache clear reaches `error`, scheduler remains blocked and analysis endpoints continue to reject new work.

## API Design

Add routes under `api/routes/startup_cache.py`:

- `GET /api/startup-cache/status`
  Returns the latest startup cache clear state.

- `GET /api/startup-cache/stream`
  Streams progress using SSE. Events:
  - `cache_clear_status`: emitted for progress updates.
  - `summary`: emitted once with the terminal state, then the client closes.

Gate behavior:

- `POST /api/analysis` rejects while startup cache clear is not `completed`.
- `POST /api/queue` rejects while startup cache clear is not `completed`.
- `QueueScheduler.advance()` returns without launching a run while startup cache clear is not `completed`.
- Rejections use a clear error message: `启动缓存清理未完成，暂不能开始分析`.

Error policy:

Any deletion failure makes the final state `error`, even if other files were deleted successfully. This intentionally blocks analysis so stale endpoint cache cannot be silently reused.

## Frontend Design

Add startup cache status support to the WebUI:

- Add TypeScript types for startup cache clear status and events.
- Add API helpers for `getStartupCacheStatus()` and `subscribeStartupCacheClear()`.
- On page load, fetch startup cache status.
- If not terminal, subscribe to the SSE stream.
- If SSE fails, fall back to status polling.

Service Health integration:

- Display the startup cache clear as a `system` item in the existing Service Health area.
- Keep the semantics distinct from service reachability by using labels such as `启动维护`.
- Show progress while running: processed count, total count, deleted files, released bytes.
- Show completion summary after success.
- Show failed paths and messages when expanded after an error.

Analysis controls:

- Disable start/enqueue actions while startup cache status is not `completed`.
- Show the disabled reason near the action or via button title: `启动缓存清理完成后可开始分析`.
- Existing queue and history views remain readable during startup maintenance.

## Testing

Backend tests:

- Cache clearer deletes endpoint cache files under `data_cache_dir`.
- Cache clearer does not delete `checkpoints/`.
- Deletion failures are recorded and produce final `error`.
- Analysis and queue POST routes are blocked before completion.
- Scheduler does not launch pending runs before completion.
- Scheduler advances after successful completion.
- Status and SSE routes expose consistent progress and terminal summary.

Frontend tests:

- API helpers parse status and SSE events.
- Service Health panel renders startup maintenance as a `system` item.
- Start/enqueue controls are disabled while cache clear is incomplete.
- Controls re-enable after completed status.
- Error details are visible when startup maintenance fails.

## Implementation Notes

- Keep the cache clearer independent from data vendor modules so it can be tested without network or API keys.
- Prefer cache-relative paths in API responses to avoid exposing full local paths in the UI.
- Keep the in-memory status object process-local; persistence is unnecessary because the task runs on every API process startup.
- Do not add a manual clear button in this feature.
- Do not change checkpoint cleanup behavior.
