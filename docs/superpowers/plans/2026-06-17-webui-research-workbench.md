# WebUI Research Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Convert the TradingAgents WebUI from a single-column chat-like surface into a responsive three-zone research workbench.

**Architecture:** Keep all API, SSE, and React state semantics unchanged. `app/page.tsx` coordinates the workbench shell, while existing feature components are restyled into focused workbench modules. Global CSS defines terminal OKLCH tokens and reusable prose/control polish.

**Tech Stack:** Next.js 16 App Router, React 19 client components, Tailwind CSS v4, TypeScript, `react-markdown`, existing FastAPI API client.

---

### Task 1: Lock In Baseline And Tokens

**Files:**
- Modify: `webui/app/globals.css`
- Verify: `cd webui && npm run lint`

- [x] **Step 1: Record the current quality baseline**

Run:

```bash
cd webui && npm run lint
```

Expected: existing lint status is known before edits. If lint already fails, capture the exact failures and continue only if they are unrelated to the redesign.

- [x] **Step 2: Add terminal OKLCH variables**

Modify `webui/app/globals.css` so `:root` and `.dark` expose a dark terminal palette:

```css
:root {
  --background: oklch(0.145 0.006 168);
  --foreground: oklch(0.9 0.01 168);
  --card: oklch(0.18 0.007 168);
  --card-foreground: oklch(0.9 0.01 168);
  --popover: oklch(0.18 0.007 168);
  --popover-foreground: oklch(0.9 0.01 168);
  --primary: oklch(0.78 0.16 158);
  --primary-foreground: oklch(0.14 0.01 168);
  --secondary: oklch(0.24 0.008 168);
  --secondary-foreground: oklch(0.84 0.01 168);
  --muted: oklch(0.22 0.007 168);
  --muted-foreground: oklch(0.64 0.012 168);
  --accent: oklch(0.28 0.02 158);
  --accent-foreground: oklch(0.88 0.02 158);
  --destructive: oklch(0.68 0.18 25);
  --border: oklch(0.34 0.01 168);
  --input: oklch(0.24 0.008 168);
  --ring: oklch(0.72 0.14 158);
  --radius: 0.5rem;
}
```

Also add app-level helpers:

```css
body {
  background: var(--background);
  color: var(--foreground);
}

::selection {
  background: oklch(0.32 0.05 158);
  color: var(--foreground);
}
```

- [x] **Step 3: Add prose/control polish**

Add CSS rules for:

```css
.ta-prose {
  color: oklch(0.84 0.01 168);
}

.ta-prose :where(p, ul, ol) {
  margin-top: 0.7rem;
  margin-bottom: 0.7rem;
}

.ta-prose :where(h1, h2, h3) {
  color: oklch(0.94 0.012 168);
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }
}
```

- [x] **Step 4: Verify CSS compiles**

Run:

```bash
cd webui && npm run lint
```

Expected: lint completes without new errors from CSS-adjacent TypeScript changes.

### Task 2: Rework Core Components

**Files:**
- Modify: `webui/components/ConfigCard.tsx`
- Modify: `webui/components/AgentProgress.tsx`
- Modify: `webui/components/HistorySidebar.tsx`
- Modify: `webui/components/MessageBubble.tsx`
- Modify: `webui/components/DecisionCard.tsx`
- Verify: `cd webui && npm run lint`

- [x] **Step 1: Restyle ConfigCard as a console module**

Keep the existing props and request payload. Change the DOM structure to compact labeled sections: Instrument, Scope, Analysts, Research, Action. Use semantic buttons for segmented controls and avoid changing `AnalysisRequest`.

- [x] **Step 2: Restyle AgentProgress as a status matrix**

Keep `statuses: Record<string, string>`. Render stable agent rows with mark, Chinese label, English id, and status text. Working state may pulse text or marker only.

- [x] **Step 3: Restyle HistorySidebar as a queue rail**

Keep props unchanged. Add an empty state, split ticker/date/decision/status into separate scan lines, and keep delete as a secondary button with `aria-label`.

- [x] **Step 4: Restyle MessageBubble as a research memo**

Keep props unchanged. Render agent label as memo metadata and markdown inside `ta-prose prose prose-invert prose-sm max-w-none`.

- [x] **Step 5: Add compact DecisionCard variant**

Extend props to:

```ts
export function DecisionCard({
  decision,
  detail,
  compact = false,
}: {
  decision: Decision;
  detail: string;
  compact?: boolean;
})
```

Full mode renders markdown detail. Compact mode renders the rating and a short status line without duplicating the full markdown body.

- [x] **Step 6: Verify component types**

Run:

```bash
cd webui && npm run lint
```

Expected: no TypeScript or lint errors.

### Task 3: Build The Three-Zone App Shell

**Files:**
- Modify: `webui/app/page.tsx`
- Modify: `webui/components/RunDetail.tsx`
- Verify: `cd webui && npm run lint`

- [x] **Step 1: Create derived run context in `page.tsx`**

Add local derived values only:

```ts
const latestMessage = messages.at(-1);
const completedAgents = Object.values(statuses).filter((s) => s === "done").length;
const workingAgents = Object.values(statuses).filter((s) => s === "working").length;
```

- [x] **Step 2: Replace the root layout with workbench zones**

Use one root container:

```tsx
<div className="min-h-screen bg-background text-foreground lg:h-screen lg:overflow-hidden">
  <div className="grid min-h-screen grid-cols-1 lg:h-screen lg:grid-cols-[18rem_minmax(0,1fr)_22rem]">
    ...
  </div>
</div>
```

Left zone contains `HistorySidebar`. Center zone contains header, error/detail/live transcript. Right zone contains `ConfigCard`, run stats, `AgentProgress`, and compact `DecisionCard`.

- [x] **Step 3: Preserve detail mode behavior**

When `selectedId` is set, center pane renders the existing `RunDetail` path with skeleton and error states. Right console still allows a new analysis, and the back button clears detail mode.

- [x] **Step 4: Preserve live run behavior**

When no detail is selected, center pane renders empty state, live messages, and the full `DecisionCard` at the end. The right console shows compact final decision when available.

- [x] **Step 5: Align RunDetail with memo surfaces**

Keep `RunDetail` props unchanged. Update the top summary block to match the workbench memo style and reuse full `DecisionCard` for final output.

- [x] **Step 6: Verify shell types**

Run:

```bash
cd webui && npm run lint
```

Expected: no TypeScript or lint errors.

### Task 4: Final Build And Visual QA

**Files:**
- Verify: `webui` build output
- Verify: browser screenshot if dev server starts

- [x] **Step 1: Run production build**

Run:

```bash
cd webui && npm run build
```

Expected: Next.js build completes.

- [x] **Step 2: Start dev server**

Run:

```bash
cd webui && npm run dev
```

Expected: local URL is printed. Keep the session open until QA is complete.

- [x] **Step 3: Visual QA desktop**

Open the app at the printed local URL. Check:

- Left history rail, center transcript, right console are visible at desktop width.
- No text overlaps or clips.
- Empty/error/running states are visible where locally reproducible.
- Decision color is accompanied by text.

- [x] **Step 4: Visual QA mobile**

Check a mobile-width viewport. Confirm:

- The layout collapses to one column.
- Controls remain usable.
- Chinese labels do not clip.
- History no longer consumes permanent side width.

- [x] **Step 5: Report final status**

Summarize changed files, verification commands, and any remaining caveats.
