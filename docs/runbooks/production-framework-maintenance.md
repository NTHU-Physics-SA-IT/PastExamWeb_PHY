# Production framework maintenance

Status: Active

Source of truth for: One-time framework-maintenance bootstrap, install-only
operation, integrity evidence, rotation, and revocation

Related documents:
- [Production deployment safety](../production-deployment.md)
- [Migration safety](../migration-safety.md)

## Separate authority lane

Normal application deployment remains:

```text
Candidate -> Preflight -> Activate
```

Framework maintenance is independent:

```text
reviewed framework source -> main Full CI and immutable candidate
-> protected production approval -> install-only forced command
-> fixed integrity evidence -> stop
```

The maintenance lane never runs preflight, activation, rollback, migration,
backup, Docker lifecycle operations, application image replacement, or a
traffic switch. It shares the `production-activation` concurrency group only
to prevent replacement of framework executables during those operations.

## Steady-state trust boundary

`.github/workflows/install-production-framework.yml` accepts only an exact
lowercase `target_sha`. Before and after protected `production` Environment
approval it requires the target to be fresh current `main`, reuses the
production deployer allowlist, resolves the unique successful exact-main Full
run, and binds its image authority and candidate receipt.

The workflow uses four dedicated `production` Environment secrets:

- `PRODUCTION_FRAMEWORK_MAINTENANCE_HOST`;
- `PRODUCTION_FRAMEWORK_MAINTENANCE_KNOWN_HOSTS`;
- `PRODUCTION_FRAMEWORK_MAINTENANCE_SSH_PRIVATE_KEY`; and
- `PRODUCTION_FRAMEWORK_MAINTENANCE_USER`, whose exact value must be
  `pastexam-framework-maintenance`.

The host account has a locked password, no supplementary groups, no
Docker-group membership, and both its login shell and authorized key are fixed
to
`/usr/local/sbin/pastexam-framework-maintenance-ssh-wrapper`. The wrapper
accepts only `install <sha>` and invokes one digest-bound root helper. The
helper accepts only the SHA, derives
`/opt/pastexam-releases/<sha>`, verifies the root-owned immutable release and
complete checksum manifest, runs its reviewed installer with captured output,
then compares all installed files to immutable sources.

Successful output has exactly this schema; component IDs are allowlisted and
host paths are never emitted:

```json
{
  "schema_version": 1,
  "source_sha": "<40-character-sha>",
  "outcome": "installed",
  "installed_files": [
    {
      "id": "<allowlisted-component-id>",
      "sha256": "<64-character-sha256>",
      "uid": 0,
      "gid": 0,
      "mode": "<expected-mode>"
    }
  ]
}
```

The workflow validates the exact schema before retaining a 90-day artifact.
Raw installer stdout/stderr is never emitted or uploaded.

## Mandatory one-time bootstrap

The old activation wrapper cannot self-bootstrap: it has no installation
command, its account is not in the Docker group, and its sudo authority is
digest-bound to the activation controller. There is no existing reviewed root
maintenance command. Source merge therefore leaves the maintenance lane
**not provisioned**.

In a separately authorized host-governance task, an operator must:

1. generate a dedicated Ed25519 key pair outside the host and retain the
   private key only for later protected-Environment provisioning;
2. place the public key, as one comment-free line, at the fixed root-owned
   mode-`0600` path
   `/root/pastexam-framework-maintenance-authorized-key.pub`;
3. independently confirm the exact current-main immutable candidate and its
   Full-CI/candidate receipt authority;
4. through an explicitly authorized provider-console/root maintenance session,
   invoke the immutable candidate's
   `scripts/bootstrap-production-framework-maintenance-channel.sh` with only
   that exact SHA;
5. verify the account is locked, has only its dedicated primary group, and both
   its login shell and only authorized key resolve to the maintenance wrapper;
6. verify the wrapper/helper digests against the immutable release and validate
   both sudoers files with `visudo`; and
7. provision the four dedicated secrets in the already protected `production`
   Environment without altering its reviewers or self-review policy.

The bootstrap script derives the release path from the SHA, verifies the full
release checksum manifest, and installs only the maintenance account boundary,
wrapper, helper, forced key, and digest-bound sudo rule. It does **not** install
the activation framework. The provider-console/root session is exceptional,
one-time bootstrap authority and must end immediately after verification; it
is not a reusable deployment interface.

This bootstrap has not occurred until host evidence and Environment secret
metadata are separately reviewed. Never describe merged source as an
operational maintenance channel.

## Installation and follow-up

After bootstrap, a separate authorization may dispatch `Install reviewed
production framework` for exact current main. Successful fixed evidence proves
the installed wrapper, controller, engine, validators, backup helpers,
immutable nginx override, and maintenance components match the immutable
candidate. The operation stops after artifact retention.

Installation does not authorize `observe`. A subsequent separately authorized
read-only task may run `status` and `observe` through the activation principal.
Only that live evidence may classify production migration drift.

## Rotation and revocation

Key rotation is a separately authorized bootstrap-governance operation: replace
the fixed public-key file, rerun the exact bootstrap artifact from current
immutable main, verify the forced-key record, then replace the protected
Environment private-key secret. Do not temporarily add an unrestricted key.

To revoke the lane, remove the four Environment secrets first, then use a
separately authorized provider-console/root task to remove the maintenance
authorized key and dedicated sudoers file and lock the account. Validate
sudoers afterward. Do not remove or alter the ordinary activation principal,
controller, or deployment state as part of maintenance-lane revocation.
