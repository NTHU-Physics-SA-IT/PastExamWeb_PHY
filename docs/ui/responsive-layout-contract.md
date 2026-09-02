# Responsive layout contract

Status: Active

Source of truth for: viewport taxonomy, responsive breakpoint authority,
feature-owned viewport ranges, container-query separation, and responsive QA
governance

Applies to: PastExamWeb_PHY UI planning, implementation, review, and acceptance

Related documents:
- [UI guidelines](guidelines.md)
- [Code organization](../development/code-organization.md)
- [Validation policy](../development/validation.md)

## Scope and non-goals

This contract defines project vocabulary and ownership for responsive work. It
does not change current production behavior or make physical-device detection
part of the UI architecture.

The class names below describe the CSS viewport used by the PastExamWeb_PHY
interface. A desktop browser resized to `900px` is in **Tablet Portrait**. A
physical tablet or any other browser viewport at `1400px` or wider is in
**Desktop**. Code must not infer hardware, operating system, browser, or device
model from these names.

Existing feature behavior may use a smaller range within a Major Class. This is
intentional when the feature has a distinct layout or interaction transition.
Adopting this contract does not authorize changing an existing breakpoint.

## Normative terminology

- **Major Class:** A project-wide top-level viewport/interface range.
- **Major Breakpoint:** A viewport-width boundary separating two Major Classes.
- **Feature Class:** The existing responsive behavior range owned by one page or
  feature. A Feature Class may equal a whole Major Class or be a smaller explicit
  pixel subrange inside it.
- **Feature Breakpoint:** A viewport-width boundary separating two Feature
  Classes owned by the same feature.
- **Container Breakpoint:** A component/container-width threshold. It is outside
  the Major Class and Feature Class viewport taxonomy.
- **Representative Viewport:** A QA or acceptance viewport. It is not a
  breakpoint and is not device detection.

These terms are the canonical project language for new governance and responsive
work. Legacy implementation names may remain until the owning code is separately
modified.

## Major Classes and Major Breakpoints

| Major Class | Inclusive display range | Canonical semantic form |
| --- | --- | --- |
| Phone Portrait | `0–767px` | `width < 768px` |
| Tablet Portrait | `768–1023px` | `width >= 768px && width < 1024px` |
| Tablet Landscape | `1024–1399px` | `width >= 1024px && width < 1400px` |
| Desktop | `>=1400px` | `width >= 1400px` |

The Major Breakpoints are `768px`, `1024px`, and `1400px`.

For every Major Breakpoint `B`, the canonical boundary convention is:

- previous Major Class: `width < B`;
- next Major Class: `width >= B`.

Therefore `767px` is Phone Portrait, `768px` and `1023px` are Tablet
Portrait, `1024px` and `1399px` are Tablet Landscape, and `1400px` is Desktop.

This convention defines the project taxonomy. An intentional Feature Class may
still span a Major Breakpoint only when the registry explicitly records that
behavior; it must not be silently reclassified or changed.

Major Breakpoints are product-level governance. A Major Breakpoint MUST NOT be
added, removed, or moved without explicit owner product authorization.

## Single-width Resolution Rule

When the owner or user supplies one viewport width for a UI change, that width
MUST be treated as a locator, not as the modification scope:

1. Identify the target feature or page.
2. Resolve the width to its Major Class.
3. Consult the existing Feature Breakpoints for that feature.
4. Determine the existing Feature Class containing the requested width.
5. Use that entire existing Feature Class as the default minimum responsive
   modification scope.

**A single requested viewport width identifies an existing Feature Class; it
does not authorize creation of a new Feature Breakpoint.**

**Existing Feature Class is the default minimum responsive modification unit.**

Example: a request to adjust Home at `1100px` resolves to Tablet Landscape and
the existing Home Feature Class `Tablet Landscape / 1024–1180px`. That whole
Feature Class is the default minimum scope. The implementation must not patch
only `1100px`, create a new `1100px` Feature Breakpoint, or ask the owner to
restate a range already resolved by this registry.

## Breakpoint authority

- A single-width request does not authorize adding a Feature Breakpoint.
- A new Feature Breakpoint MAY be introduced only when the owner or user
  explicitly requests or approves adding a Feature Breakpoint or splitting a
  Feature Class.
