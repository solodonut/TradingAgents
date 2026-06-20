# Chat Multi-Report Context Design

## Goal

Allow one Chat session to use zero or more completed analysis reports as persistent context. Reopening the session restores the same report selection, and every subsequent message uses that selection until the user changes it.

## Scope

- Replace the single-report Chat association with an ordered, persistent multi-report association.
- Keep existing single-report sessions readable without a destructive migration.
- Allow only completed analysis runs to be selected.
- Let users update the reports associated with an existing Chat session without clearing its messages.
- Preserve the current page layout and right-sidebar ownership of report and portfolio controls.

Per-message report overrides, report comparison workflows, and a hard selection limit are outside this change.

## Data Model

Add a `chat_session_runs` table with:

- `session_id`: references the Chat session.
- `run_id`: references the analysis run.
- `position`: preserves the user's selection order.
- A unique constraint on `(session_id, run_id)`.

Keep `chat_sessions.run_id` for compatibility with existing databases. When a session has no rows in `chat_session_runs`, the store exposes the legacy `run_id` as a single-element `run_ids` list. Any later association update writes the new table and clears the legacy field so that the normalized association becomes authoritative.

Deleting a Chat session removes its association rows. Deleting an analysis run removes its association rows while leaving the Chat session and messages intact.

## API Contract

Creating a session accepts `run_ids: string[]`, while continuing to accept the legacy `run_id` field during migration. Supplying both fields is invalid.

Session list and detail responses expose `run_ids`. The legacy `run_id` response field remains available and contains the first selected report, or `null`, to avoid breaking current clients during this change.

Add an endpoint to replace a session's report associations atomically. The request contains the complete ordered `run_ids` list. An empty list changes the session to general investment consultation.

The API rejects the complete update with HTTP 422 when any ID:

- does not exist,
- belongs to a run whose status is not `completed`, or
- appears more than once.

No partial update is written after validation fails.

## Chat Context Assembly

The stream endpoint reads report IDs from the persisted session, not from each message request. For every selected run it builds report context using the existing report-context helper.

Multiple contexts are joined in selection order. Each section has a clear header containing the report number, instrument code, analysis date, and decision so the model can distinguish reports. Missing report associations caused by later report deletion are ignored because their join rows are removed.

The existing prompt construction and report-content trimming rules remain authoritative. This feature does not add a separate token-budget system.

## Frontend Interaction

Change the right-sidebar report picker from a single-select control to a compact multi-select control:

- The collapsed state summarizes the selection and shows the selected count.
- The expanded state lists analysis runs with checkboxes and identifies each by instrument, date, and decision.
- Completed runs are selectable. Running and failed runs remain visible but disabled.
- Zero selected reports is valid and represents general consultation.
- Changes on an existing session are saved immediately without creating a new session or deleting messages.
- If saving fails, restore the last persisted selection and show a concise error.

The page's large-scale layout, Chat history sidebar, and portfolio controls do not move.

## Testing

Store tests cover ordered create/read/update behavior, empty selections, legacy `run_id` compatibility, and cleanup when a session or analysis run is deleted.

Route tests cover create and update contracts, rejection of missing/non-completed/duplicate runs, atomic failure behavior, and multi-report system-prompt assembly.

Frontend verification uses the existing lint, TypeScript, and production-build commands. No new component-test framework is introduced for this focused change.

## Success Criteria

1. A user can select multiple completed reports in the Chat right sidebar.
2. The selection persists with the Chat session and is restored after reopening the page.
3. Every Chat response uses all currently selected reports in a clearly separated context.
4. Invalid or unfinished reports cannot become Chat context.
5. Existing single-report and report-free Chat sessions remain usable.
