# Product

## Register

product

## Users

Traders, quant researchers, and finance-curious developers running multi-agent
LLM analysis on a ticker. They arrive with a symbol and a date, configure a run
(analysts, research depth, LLM provider, language), and watch a team of agents
debate toward a Buy/Hold/Sell decision in real time. They are technical, read
fast, and care about provenance: which agent said what, and why the final call
landed where it did. Often bilingual (the UI ships Simplified Chinese strings
alongside English).

The context is focused work, not casual browsing. One analysis at a time
(the backend enforces a single-run lock), streamed over SSE, sometimes running
for minutes. Users keep the tab open and glance back as agents report in.

## Product Purpose

A conversational front end for the TradingAgents framework. It turns a CLI-only
research tool into a watchable, replayable workflow: start a run, follow agent
progress live, read each analyst's report as it streams, land on a final
decision, and browse past runs from history. Success is a user trusting the
decision enough to understand the reasoning behind it, not just the verdict.

This is a research scaffold, never financial advice. The UI should make the
multi-agent reasoning legible, not dress it up as certainty.

## Brand Personality

Terminal-native, precise, unembellished. Three words: **instrument, legible,
candid.** It reads like a trading terminal or a well-built dev tool, not a
fintech marketing site. Monospaced type, dark surface, restrained color that
only speaks when it carries meaning (green = bullish, red = bearish). The voice
is direct and status-driven: "最终决策", agent names, live statuses, no hype.

## Anti-references

- **Consumer fintech apps** (Robinhood, neobank dashboards): confetti, gradients,
  big friendly rounded cards, celebratory color. Wrong register entirely.
- **Generic SaaS / shadcn default look**: grayscale neutral theme, identical card
  grids, purple accents, hero-metric templates. The current shadcn tokens lean
  this way; the real app intentionally overrides them.
- **Navy-and-gold "serious finance"**: the first-reflex trap for trading tools.
  Avoid it.
- **Dashboards that fake confidence**: oversized single numbers with decorative
  accents that imply precision the model doesn't have.

## Design Principles

1. **Color is signal, not decoration.** Green and red mean bullish and bearish.
   Reserve them for decision state and direction; everything else stays neutral
   so the meaningful color reads instantly.
2. **Show the reasoning, not just the verdict.** Agent-by-agent reports and live
   status are the product. The final decision is the destination, not the whole
   trip.
3. **Legible under glance.** Users watch a run unfold over minutes. Streaming
   state, agent identity, and current step must be readable at a glance without
   re-reading.
4. **Earned familiarity over novelty.** This is a tool. Standard affordances,
   consistent component vocabulary, no invented controls. The interface should
   disappear into the task.
5. **Honest about uncertainty.** The framework is non-deterministic and not
   advice. The UI never implies more confidence than the analysis warrants.

## Accessibility & Inclusion

- Target WCAG AA. The dark terminal theme must keep body text and the
  green/red decision colors above 4.5:1 on the near-black surface (current
  emerald-400 / red-400 on zinc-900 are borderline at small sizes; verify).
- Never encode decision direction by color alone. The decision label text
  (Buy / Hold / Sell, plus the Chinese label) always carries the meaning too,
  so red/green color-vision deficiency is covered.
- Bilingual (zh-CN + English) strings coexist; type and layout must not clip
  CJK glyphs.
- Respect `prefers-reduced-motion` for any streaming/progress animation.