- Moving an existing Feature Breakpoint also requires explicit approval.
- When a Feature Breakpoint is added or moved, the change MUST define the
  resulting Feature Class ranges, update this contract, and verify adjacent
  behavior proportionately.
- Use `B-1`, `B`, and `B+1` when the changed boundary is structurally
  significant, exact-boundary behavior is high-risk, or CSS and JavaScript
  jointly control the responsive mode.
- Cosmetic adjustments do not automatically require a boundary triplet.

## Feature Class and Feature Breakpoint registry

The registry records current material viewport behavior. Small typography,
spacing, decorative, and dialog-fit thresholds remain feature-owned even when
they are not expanded into separate registry rows. Source paths are evidence of
current ownership, not permission to change the breakpoint.

Statuses:

- **KEEP:** preserve the current Feature Breakpoint and behavior unless a later
  task explicitly authorizes a change.
- **NO FEATURE BREAKPOINT:** the page inherits shared layout behavior and has no
  meaningful feature-owned viewport transition.

### Navbar

| Major Class / explicit px range | Current behavior or transition purpose | Owning Feature Breakpoint(s) | Status | Evidence |
| --- | --- | --- | --- | --- |
| Phone Portrait / `0–640px` | Reduced action controls with narrow brand spacing; the brand receives a further cosmetic adjustment through `380px`. | `640px`; cosmetic `380px` | KEEP | `frontend/src/components/Navbar.vue` |
| Phone Portrait / `641–767px` | Reduced action controls without the narrow-brand adjustment. | `768px` | KEEP | `frontend/src/components/Navbar.vue` |
| Tablet Portrait / `768–1023px` | Full navigation action group; JavaScript also resolves `>=768px` to the full-navigation path. | `768px` | KEEP | `frontend/src/components/Navbar.vue` |
| Tablet Landscape / `1024–1399px` | Same full-navigation Feature Class. | `768px` | KEEP | `frontend/src/components/Navbar.vue` |
| Desktop / `>=1400px` | Same full-navigation Feature Class. | `768px` | KEEP | `frontend/src/components/Navbar.vue` |

### Home

| Major Class / explicit px range | Current behavior or transition purpose | Owning Feature Breakpoint(s) | Status | Evidence |
| --- | --- | --- | --- | --- |
| Phone Portrait / `0–560px` | Stacked hero with the narrowest background, sizing, and overflow adjustments. | `560px` | KEEP | `frontend/src/views/Home.vue` |
| Phone Portrait / `561–767px` | Stacked hero; dashboard remains one column below `768px`. | `768px` | KEEP | `frontend/src/views/Home.vue` |
| Tablet Portrait / `768–920px` | Stacked hero with reduced formula field and two-column dashboard. | `768px`, `920px` | KEEP | `frontend/src/views/Home.vue`; `frontend/src/composables/useFormulaPhysics.js` |
| Tablet Portrait / `921–1023px` | Stacked hero and two-column dashboard without the `<=920px` formula reduction. | `920px` | KEEP | `frontend/src/views/Home.vue` |
| Tablet Landscape / `1024–1180px` | Stacked, centered hero composition. | `1181px` | KEEP | `frontend/src/views/Home.vue` |
| Tablet Landscape / `1181–1399px` | Wide hero composition, right-side metrics, and relocated catalog action. | `1181px` | KEEP | `frontend/src/views/Home.vue` |
| Desktop / `>=1400px` | Same wide structural composition with feature-owned decorative formula-position subranges. | `1181px`; decorative `1450/1500/1650/1900px` thresholds | KEEP | `frontend/src/views/Home.vue` |

The decorative wide thresholds are Feature Breakpoints or cosmetic thresholds,
not Major Breakpoints.

### Archive

