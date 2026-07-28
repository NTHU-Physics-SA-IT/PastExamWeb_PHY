# Codex Skill security review

Reviewed 2026-07-12 before installation. Repository revisions were obtained with read-only `git clone` into an isolated temporary directory; no third-party installer, hook, or repository script was executed during review.

As of 2026-07-24, the reviewed Skills are no longer stored in this repository. They may be installed independently as optional user-level Codex Skills under `$CODEX_HOME/skills` (normally `~/.codex/skills`). The application does not depend on these Skills to build, test, deploy, or operate. This document is retained as a historical security and provenance record.

## Current policy

- The installed Codex version currently loads the legacy user path
  `~/.codex/skills/`; both `pastexam-web` and `ui-ux-pro-max` remain
  user-scoped there.
- The future canonical repository path is
  `.agents/skills/pastexam-web/SKILL.md`. Repository `.codex/skills/` must not
  be restored as an alternative location.
- The project-specific `pastexam-web` migration is a separate fourth-stage
  task. It has not happened yet, and this governance stage does not create or
  disable a Skill.
- User and repository copies with the same `pastexam-web` name must not be
  active simultaneously. The user-scoped copy must be disabled or removed as
  part of the controlled repository migration, after repository loading is
  verified.
- The first repository-local Skill will be instruction-only and contain no
  executable scripts. `AGENTS.md` and the canonical documents under `docs/`
  remain the specification authorities; the Skill only routes an Agent through
  the appropriate workflow and references.
- `ui-ux-pro-max` remains an optional user-scoped general design reference. It
  is not a project contract and is not part of the `pastexam-web` migration.
- This plan does not migrate every user Skill from `~/.codex/skills/` to
  `~/.agents/skills/`. User-scope path normalization, if needed, is a separate
  Codex environment task.

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
- `pastexam-web` is still a user-level workflow Skill in
  `~/.codex/skills/pastexam-web/`. Its repository-local replacement is only
  Planned.
- Shared project requirements belong in `AGENTS.md` and canonical `docs/`.
  They take precedence and must not be copied into a second Skill policy.
