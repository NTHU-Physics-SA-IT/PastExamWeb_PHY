# Contributing

## Pull requests

The repository currently uses a direct feature-to-`main` workflow. Open pull
requests against `main`; the `Validate PR base branch` check rejects other base
branches. There is no `dev` integration branch.

## Production candidates

CI builds and tests every pushed branch. Image publication remains limited to
`main`. Production candidate preparation is additionally gated by the
`PRODUCTION_DEPLOY_ENABLED` repository variable and the
protected `production` GitHub Environment.

Candidate preparation creates a new checkout under `/opt/pastexam-releases`
and validates its Compose configuration. It does not update the active dirty
checkout under `/opt/PastExamWeb_PHY`, start a new production stack, or switch
traffic. Production activation requires a separate, explicitly approved
operation after candidate evidence has been reviewed. See
[`docs/production-deployment.md`](docs/production-deployment.md) for the
candidate manifest, configuration boundary, and activation blockers.