| Major Class / explicit px range | Current behavior or transition purpose | Owning Feature Breakpoint(s) | Status | Evidence |
| --- | --- | --- | --- | --- |
| Phone Portrait / `0–480px` | Drawer navigation with the narrowest card/action treatment. | `480px` | KEEP | `frontend/src/views/Archive.vue` |
| Phone Portrait / `481–640px` | Drawer navigation with additional compact card/action treatment through `640px`. | `640px` | KEEP | `frontend/src/views/Archive.vue` |
| Phone Portrait / `641–767px` | Drawer navigation and Phone Portrait header/content rules. | `768px` | KEEP | `frontend/src/views/Archive.vue` |
| Tablet Portrait / `768–1023px` | Fixed `258px` sidebar and the wider table-overflow treatment. | `768px` | KEEP | `frontend/src/views/Archive.vue` |
| Tablet Landscape / `1024px` | Remains in Archive's inclusive `768–1024px` sidebar Feature Class with a `258px` sidebar. | `1025px` | KEEP | `frontend/src/views/Archive.vue` |
| Tablet Landscape / `1025–1199px` | Sidebar expands to `280px`; content retains the `<=1199px` refinements. | `1025px`, `1200px` | KEEP | `frontend/src/views/Archive.vue` |
| Tablet Landscape / `1200–1399px` | Default Archive sizing after the `<=1199px` refinements end. | `1200px` | KEEP | `frontend/src/views/Archive.vue` |
| Desktop / `>=1400px` | Same default Archive structural Feature Class. | `1200px` | KEEP | `frontend/src/views/Archive.vue` |

### Wish Pool

Wish Pool does not own a viewport Feature Breakpoint for its navigation model.
Its native-scrolling to camera/panning transition is owned by the measured
`.wish-pool-stage` width and is registered under the Container Breakpoint
policy below.

### Public Courses and Public Course

| Feature | Major Class / explicit px range | Current behavior or transition purpose | Owning Feature Breakpoint(s) | Status | Evidence |
| --- | --- | --- | --- | --- | --- |
| Public Courses | Phone Portrait / `0–560px` | `40px` total horizontal inset and stacked category header. | `560px` | KEEP | `frontend/src/views/PublicCourses.vue` |
| Public Courses | Phone Portrait / `561–767px` | `56px` total horizontal inset. | `560px`, `820px` | KEEP | `frontend/src/views/PublicCourses.vue` |
| Public Courses | Tablet Portrait / `768–820px` | Same `56px` inset. | `820px` | KEEP | `frontend/src/views/PublicCourses.vue` |
| Public Courses | Tablet Portrait / `821–1023px` | Default max-`1080px` container; card columns remain intrinsic. | `820px` | KEEP | `frontend/src/views/PublicCourses.vue` |
| Public Courses | Tablet Landscape / `1024–1399px` | Same default container/intrinsic grid Feature Class. | `820px` | KEEP | `frontend/src/views/PublicCourses.vue` |
| Public Courses | Desktop / `>=1400px` | Same default container/intrinsic grid Feature Class. | `820px` | KEEP | `frontend/src/views/PublicCourses.vue` |
| Public Course | Phone Portrait / `0–560px` | `40px` total horizontal inset and stacked archive title row. | `560px` | KEEP | `frontend/src/views/PublicCourse.vue` |
| Public Course | Phone Portrait / `561–767px` | `56px` total horizontal inset. | `560px`, `820px` | KEEP | `frontend/src/views/PublicCourse.vue` |
| Public Course | Tablet Portrait / `768–820px` | Same `56px` inset. | `820px` | KEEP | `frontend/src/views/PublicCourse.vue` |
| Public Course | Tablet Portrait / `821–1023px` | Default max-`980px` container; archive columns remain intrinsic. | `820px` | KEEP | `frontend/src/views/PublicCourse.vue` |
| Public Course | Tablet Landscape / `1024–1399px` | Same default container/intrinsic grid Feature Class. | `820px` | KEEP | `frontend/src/views/PublicCourse.vue` |
| Public Course | Desktop / `>=1400px` | Same default container/intrinsic grid Feature Class. | `820px` | KEEP | `frontend/src/views/PublicCourse.vue` |

### Personal Settings

