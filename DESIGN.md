# Design

Visual system for the TradingAgents WebUI (`webui/`). Next.js 16, React 19,
Tailwind v4, shadcn + base-ui primitives.

> **Important: two layers exist, and the second one is the real design.**
> `app/globals.css` ships the stock shadcn token set (a neutral grayscale theme
> with light + dark variants). But `app/page.tsx` and the feature components do
> not consume those tokens. They hard-code a dark terminal aesthetic with raw
> Tailwind utilities (`bg-black`, `text-zinc-200`, `font-mono`, emerald/red).
> When designing new UI, follow the terminal aesthetic below. Treat the unused
> shadcn neutral tokens as scaffolding to either adopt deliberately or migrate
> off, not as the current look.

## Theme

Dark. Scene: a trader watching a multi-agent run stream in on a dark terminal,
focused, scanning agent statuses and reports for the call. Near-black surface,
monospaced type, color reserved for bullish/bearish signal. Light mode tokens
exist in `globals.css` but the app renders dark-only today.

## Color

Strategy: **Restrained.** Tinted-toward-neutral dark surface, with green and red
as the only meaningful accents, used exclusively for decision direction and
state. No decorative color.

Currently the components use raw Tailwind palette values rather than OKLCH
tokens. Documenting what's actually on screen:

| Role | Value (current) | Usage |
|---|---|---|
| Surface (app) | `black` (zinc-950-ish) | Root background (`page.tsx`) |
| Surface (panel/card) | `zinc-900` | DecisionCard, message surfaces |
| Body text | `zinc-200` | Default foreground |
| Muted text | `zinc-300` / `zinc-500` | Secondary, labels, captions |
| Borders | `zinc-700` | Default card/panel borders |
| Bullish | `emerald-400` (Buy), `emerald-300` (Overweight) | Decision direction up |
| Bearish | `red-400` (Sell), `red-300` (Underweight) | Decision direction down |
| Neutral decision | `zinc-300` (Hold) | No directional signal |
| Error | `red-400` on `red-950/40`, border `red-800` | Error banners |
| Brand accent | `emerald-400` | App title (`TradingAgents 分析助手`) |

shadcn token layer (in `globals.css`, mostly unused by features): full neutral
`oklch(... 0 0)` ramp for background/foreground/card/primary/secondary/muted/
accent, `destructive` at `oklch(0.577 0.245 27.325)`, plus chart-1..5 grays and
sidebar tokens. One stray purple lives at `--sidebar-primary:
oklch(0.488 0.243 264.376)` in dark mode and is not used by the app.

**Direction when adding color:** keep it restrained. Green up, red down, neutral
otherwise. If you introduce new accents, define them as OKLCH tokens and tint
neutrals toward the surface hue rather than using pure `zinc`/`black`.

## Typography

- **Mono is the brand voice.** `--font-geist-mono` (Geist Mono) carries the
  title, the decision verdict, labels, statuses, and error text. This is the
  terminal identity; keep mono for system/status/data surfaces.
- **Sans for prose.** Geist Sans (`--font-geist-sans`, wired as `--font-sans`)
  is the default body font (`html { font-family: sans }`), used for streamed
  report prose via `@tailwindcss/typography` (`prose prose-invert prose-sm`).
- Loaded in `app/layout.tsx` via `next/font/google` (Geist + Geist Mono).
- Decision verdict is the one display moment: `text-4xl font-bold font-mono
  tracking-tight`. Labels use tiny uppercase mono with wide tracking
  (`text-[0.65rem] uppercase tracking-widest`).
- Keep report prose at readable measure (the main column is `max-w-3xl`).

## Layout

- **App shell:** full-height flex. Left `HistorySidebar` (past runs) + main
  scroll column (`flex h-screen`). Main content centered at `max-w-3xl mx-auto`,
  padded `p-4`, vertical rhythm `space-y-3`.
- Single-column conversation flow: title, config card, agent progress, streamed
  message bubbles, final decision card, stacked top to bottom in run order.
- Radius scale is token-driven off `--radius: 0.625rem` (sm/md/lg/xl... computed
  as multiples). Components mostly use `rounded-lg`.
- Cards are used here because each agent report and the final decision are
  genuinely distinct units. The DecisionCard earns a heavier `border-2` to mark
  it as the terminal output. Do not introduce nested cards.

## Components

Primitives in `components/ui/` (shadcn-style, built on `@base-ui/react`):
`button.tsx`, `card.tsx`, `badge.tsx`. Feature components in `components/`:
`ConfigCard`, `AgentProgress`, `MessageBubble`, `DecisionCard`,
`HistorySidebar`.

- **Button** (`cva` variants): `default` (primary fill), `outline`, `secondary`,
  `ghost`, `destructive` (tinted, not solid red), `link`. Sizes
  `xs/sm/default/lg` + icon variants. Has focus-visible ring, active translate,
  disabled opacity. This is the standard interactive vocabulary; reuse it rather
  than hand-rolling buttons.
- **DecisionCard:** the climax. `border-2` colored by direction, giant mono
  verdict, markdown detail below in `prose-invert`.
- **Decision vocabulary** is five-tier: Buy / Overweight / Hold / Underweight /
  Sell, each mapped to a color + border (emerald → zinc → red).

State coverage to maintain: every interactive component needs default, hover,
focus, active, disabled. Button has these; new components should match. Use
skeletons over spinners for loading; design empty states (history with no runs)
to teach the interface.

## Motion

`tw-animate-css` is available. Keep motion as state feedback only: streaming
status changes, progress, reveals. 150-250ms, ease-out (no bounce/elastic).
Don't animate layout properties. Honor `prefers-reduced-motion`.

## Known cleanups (not yet done)

- `app/layout.tsx` metadata still says "Create Next App" / "Generated by create
  next app". Should reflect the product.
- Components bypass the shadcn token system and use raw `zinc`/`emerald`/`red`.
  Either migrate the terminal palette into proper OKLCH tokens or drop the unused
  shadcn neutral layer; right now both coexist and the tokens mislead.
- Light-mode tokens exist but the app is dark-only. Decide whether light mode is
  in scope.
- Verify `emerald-400` / `red-400` decision text hits WCAG AA on `zinc-900` at
  small sizes.
