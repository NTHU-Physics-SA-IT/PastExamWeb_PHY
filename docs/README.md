# Project documentation

## Purpose

The repository root [`README.md`](../README.md) is the public product homepage.
The `docs/` directory contains internal development, Domain, data, and operations
documentation. This file provides the documentation index and authority map.
Each rule or topic should have exactly one canonical source.

## Document status

- **Active:** Currently valid and may be used as an operational or specification
  authority.
- **Historical:** Retained for background and decision history, but not as a
  day-to-day operational authority.
- **Planned:** Intended for future creation, but does not yet exist or is not yet
  in effect.

## Authority map

| Source | Authority | Status | Notes |
| --- | --- | --- | --- |
| [`../README.md`](../README.md) | Public project overview | Active | Not a complete internal runbook. |
| [`../AGENTS.md`](../AGENTS.md) | Repository Agent constraints | Active | Applies to Agent work in this repository. |
| [`../CONTRIBUTING.md`](../CONTRIBUTING.md) | Human contribution, PR, CI, and release gates | Active | Human contributor workflow. |
| [`migration-safety.md`](migration-safety.md) | Migration policy and safe operations | Active | Canonical migration safety policy. |
| [`production-deployment.md`](production-deployment.md) | Production candidate, activation, backup, and deployment safety | Active | Canonical production deployment guidance. |
| [`umami-screenshot-automation.md`](umami-screenshot-automation.md) | Umami screenshot automation runbook | Active | Some outdated descriptions are planned for a later update. |
| [`governance/codex-skill-security-review.md`](governance/codex-skill-security-review.md) | Codex Skill provenance and security review background | Historical | Not a day-to-day Agent execution policy. |
| [`screenshots/`](screenshots/) | Tracked screenshots used by the public README | Active assets | Keep these paths stable. |

## Planned canonical documents

The following paths are **Planned** only. They must not be treated as Active
authority before the files are created and adopted. Update this index when that
happens.

```text
docs/development/local-environment.md
docs/development/code-organization.md
docs/development/validation.md
docs/ui/guidelines.md
docs/domain/README.md
docs/domain/entity-relationships.md
docs/domain/state-transitions.md
docs/domain/notifications-and-side-effects.md
.agents/skills/pastexam-web/SKILL.md
```

## Documentation rules

- Each topic has one canonical document.
- Other documents may summarize and link to the canonical source, but should not
  duplicate its full rules.
- A policy describes constraints and guarantees; a runbook describes concrete
  operating steps.
- Historical documents do not replace current Active documents.
- Product or Domain behavior changes must eventually update the Domain contract
  and its tests together.
- Protect the public design and stable links of the root `README.md`.