| Major Class / explicit px range | Current behavior or transition purpose | Owning Feature Breakpoint(s) | Status | Evidence |
| --- | --- | --- | --- | --- |
| Phone Portrait / `0–640px` | One-column page/forms and full-width form actions. | `640px` | KEEP | `frontend/src/views/PersonalSettings.vue` |
| Phone Portrait / `641–767px` | One-column page with horizontal settings navigation. | `640px`, `980px` | KEEP | `frontend/src/views/PersonalSettings.vue` |
| Tablet Portrait / `768–980px` | Same one-column page and horizontal settings navigation. | `980px` | KEEP | `frontend/src/views/PersonalSettings.vue` |
| Tablet Portrait / `981–1023px` | Two-column settings navigation/content layout. | `980px` | KEEP | `frontend/src/views/PersonalSettings.vue` |
| Tablet Landscape / `1024–1399px` | Same two-column Feature Class. | `980px` | KEEP | `frontend/src/views/PersonalSettings.vue` |
| Desktop / `>=1400px` | Same two-column Feature Class. | `980px` | KEEP | `frontend/src/views/PersonalSettings.vue` |

The `980px` structural Feature Breakpoint MUST NOT be aligned to `1024px`
without explicit approval and visual evidence.

### Admin

Admin contains several responsive surfaces with different owners. The ranges
below must not be collapsed into one universal Admin mode.

| Surface | Major Class / explicit px range | Current behavior or transition purpose | Owning Feature Breakpoint(s) | Status | Evidence |
| --- | --- | --- | --- | --- | --- |
| Shared Admin shell/dialogs | Phone Portrait / `0–640px` | Narrow action, toolbar, paginator, and card arrangements. | `360/400/480/600/640px` | KEEP | `frontend/src/views/Admin.vue` |
| Shared Admin toolbars | Phone Portrait / `641–760px` | Narrower toolbar/card arrangement. | `760px`, `761px` | KEEP | `frontend/src/views/Admin.vue` |
| Shared Admin toolbars | Phone Portrait / `761–767px` | Wider three-part toolbar arrangement within Phone Portrait. | `761px`, `768px` | KEEP | `frontend/src/views/Admin.vue` |
| Shared Admin shell/dialogs | Tablet Portrait / `768–1023px` | Tablet Portrait shell/table overflow and labeled review-dialog action treatment; surface-specific card rules continue to apply. | `768px` | KEEP | `frontend/src/views/Admin.vue` |
| User/notification management | Tablet Portrait / `768–1023px` | Responsive card/list representation; PrimeVue stack boundaries use `1023px`. | `1024px` expressed by `max-width:1023px` | KEEP | `frontend/src/views/Admin.vue` |
| User/notification management | Tablet Landscape / `1024–1399px` | May return to the surface's table representation where no narrower surface rule overrides it. | `1024px` | KEEP | `frontend/src/views/Admin.vue` |
| Course/category management | Tablet Portrait / `768–1023px` | Dedicated tablet card geometry. | `768px`, `1024px` | KEEP | `frontend/src/views/Admin.vue` |
| Course/category management | Tablet Landscape / `1024–1399px` | Tablet card geometry with the category layout refinement beginning at `1024px`. | `1024px`, `1400px` | KEEP | `frontend/src/views/Admin.vue` |
| Course/category management | Desktop / `>=1400px` | Wide desktop DataTables replace course/category cards. | `1400px` | KEEP | `frontend/src/views/Admin.vue` |
| Review/trash/report/slogan surfaces | Phone Portrait / `0–767px` | Responsive cards with selected internal subranges through `640px`. | `640px`, `1400px`; lower side currently written as `1399px` or `1399.98px` | KEEP | `frontend/src/views/Admin.vue`; `frontend/src/style.css`; `frontend/src/components/admin/ReportManagementPanel.vue`; `frontend/src/components/admin/HomepageSloganManagementPanel.vue` |
| Review/trash/report/slogan surfaces | Tablet Portrait / `768–1023px` | Responsive cards; selected metadata layouts change from `900px`. | `900px`, `1400px`; lower side currently written as `1399px` or `1399.98px` | KEEP | same sources |
| Review/trash/report/slogan surfaces | Tablet Landscape / `1024–1399px` | Responsive cards with the wider metadata arrangements. | `900px`, `1400px`; lower side currently written as `1399px` or `1399.98px` | KEEP | same sources |
| Review/trash/report/slogan surfaces | Desktop / `>=1400px` | Wide table composition and desktop-specific table/action ordering. | `1400px` | KEEP | same sources |

