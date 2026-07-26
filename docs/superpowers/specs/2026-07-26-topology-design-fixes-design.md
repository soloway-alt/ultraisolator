# Design: partition-bar interaction fix + stale-theme audit

Date: 2026-07-26 · Scope approved: "Дефекты + аудит остальных страниц" (Подход 1)

## Context

Commit efdb045 adopted the validated CPU-partition palette (design system
"UltraIsolator Design System" in Claude Design). A post-hoc adversarial review
found two defects and one process gap:

1. `premium.css` `.core-tile:hover, .core-tile.selected { border-color: … }`
   repaints all four border sides, so the 3px partition top bar turns
   interactive-blue on hover/selection (invisible on the game partition, wrong
   on background/housekeeping/unassigned).
2. The Topology legend swatch for "Unassigned" is solid; the design system
   renders it dashed (absence-of-a-partition semantics).
3. Visual baselines compare with `maxDiffPixelRatio: 0.005`, not byte-identical
   — noted for Этап 9 (the CSS-flatten oracle must be tightened to 0 for the
   flatten run); out of scope here.

## Changes

### Fix 1 — partition bar survives hover/selection
In `premium.css`, after the `.core-tile:hover, .core-tile.selected` block, add
four rules restoring `border-top-color: var(--eii-partition-<x>)` for
`partition-game/background/housekeeping/unassigned` under `:hover` and
`.selected`. Border-style is untouched, so the unassigned dash survives.

### Fix 2 — dashed legend swatch
In `styles.css`: `.legend-item.partition-unassigned::before { border-style: dashed; }`.

### Audit — stale-theme literals in ui/src (CSS + JSX)
Grep list: `#00D4AA`, `rgba(0,212,170,…)`, `#22f0c5`, `#66E0C8`, `#8AB4F8`,
`#FFB800`, `rgba(255,184,0,…)`, `#FF4757`, `rgba(66,199,183,…)`, `#42c7b7`,
`#6de0d2`, `#8fb7ff`, `rgba(148,166,176,…)`. Each hit is classified by cascade:

- **live** (user-visible in the premium theme) → replace with a premium token,
  preserving the current visual value unless it contradicts the design system;
  known case: `.status-badge.foreground` (#66E0C8) and `.protected` (#8AB4F8)
  stay visually identical but move behind new tokens
  `--eii-status-foreground` / `--eii-status-protected`.
- **dead** (overridden by premium) → left untouched; listed in task #8 notes as
  input for the Этап-9 cascade-winner flatten.

## Out of scope

Dead literals themselves, the screenshot-tolerance change, new components, any
broader re-skin.

## Verification

Single commit. `build:renderer` → `test:unit` → full Python suite → eslint +
stylelint → visual suite (baselines regenerated only deliberately, every diff
eyeballed) → a11y → smoke.

## Audit outcome (as executed)

A postcss cascade classifier (scratchpad `stale-audit.js`, the precursor of the
Этап-9 flatten script) partitioned 84 stale-literal declarations into 50 DEAD
(identical-selector override later in the cascade) and 25+9 LIVE candidates
(including old-alert `rgba(255,71,87,…)` hits missed by the first pattern set).
All live candidates were modernized: status-badge foreground/protected behind
new tokens, game/jailed/warning/error row washes, analysis/readiness check
borders, Carbon tag--green/--yellow/--red surfaces, toast/history warning and
error borders, Start-button ring, Settings input focus ring, table hover wash,
and the late-theme quick-actions hover block. A headless-Chromium computed-style
probe confirmed the fixes render (tags, glows, washes, tokens); it also showed
three edits are dead-but-harmless because premium already wins via other
selectors (`.quick-actions button:first-child` colors, the game-mode panel
border, the msi-table hover) — left for the Этап-9 flatten. Visual baselines
did not change beyond the comparator threshold; no baseline regeneration was
needed. Full suite green: 326 Python, unit, eslint/stylelint 0 errors,
11 visual + 5 a11y, smoke.
