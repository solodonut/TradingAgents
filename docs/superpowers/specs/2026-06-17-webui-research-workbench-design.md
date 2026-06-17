# TradingAgents WebUI Research Workbench Redesign

Date: 2026-06-17
Status: Approved for implementation
Register: product

## Goal

Redesign the current single-column TradingAgents WebUI into a dense research workbench for technical users watching a multi-agent market analysis run. The UI should feel like an instrument: precise, candid, terminal-native, and optimized for scanning provenance, progress, and final reasoning.

The redesign keeps the existing API, SSE event model, and run/history data structures. This is a frontend experience and visual-system change, not a backend rewrite.

## Scene

A trader or quant researcher keeps the app open on a desktop monitor while a run streams for several minutes. They need to start a run, glance at which agents are done or working, read reports as they arrive, and understand the final decision without scrolling through the whole transcript.

This forces a dark, restrained product interface. Color is reserved for semantic state: bullish, bearish, neutral, warning, and error.

## Primary Layout

Desktop becomes a three-zone workbench:

1. Left rail: history queue
   - Fixed-width rail for recent analyses.
   - Each row shows ticker, trade date, status, and decision where available.
   - Selected history item is visibly active without relying on color alone.
   - Delete remains available but subordinate.

2. Center pane: research transcript
   - Main reading surface for live reports and historical report sections.
   - Message bubbles become research memos, with compact agent headers, stage labels, and markdown body.
   - Empty state explains the workflow briefly without marketing language.
   - Error state stays inline and specific.

3. Right console: run controls and state
   - New analysis configuration sits at the top.
   - Agent status matrix stays visible during the run.
   - Final decision summary stays visible when available.
   - Running state is explicit and non-decorative.

## Mobile Layout

Below tablet width, the workbench collapses to one column:

- Header and active context first.
- Run controls and agent status next.
- Transcript follows.
- History becomes a full-width section rather than a persistent side rail.

No text should clip in Chinese or English. Controls keep fixed, predictable heights.

## Visual System

- Replace most raw `black` / `zinc` styling with OKLCH CSS variables for the terminal palette.
- Keep the design dark-only for this pass.
- Use restrained color:
  - Green: Buy / Overweight / positive completion.
  - Red: Sell / Underweight / destructive/error.
  - Amber: working/warning.
  - Neutral: Hold, pending, metadata, inactive surfaces.
- Avoid gradient text, glassmorphism, decorative charts, decorative motion, hero metrics, and repeated identical card grids.
- Use thin borders, compact labels, tabular numbers, and consistent radius.
- Motion is limited to state feedback and respects `prefers-reduced-motion`.

## Component Changes

### App shell

`webui/app/page.tsx` becomes the layout coordinator for the three workbench zones. It keeps the current state model: options, history, statuses, messages, decision, error, running, selected detail.

### ConfigCard

The config form becomes a compact console module:

- Ticker/date grouped as primary inputs.
- Asset type uses a segmented control.
- Analyst selection uses compact toggles.
- Research depth and language are grouped as run parameters.
- Start button remains the primary action and clearly shows disabled/running state.

### AgentProgress

The status row becomes a status matrix:

- Stable agent order.
- Pending, working, done states.
- Uses text labels plus symbols, not color alone.
- Compact enough for the right console and mobile.

### HistorySidebar

History rows become more scan-friendly:

- Ticker emphasized.
- Date and status separated.
- Decision badge where known.
- Empty state included.

### MessageBubble

Renamed visually into a research memo without changing the component name unless implementation makes it worthwhile:

- Agent header is compact and structured.
- Markdown remains readable.
- Long reports keep a 65-75ch prose measure.
- Code/pre blocks remain dark and bounded.

### DecisionCard

Decision becomes the terminal output:

- Rating/decision is prominent but not a fake certainty metric.
- Detail text remains markdown.
- For the right console, a compact summary variant may be added if needed.

### RunDetail

Historical run detail should reuse the same memo and decision presentation rather than looking like a separate screen.

### Metadata

Update `app/layout.tsx` metadata from default Create Next App text to TradingAgents-specific copy.

## Data Flow

No API changes.

- `getConfigOptions()` loads form options.
- `getHistory()` populates the history rail.
- `startAnalysis()` starts a run.
- `subscribe()` streams `agent_status`, `message`, `done`, and `error`.
- History detail still loads via `getHistoryDetail()`.

The UI may derive small view-model helpers locally, for example current active agent count or latest message agent, but should not alter persisted data.

## Error And Edge States

- Backend unavailable: visible inline error near the run console.
- 409 busy state: clear Chinese text, start button disabled while local run is active.
- No history: left rail teaches that completed runs appear there.
- No messages yet: center pane explains that reports will stream in.
- History detail loading: skeleton blocks, not a spinner.
- History detail error: inline error.
- External data gaps in report text should be readable as report content, not hidden.

## Accessibility

- Interactive rows and controls must have focus-visible states.
- Decisions must include text labels, not color alone.
- Contrast should meet WCAG AA for small labels where practical.
- Avoid icon-only buttons unless they have accessible labels.
- Respect `prefers-reduced-motion`.

## Files Expected To Change

- `webui/app/page.tsx`
- `webui/app/globals.css`
- `webui/app/layout.tsx`
- `webui/components/ConfigCard.tsx`
- `webui/components/AgentProgress.tsx`
- `webui/components/HistorySidebar.tsx`
- `webui/components/MessageBubble.tsx`
- `webui/components/DecisionCard.tsx`
- `webui/components/RunDetail.tsx` if needed

## Verification

Run:

```bash
cd webui && npm run lint
cd webui && npm run build
```

If a local browser run is feasible, start:

```bash
cd webui && npm run dev
```

Then visually check:

- Desktop workbench layout has left history, center transcript, right console.
- Mobile layout does not clip controls or CJK labels.
- Empty, loading, running, error, history detail, and final decision states remain understandable.
- No forbidden visual patterns appear: gradient text, decorative glass, side-stripe borders, hero metric blocks, or nested cards.

## Self Review

- No placeholders remain.
- Scope is limited to frontend design and UI structure.
- API and backend behavior are explicitly unchanged.
- The design keeps the project's product register and terminal-native personality.
- The largest risk is implementation size in existing compact components; if a file becomes too large, extract a small local helper component rather than introducing a new design system.
