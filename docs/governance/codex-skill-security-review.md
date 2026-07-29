# Codex Skill security review

Reviewed 2026-07-12 before installation. Repository revisions were obtained with read-only `git clone` into an isolated temporary directory; no third-party installer, hook, or repository script was executed during review.

As of 2026-07-24, the reviewed Skills are no longer stored in this repository. They may be installed independently as optional user-level Codex Skills under `$CODEX_HOME/skills` (normally `~/.codex/skills`). The application does not depend on these Skills to build, test, deploy, or operate. This document is retained as a historical security and provenance record.

## Current status

- The canonical repository path is
  `.agents/skills/pastexam-web/SKILL.md`. The Skill is tracked by Git and is
  Active for PastExamWeb_PHY task routing.
- The repository Skill is instruction-only and contains exactly `SKILL.md` and
  `agents/openai.yaml`. It has no scripts, references, assets, MCP dependencies,
  hooks, or network actions.
- Detailed architecture, frontend, backend, and validation guidance now lives
  in the Active canonical documents indexed by `docs/README.md`; the old Skill
  references are not copied into the repository Skill.
- `AGENTS.md` and the Active canonical documents remain the specification
  authorities. The Skill is a workflow router and cannot replace them.
- Following successful repository-branch CI and checksum verification, the
  legacy user-level `pastexam-web` copy was moved intact outside known Skill
  scan roots. No active user-level copy remains at
  `$CODEX_HOME/skills/pastexam-web`.
- `ui-ux-pro-max` remains an optional user-scoped general design reference. It
  is advisory, is not a project contract, and is not part of this migration.
- This stage does not migrate the overall user Skill location from
  `~/.codex/skills/` to `~/.agents/skills/`.
- Repository `.codex/skills/` remains unused and must not be restored as an
  alternative location.
- **Base repository load verification: Passed.** Explicit and implicit runtime
  verification results for the earlier Skill migration are recorded below.

## 2026-07-29 feature-workflow routing update

- Repository Skill routing now includes the Active
  `docs/development/feature-development-workflow.md` procedure for feature,
  behavior, Domain bug-fix, and architectural-refactor work.
- The Skill remains instruction-only. This update adds no scripts, references,
  assets, MCP dependencies, hooks, or network actions.
- `AGENTS.md` and the Active canonical documents remain higher-priority
  authorities; the Skill still only classifies tasks, selects documents,
  confirms gates, and applies stop conditions.
- **Static validation:** Completed on
  `docs/feature-development-workflow`; Markdown, link/path, frontmatter,
  instruction-only structure, authority-boundary, and protected-path checks
  passed.
- **Fresh-session explicit feature-workflow verification:** Pending.
- **Fresh-session implicit feature-workflow verification:** Pending.

The earlier runtime evidence below remains valid for repository discovery and
precedence. It does not claim that this new routing has been exercised in a
fresh session.

## Fresh-session verification

### Explicit trigger

- **Status:** Passed.
- **Skill name:** `pastexam-web`.
- **Runtime source:** `.agents/skills/pastexam-web/SKILL.md`.
- **Repository-local:** Yes.
- **Duplicate active Skill:** None observed.
- **Legacy user Skill:** Not loaded. The old active path was absent, and the
  retained backup was outside the active scan path.
- **Workflow routing:** Conformed to `AGENTS.md` and the Active canonical
  documents.

### Implicit trigger

- **Status:** Passed.
- The user did not explicitly name a Skill, and the runtime selected the
  repository `pastexam-web` workflow automatically.
- The runtime source remained `.agents/skills/pastexam-web/SKILL.md`, with no
  same-named active user workflow observed.
- The legacy user Skill and its retained backup were not loaded.
- `ui-ux-pro-max` remained visible as a user-scoped advisory Skill but was not
  loaded.
- Document routing followed the minimum-necessary principle.
- A hypothetical responsive UI task was correctly classified as
  **Domain impact: No**.

### Verified migration state

- The repository Skill completed static and fresh-session runtime verification
  for the earlier migration scope.
- The 2026-07-29 feature-workflow routing expansion remains pending the
  explicit and implicit fresh-session checks listed above.
- The old user Skill has exited the active scan path.
- The legacy backup is retained outside active scan roots and was not loaded
  by the runtime.
- The repository Skill can now serve as the Active workflow router.
- `AGENTS.md` and the Active canonical documents remain the specification
  authorities.

## nextlevelbuilder/ui-ux-pro-max-skill

- Source: `https://github.com/nextlevelbuilder/ui-ux-pro-max-skill`
- Reviewed component: `.claude/skills/ui-ux-pro-max` (about 1.5 MB), not the npm CLI or other bundled plugins.
- Installed component contains `SKILL.md`, CSV reference data, and three Python scripts using standard-library modules. Search reads only bundled CSV files and writes only when `--persist` is explicitly requested, to the selected output directory.
- No subprocess, shell execution, package install, network request, credential access, install hook, or active Git hook was found in the installed component.
- The upstream CLI was not installed or run. It has npm dependencies and a `prepublishOnly` chain, so it remains outside the trusted project surface.
- Prompt review found no instruction to override higher-priority rules, expose secrets, or silently execute/download content. Project instructions explicitly take precedence over aesthetic recommendations.
- License: MIT. A copy should be retained with any user-level installation because the upstream Skill subdirectory does not contain its own license file.
- Residual risk: CSV guidance is third-party content and can be inaccurate; scripts can create design-system Markdown only when invoked with persistence. Review generated recommendations and diffs before use.

## anthropics/skills `.claude-plugin`

- Source: `https://github.com/anthropics/skills/tree/main/.claude-plugin`
- The target is a marketplace manifest, not one Skill. It references document, example, and Claude API Skill collections.
- The potentially relevant `skills/frontend-design` contains only `SKILL.md` and Apache-2.0 license text, with no scripts, hooks, dependencies, network access, or file/command permissions.
- Other marketplace entries contain scripts that may use subprocesses, package managers, browsers, or network examples. They were not installed because they are unrelated to PastExamWeb_PHY and an all-or-nothing install would unnecessarily widen capability and supply-chain surface.
- `frontend-design` was not copied because its default emphasis on inventing a distinctive visual identity can conflict with this established application's consistency-first requirement. Its useful accessibility, responsive, reduced-motion, purposeful-content, and self-review concepts are represented independently in the project Skill.

## Current installation status

- `ui-ux-pro-max` is an optional, reviewed third-party UI/UX reference Skill in
  the legacy user directory and remains advisory only.
- The repository-local `pastexam-web` replacement is tracked under
  `.agents/skills/pastexam-web/` and is Active as the project workflow source.
- The legacy user-level copy is archived intact under
  `$CODEX_HOME/skill-backups/pastexam-web-legacy-3e776e58dc4a`, outside known
  scan roots, and is not loaded by the runtime.
- Shared project requirements belong in `AGENTS.md` and canonical `docs/`.
  They take precedence and must not be copied into a second Skill policy.
