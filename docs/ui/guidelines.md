# UI guidelines

Status: Active

Source of truth for: UI presentation consistency, responsive behavior, and visual verification

Applies to: Vue views, components, shared styles, and user-visible labels

Related documents:
- [Code organization](../development/code-organization.md)
- [Validation policy](../development/validation.md)
- [Domain state transitions](../domain/state-transitions.md)

## Current state

The frontend has useful shared foundations, but presentation is not yet fully
centralized:

- `frontend/src/utils/time.js` and `productTimezone.js` provide shared
  date/time formatting, while `Archive.vue`, `Navbar.vue`, and chart code also
  contain local formatters.
- Empty values use `—`, `--`, blank text, or context-specific wording.
- Submission and report labels, severities, and CSS classes are mapped in
  multiple views and components. `Archive.vue` displays rejected submissions
  as `未通過`, while `Admin.vue` still contains `已退回`.
- `frontend/src/style.css` defines light/dark semantic variables and scalable
  type sizes, but component-scoped styles also contain hard-coded colors.
- Media queries include common `640px` and `768px` thresholds plus many
  screen-specific exceptions in `Admin.vue`, `Archive.vue`, and `Home.vue`.
- Loading, empty, error, timeout, and permission-denied states are handled
  independently across features.

These observations are known technical debt, not a claim that the UI has
already been normalized.

## Required direction

- Use `frontend/src/utils/time.js` and `productTimezone.js` as the starting
  point for shared date/time behavior. Exact times use the product timezone and
  a 24-hour clock.
- Do not use one placeholder to conflate a missing value, an intentionally
  unset value, hidden information, and a load failure. Use explicit text when
  the distinction affects user decisions.
- Domain status meaning and allowed actions come from
  [Domain state transitions](../domain/state-transitions.md). UI code must not
  invent a different Chinese name for the same Domain state.
- Prefer semantic light/dark tokens from `frontend/src/style.css`. Add or
  extend a token when a repeated semantic role cannot be expressed safely;
  avoid duplicating raw light/dark color pairs.
- Render loading, empty, error, timeout, and permission-denied as separate
  states with appropriate recovery actions.
- Choose a search normalizer by Domain. Course search currently uses
  `frontend/src/utils/courseText.js`, including whitespace and full-width/
  half-width parenthesis handling; unrelated search domains need not inherit
  those exact rules.
- Shared components should centralize a repeated rule, not become a single
  universal component with unrelated modes.

## Canonical presentation decisions

| Domain value | Canonical Chinese label |
| --- | --- |
| `ArchiveSubmission.rejected` | `未通過` |
| Report `dismissed` | `回報不成立` |

Other labels, severities, and action availability must follow the Domain
contract rather than a local mapping copied into a new screen.

## Responsive principles

- A mobile fix must not change the desktop contract unintentionally.
- Prefer the existing common breakpoint tiers. A page-specific breakpoint is
  acceptable only when the component's intrinsic layout demonstrates the need.
- For a changed breakpoint `B`, verify `B-1`, `B`, and `B+1`, plus one
  representative narrow mobile, wide mobile/tablet, and desktop viewport.
- Do not begin with another extremely narrow media query when the issue may be
  caused by intrinsic sizing or a parent constraint.
- After a second CSS attempt fails for the same scenario, stop stacking rules
  and inspect the DOM, computed styles, intrinsic sizing, parent constraints,
  actual CSS viewport, font loading, browser zoom, and cache/Service Worker.
- Separate Safari/Chrome layout-engine differences from stale bundle or cache
  differences before applying browser-specific CSS.
- Preserve keyboard access, visible focus, semantic markup, adequate contrast,
  and reduced-motion behavior at every supported size.

## Font scaling

`frontend/src/utils/fontSizePreference.js` defines a supported display range of
50% to 150%, applies it through `--app-font-scale`, and retains legacy stored
values. UI work must not be verified only at 100%. Enlarged text must preserve
the main actions, labels, validation messages, and data needed to recover.

## Verification expectations

For a focused UI change:

1. inspect the relevant shared utilities, tokens, and closest existing pattern;
2. run the narrowest relevant lint or unit check;
3. verify the changed states and responsive boundary at the planned font sizes;
4. use browser evidence only when layout or interaction cannot be established
   statically;
5. follow the retry and stop budget in
   [Validation policy](../development/validation.md).

Record which themes, viewports, font scales, states, and browsers were actually
checked. Do not claim visual equivalence from a build alone.

## Known technical debt

- Consolidate date/time formatters after consumer behavior is characterized.
- Replace parallel status label/severity maps with Domain-aware presentation
  helpers.
- Define placeholder semantics for common table/detail contexts.
- Reduce hard-coded colors by extending semantic tokens.
- Establish common responsive tiers while retaining justified component
  boundaries.
- Extract repeatable loading/empty/error/timeout patterns without erasing
  feature-specific recovery.

## Required follow-up

Technical debt should be addressed in bounded UI slices with focused tests and
visual evidence. It must not be bundled into unrelated feature work.
