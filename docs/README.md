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
| [`../.agents/skills/pastexam-web/SKILL.md`](../.agents/skills/pastexam-web/SKILL.md) | PastExamWeb_PHY task routing and workflow | Active | Does not store project facts; follows `AGENTS.md` and canonical documents. |
| [`development/local-environment.md`](development/local-environment.md) | Local environment identities and safe Compose boundaries | Active | Canonical local environment contract; not a recovery runbook. |
| [`development/code-organization.md`](development/code-organization.md) | Code responsibility and pattern consistency | Active | Records current structure and intended ownership direction. |
| [`development/validation.md`](development/validation.md) | Risk-proportional verification and CI completion policy | Active | Canonical validation budget, retry, and reporting rules. |
| [`ui/guidelines.md`](ui/guidelines.md) | UI presentation and responsive consistency | Active | Canonical UI-level decisions; Domain meaning is linked, not duplicated. |
| [`domain/README.md`](domain/README.md) | Domain terminology, evidence labels, and contract map | Active | Entry point for product behavior contracts. |
| [`domain/entity-relationships.md`](domain/entity-relationships.md) | Entity ownership, grouping, and lifecycle relationships | Active | Distinguishes current implementation from intended product relations. |
| [`domain/state-transitions.md`](domain/state-transitions.md) | Domain states, authorization, visibility, and business errors | Active | Canonical state and action contract. |
| [`domain/notifications-and-side-effects.md`](domain/notifications-and-side-effects.md) | Notifications, transactions, storage, and external effects | Active | Canonical side-effect and deletion-result contract. |
| [`migration-safety.md`](migration-safety.md) | Migration policy and safe operations | Active | Canonical migration safety policy. |
| [`production-deployment.md`](production-deployment.md) | Production candidate, activation, backup, and deployment safety | Active | Canonical production deployment guidance. |
| [`umami-screenshot-automation.md`](umami-screenshot-automation.md) | Umami screenshot automation runbook | Active | Canonical screenshot schedule and asset publication flow. |
| [`governance/codex-skill-security-review.md`](governance/codex-skill-security-review.md) | Codex Skill provenance and security review background | Historical | Not a day-to-day Agent execution policy. |
| [`screenshots/`](screenshots/) | Tracked screenshots used by the public README | Active assets | Keep these paths stable. |

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