Within the Phone Portrait review-card range, the Admin review application cards
for `新課程 / 新分類考古申請` and `既有課程考古申請` reuse the existing `480px`
Feature Breakpoint. At `width < 480px`, each card keeps its actual action set in
one icon-only row. At `width >= 480px && width < 641px`, the same actions remain
in one labeled icon-and-text row. Card metadata stays above the action controls
throughout `width < 641px`. The shared threshold is based on measured fit of the
worst-case five-action row and is owned only by these Admin review application
cards; it does not change Trash responsive behavior.

The existing `1399px`, `1399.98px`, and `1400px` notation remains unchanged.
It expresses the approved Tablet Landscape to Desktop transition and is not a
separate set of Major Breakpoints.

### About Us, PDF Preview, and routes without Feature Breakpoints

| Feature | Major Class / explicit px range | Current behavior or transition purpose | Owning Feature Breakpoint(s) | Status | Evidence |
| --- | --- | --- | --- | --- | --- |
| About Us | Phone Portrait / `0–640px` | Header/actions stack and content spacing adjusts. | `640px` | KEEP | `frontend/src/views/AboutUs.vue` |
| About Us | Phone Portrait / `641–767px` | Default content/action arrangement. | `640px` | KEEP | `frontend/src/views/AboutUs.vue` |
| About Us | Tablet Portrait / `768–1023px` | Same default content/action Feature Class. | `640px` | KEEP | `frontend/src/views/AboutUs.vue` |
| About Us | Tablet Landscape / `1024–1399px` | Same default content/action Feature Class. | `640px` | KEEP | `frontend/src/views/AboutUs.vue` |
| About Us | Desktop / `>=1400px` | Same default content/action Feature Class. | `640px` | KEEP | `frontend/src/views/AboutUs.vue` |
| PDF Preview / discussion | Phone Portrait / `0–767px` | The narrow interaction branch closes the persistent discussion panel and uses modal discussion behavior. | `768px` | KEEP | `frontend/src/components/PdfPreviewModal.vue` |
| PDF Preview / discussion | Tablet Portrait / `768–1023px` | Persistent discussion side-panel behavior is available. | `768px` | KEEP | `frontend/src/components/PdfPreviewModal.vue` |
| PDF Preview / discussion | Tablet Landscape / `1024–1399px` | Same persistent discussion side-panel Feature Class. | `768px` | KEEP | `frontend/src/components/PdfPreviewModal.vue` |
| PDF Preview / discussion | Desktop / `>=1400px` | Same persistent discussion side-panel Feature Class. | `768px` | KEEP | `frontend/src/components/PdfPreviewModal.vue` |
| Login Callback | All Major Classes | No meaningful feature-owned viewport transition; inherits shared application layout. | none | NO FEATURE BREAKPOINT | `frontend/src/views/LoginCallback.vue` |
| Not Found | All Major Classes | No meaningful feature-owned viewport transition; inherits shared application layout. | none | NO FEATURE BREAKPOINT | `frontend/src/views/NotFound.vue` |
| Development login | All Major Classes | No meaningful feature-owned viewport transition found; development-only route inherits shared layout. | none | NO FEATURE BREAKPOINT | `frontend/src/views/NthuDevLogin.vue`; `frontend/src/router/index.js` |

## The 1400px product rationale

### Owner-supplied product rationale

`1400px` is the approved Tablet Landscape to Desktop Major Breakpoint. The owner
intentionally selected it so prior large 13-inch-class tablet landscape design
targets remain on the Tablet Landscape side and Desktop begins at `>=1400px`.
This is product rationale about viewport/interface width; the application does
not detect a 13-inch tablet.

### Repository corroboration

Current Admin code keeps course/category and other wide-table surfaces in their
responsive card representations below `1400px` and enables their Desktop table
representations at `>=1400px`. Local history also contains commit
`0ce1d0b55194093aeea01d2a556ca54e88bed9d6` (`fix: extend course card layouts
across iPad viewports`), which moved the course/category wide-table transition
from `1200px` to `1400px` and added the current `1024–1399px` refinement.

Repository evidence corroborates the intended 1400px behavior. The more
specific historical hardware rationale above remains owner-supplied product
context rather than a claim made by runtime code.

## Container Breakpoint policy

Container Breakpoints are component-owned and outside the Major Class and
Feature Class viewport taxonomy.

