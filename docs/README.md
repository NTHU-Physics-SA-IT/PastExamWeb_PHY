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

Decision Records use the separate status vocabulary defined in the
[Decision Record index](decisions/README.md). In particular, a `Superseded`
Decision Record is retained rationale that defers to its linked replacement;
it is not current operating authority merely because this index retains it.

## Authority map

| Source | Authority | Status | Notes |
| --- | --- | --- | --- |
| [`../README.md`](../README.md) | Public project overview | Active | Not a complete internal runbook. |
| [`../AGENTS.md`](../AGENTS.md) | Repository Agent constraints | Active | Applies to Agent work in this repository. |
| [`../CONTRIBUTING.md`](../CONTRIBUTING.md) | Human contribution, PR, CI, and release gates | Active | Human contributor workflow. |
| [`../.agents/skills/pastexam-web/SKILL.md`](../.agents/skills/pastexam-web/SKILL.md) | PastExamWeb_PHY task routing and workflow | Active | Does not store project facts; follows `AGENTS.md` and canonical documents. |
| [`development/local-environment.md`](development/local-environment.md) | Local environment identities and safe Compose boundaries | Active | Canonical local environment contract; not a recovery runbook. |
| [`development/backend-runtime-recovery.md`](development/backend-runtime-recovery.md) | Backend runtime diagnosis, controlled restart eligibility, and clean-start acceptance | Active | The checker is read-only; restart remains separately authorized. |
| [`development/code-organization.md`](development/code-organization.md) | Code responsibility and pattern consistency | Active | Records current structure and intended ownership direction. |
| [`development/i18n.md`](development/i18n.md) | Frontend translation completeness, interpolation, and localization contract | Active | Owns locale-copy rules; UI guidelines own presentation, validation owns verification policy, and the Skill owns task routing. |
| [`development/feature-development-workflow.md`](development/feature-development-workflow.md) | Feature and behavior-change planning, implementation, and test-design workflow | Active | Procedural authority; does not store product contracts or replace validation, Domain, UI, migration, or production guidance. |
| [`development/collaboration-and-conflict-resolution.md`](development/collaboration-and-conflict-resolution.md) | Parallel-development reconciliation and semantic-conflict workflow | Active | Current procedure for target refresh, PR and Decision review, conflict classification, and safe integration. |
| [`development/validation.md`](development/validation.md) | Risk-proportional verification and CI completion policy | Active | Canonical validation budget, retry, and reporting rules. |
| [`development/permanent-deletion-reconciler.md`](development/permanent-deletion-reconciler.md) | Dedicated permanent-deletion reconciler operation | Active | Code is deployable but production activation remains separately authorized. |
| [`runbooks/coordination.md`](runbooks/coordination.md) | Protected integration coordination lifecycle and recovery procedure | Active | Operational authority for ADR-0013; ordinary main remains coordination-free. |
| [`runbooks/trusted-activation.md`](runbooks/trusted-activation.md) | Historical heavy Trusted Activation procedure | Historical | Superseded by ADR-0013; never use its obsolete rehearsal identity or manual issuance flow. |
| [`development/vite8-playwright-readiness-research-archive.md`](development/vite8-playwright-readiness-research-archive.md) | Vite 8 / Playwright readiness research evidence | Historical | Background evidence only; ADR-0009 owns the durable current decision and operational authority. |
| [`development/ordinary-product-postmerge-equivalent-research-archive.md`](development/ordinary-product-postmerge-equivalent-research-archive.md) | Ordinary-product coordination postmerge Equivalent research evidence | Historical | Background evidence only; ADR-0010 owns the durable current decision and operational authority. |
| [`development/protected-coordination-postmerge-equivalent-research-archive.md`](development/protected-coordination-postmerge-equivalent-research-archive.md) | Protected coordination postmerge Equivalent research evidence | Historical | Background evidence only; ADR-0014 owns the exact-state operating decision. |
| [`decisions/README.md`](decisions/README.md) | Decision Record index, status rules, and durable design history | Active | Accepted records preserve scoped rationale and invariants; superseded records are historical rather than operating authority. |
| [`../scripts/run-isolated-backend-tests.py`](../scripts/run-isolated-backend-tests.py) | Guarded local isolated PostgreSQL test execution | Active tool | Direct Docker runner; no Compose or persistent test service. |
| [`../scripts/check-backend-runtime.py`](../scripts/check-backend-runtime.py) | Read-only backend source/runtime/service/data classification | Active tool | Requires exact container IDs and explicit backend source paths. |
| [`ui/guidelines.md`](ui/guidelines.md) | UI presentation and responsive consistency | Active | Canonical UI-level decisions; Domain meaning is linked, not duplicated. |
| [`ui/responsive-layout-contract.md`](ui/responsive-layout-contract.md) | Viewport taxonomy, responsive breakpoint authority, feature-owned ranges, container-query separation, and responsive QA governance | Active | Canonical responsive governance; intentional Feature Class exceptions remain explicitly recorded. |
| [`domain/README.md`](domain/README.md) | Domain terminology, evidence labels, and contract map | Active | Entry point for product behavior contracts. |
| [`domain/entity-relationships.md`](domain/entity-relationships.md) | Entity ownership, grouping, and lifecycle relationships | Active | Distinguishes current implementation from intended product relations. |
| [`domain/state-transitions.md`](domain/state-transitions.md) | Domain states, authorization, visibility, and business errors | Active | Canonical state and action contract. |
| [`domain/notifications-and-side-effects.md`](domain/notifications-and-side-effects.md) | Notifications, transactions, storage, and external effects | Active | Canonical side-effect and deletion-result contract. |
| [`domain/permanent-deletion.md`](domain/permanent-deletion.md) | Durable permanent-deletion workflow and exact storage identity | Active | Durable Trash deletion and the dedicated Stage 5F-E reconciler are implemented; production worker activation is deferred. |
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
- Active operating documents own current procedure. Accepted Decision Records
  preserve durable rationale and invariants within scope; they do not silently
  override higher machine-enforced contracts or current operating documents.
- Product or Domain behavior changes must eventually update the Domain contract
  and its tests together.
- Protect the public design and stable links of the root `README.md`.
