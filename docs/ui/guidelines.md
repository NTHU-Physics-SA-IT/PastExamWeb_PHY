# UI guidelines

Status: Active

Source of truth for: UI presentation consistency, responsive behavior, and visual verification

Applies to: Vue views, components, shared styles, and user-visible labels

Related documents:
- [Responsive layout contract](responsive-layout-contract.md)
- [Code organization](../development/code-organization.md)
- [Frontend internationalization](../development/i18n.md)
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

- Localized user-visible copy and translation completeness must follow the
  [frontend internationalization contract](../development/i18n.md).
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

Review Center course presentation distinguishes the nullable current linked
Archive placement from submitted/proposed history. When `current_archive` is
present, its localized Course name is primary and a differing submitted Course
is labeled as history. When it is absent, the UI labels the submission value as
submitted data rather than implying a current placement. Both submission-family
tabs use the same rule, status-pill classes, and non-wrapping administrator
badge contract. Backend catalog ordering is canonical; selectors preserve API
Category/Course order instead of applying their own locale-sensitive or local
index sort.

## Responsive principles

- Use the canonical Major Class, Major Breakpoint, Feature Class, Feature
  Breakpoint, and Container Breakpoint terminology and authority in the
  [Responsive layout contract](responsive-layout-contract.md).
- A change scoped to one Feature Class must not change another Feature Class
  unintentionally.
- Preserve documented Feature Breakpoints unless the owner explicitly approves
  adding, moving, or removing one.
- Keep fixed Major Breakpoints and Feature Breakpoints in pixels so root
  typography preferences do not reclassify the same viewport as a different
  class. Keep Container Breakpoints outside the viewport taxonomy.
- Apply the contract's proportional boundary validation. Use `B-1`, `B`, and
  `B+1` for changed structural or high-risk boundaries and for joint CSS/JS
  mode switching, not automatically for every cosmetic adjustment.
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

`frontend/src/utils/fontSizePreference.js` defines the 90% application typography
baseline and a supported 50% to 150% user multiplier. Their product is applied
once at the root font size and exposed as `--app-effective-font-scale`; nested
`rem` typography must not multiply that effective scale again. The preference
retains legacy stored values. UI work must not be verified only at 100%. Enlarged
text must preserve the main actions, labels, validation messages, and data needed
to recover.

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
- Apply the documented Major Classes and Feature Classes while resolving known
  legacy exact-boundary behavior through focused visual evidence.
- Extract repeatable loading/empty/error/timeout patterns without erasing
  feature-specific recovery.

## Required follow-up

Technical debt should be addressed in bounded UI slices with focused tests and
visual evidence. It must not be bundled into unrelated feature work.