- Never infer a Major Class from a Container Breakpoint.
- Never call a Container Breakpoint a Major Breakpoint or Feature Breakpoint.
- Do not move a Container Breakpoint merely because a Major Breakpoint changes.
- A component may enter a container-responsive layout at different viewport
  widths depending on its parent, sidebar, dialog, or panel allocation.

Important current Container Breakpoints include:

| Container Breakpoint | Owning component/purpose | Evidence |
| --- | --- | --- |
| `32rem` | Archive course-header summary arrangement | `frontend/src/views/Archive.vue` |
| `52rem`, `34rem` | Archive filter-grid composition | `frontend/src/views/Archive.vue` |
| `680px` | Personal Settings display-form composition | `frontend/src/views/PersonalSettings.vue` |
| `680px` | Wish Pool wide horizontal header to title-above/two-column action composition | `frontend/src/components/WishPool.vue` |
| `1024px` | Wish Pool native-scrolling to camera/panning interaction | `frontend/src/utils/wishHoneycombLayout.js`; `frontend/src/components/WishPool.vue` |
| `640px` | Notification Center content composition | `frontend/src/components/NotificationCenterModal.vue` |
| `640px` | User duration chart composition | `frontend/src/components/UserOnlineDurationChart.vue` |
| `320px` | Archive discussion panel composition | `frontend/src/components/ArchiveDiscussionPanel.vue` |
| `640px` | Admin insights card composition | `frontend/src/views/Admin.vue` |
| `1080px` | Homepage slogan management composition | `frontend/src/components/admin/HomepageSloganManagementPanel.vue` |
| `62rem`, `42rem`, `34rem`, `25rem`, `20rem` | Report section/filter/card composition | `frontend/src/style.css`; `frontend/src/components/admin/ReportManagementPanel.vue` |

For the Wish Pool header/action Container Breakpoint, `680px` is the lowest
audited comfortable size for the wide horizontal header. At or below `680px`,
the title remains above two equal-width action columns. This removes the
Archive `1025px` sidebar transition's former wide-to-narrow-to-wide header
oscillation; the narrow grid was verified across the audited narrow range.
Archive retains independent ownership of its unchanged `1025px` Feature
Breakpoint.

For the Wish Pool interaction Container Breakpoint:

- **Owner:** Wish Pool / `.wish-pool-stage`.
- **Measurement:** `.wish-pool-stage.clientWidth`, supplied through its
  `ResizeObserver`.
- **Semantics:** `<1024px` uses native scrolling; `>=1024px` uses
  camera/panning.
- **Purpose:** select the interaction model without coupling it to viewport
  Major Classes or Feature Classes.
- **Rationale:** camera/panning at an exact measured `1024px` stage width was
  verified with mouse and proportional touch interaction. No concrete UX value
  was found for retaining an inclusive one-pixel native-only boundary.

## Responsive utility authority

- Existing production responsive utility prefixes remain unchanged.
- Current production `md:` usage is compatible because Tailwind and PrimeFlex
  both resolve `md` to `768px` in the current stack.
- Framework `lg` and `xl` names MUST NOT be used as substitutes for project
  Major Classes; Tailwind and PrimeFlex assign them different values.
- New structural Major Breakpoint logic MUST follow this contract and explicit
  `768px`, `1024px`, and `1400px` semantics rather than assuming a framework
  `lg` or `xl` means Tablet Landscape or Desktop.
- This contract does not authorize removing or migrating Tailwind or PrimeFlex.

## Responsive QA governance

The baseline Representative Viewports are:

| Major Class | Representative Viewport(s) |
| --- | --- |
| Phone Portrait | `390×844` |
| Tablet Portrait | `834×1210` |
| Tablet Landscape | `1024×768`, `1280×800` |
| Desktop | `1440×900` |

These are QA and acceptance samples, not breakpoints and not device detection.
Reuse them when they exercise the affected Feature Class.

Exact `B-1`, `B`, and `B+1` coverage is required proportionately when:

- adding or moving a Major Breakpoint;
- adding or moving a structural Feature Breakpoint;
- exact-boundary behavior is high-risk;
- CSS and JavaScript jointly control the responsive mode; or
- a known boundary inconsistency is under review.

It is not automatically required for every cosmetic threshold change.
