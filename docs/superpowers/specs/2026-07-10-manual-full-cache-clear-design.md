# Manual Full Cache Clear Design

## Goal

Allow a WebUI user to clear all files under `DEFAULT_CONFIG["data_cache_dir"]` on demand. This includes vendor data caches and `checkpoints/`, so a new analysis fetches data again and cannot resume any interrupted checkpointed run.

## Scope

In scope:

- Reuse the existing `StartupCacheClearer` scanning, symlink protection, progress state, and deletion accounting.
- Add a full-clear mode that includes `checkpoints/`.
- Expose a manual cache-clear API and a WebUI action with confirmation and progress.
- Reject a manual clear while an analysis is running or another clear is active.

Out of scope:

- `~/.tradingagents/webui.db`, analysis history, queue rows, watchlist, chat data, ETF snapshots, run logs, or learning memory.
- Changing the automatic startup clear behavior, which continues to preserve `checkpoints/`.
- Changing vendor routing, cache TTLs, or market-data freshness rules.

## Chosen Design

Extend `StartupCacheClearer` with an `include_checkpoints` option. Its default remains `False`, preserving startup behavior. A manual full-clear instance uses `True` and deletes every regular file beneath `data_cache_dir`, including checkpoint databases. The scanner continues to reject a symlink cache root and skips symlink targets.

The API owns one process-local manual clearer in `app.state`. `POST /api/cache/clear` starts a full clear and returns its initial state. `GET /api/cache/status` returns the latest state, and `GET /api/cache/stream` exposes the existing SSE progress events. A request while the clearer is active returns 409. A request while an analysis is active returns 409.

The WebUI adds a destructive `清除全部缓存` action near service health. Its confirmation states that all data caches and checkpoints will be deleted, while history, queue, portfolios, snapshots, and memory remain. Once confirmed, the UI starts the request, subscribes to progress, and disables the action until terminal completion.

## Data Flow

1. User confirms `清除全部缓存`.
2. The frontend calls `POST /api/cache/clear`.
3. The route rejects active analysis or a concurrent clear; otherwise it creates/starts `StartupCacheClearer(..., include_checkpoints=True)`.
4. The clearer scans only `data_cache_dir`, deletes files one by one, and publishes progress.
5. The frontend reads `/status` and `/stream` until it receives a terminal `completed` or `error` state.
6. The next analysis starts with empty endpoint and checkpoint caches.

## Error and Safety Rules

- Never traverse or delete a symlink target.
- Never delete outside `data_cache_dir`.
- Continue deleting remaining files after an individual deletion failure, then surface terminal `error` with bounded cache-relative error details.
- Do not start while `app.state.run_lock` is locked or a manual clear is already active.
- Do not remove empty directories: deleting files is sufficient and minimizes filesystem mutation.

## Tests

- Default startup mode still preserves `checkpoints/`.
- Full mode deletes vendor cache files and checkpoint files.
- Full mode preserves files outside the configured cache root and skips symlink targets.
- Manual API returns 409 for an active analysis or active clear.
- Manual status and SSE return progress and terminal summaries.
- Frontend requires confirmation, sends the clear request, and disables the action while active.
