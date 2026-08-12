# Development NTHU OAuth Mock Login

Status: Development-only

This harness exists for localhost authentication QA. It mocks only the NTHU provider profile retrieval. OAuth state validation, the canonical callback, persisted access policy, UUID identity resolution, PostgreSQL user lifecycle, Redis login handoff, one-time exchange, JWT issuance, and frontend callback remain production code.

## Security boundary

The backend requires both `APP_ENVIRONMENT=development` (or `test`) and `NTHU_DEV_MOCK_ENABLED=true`. The flag defaults to false. Enabling it with a production environment fails startup. Production Compose does not set either the backend or frontend mock flag.

The frontend route `/dev/nthu-login` is compiled into the route table only when Vite is in development mode and `VITE_NTHU_DEV_MOCK_ENABLED=true`. The backend accepts only seven fixed profile keys. It has no arbitrary UUID, userid, email, `inschool`, or JSON input.

## Local use

Set `NTHU_DEV_MOCK_ENABLED=true` in the canonical `pastexam-dev` Compose environment and recreate the backend and frontend containers. Open `http://localhost:8080/dev/nthu-login`. Disable it by removing the value or setting it to `false`, then recreate those two services.

The backend stores opaque `dev_` provider codes in a separate Redis namespace for 90 seconds and consumes them atomically once. A disabled or expired `dev_` code fails closed and never reaches the real NTHU token endpoint.

## Fixed profiles

| Key | userid | UUID | Affiliation | Department | inschool |
| --- | --- | --- | --- | --- | --- |
| `physics` | `112022123` | `dev-nthu-physics-0001` | `STANDARD_STUDENT` | `022` | true |
| `other_department` | `112025123` | `dev-nthu-other-0001` | `STANDARD_STUDENT` | `025` | true |
| `special_userid` | `X1106099` | `dev-nthu-special-0001` | `UNRESOLVED` | unknown | true |
| `missing_userid` | null | `dev-nthu-missing-0001` | `UNRESOLVED` | unknown | true |
| `staff_allowed` | `W90001` | `dev-nthu-staff-allowed-0001` | `STAFF` | unknown | true |
| `staff_unlisted` | `W90002` | `dev-nthu-staff-unlisted-0001` | `STAFF` | unknown | true |
| `not_inschool` | `112022124` | `dev-nthu-inactive-0001` | `STANDARD_STUDENT` | `022` | false |

All emails use `.invalid` and all display names start with `[DEV]`. Successful logins intentionally create or reuse normal external users in the local database. Denied profiles must not create or mutate users.

## Affiliation classification

The centralized backend classifier derives `STANDARD_STUDENT`, `STAFF`, or
`UNRESOLVED` from the current provider userid and department catalog. Staff-like
formats are explicitly best-effort display classifications; they are not
persisted account types. Non-standard identifiers such as `X1106099` remain
unresolved instead of receiving a special-student inference.

Display classification is not authorization. In particular, a `STAFF` label
does not grant login access: custom scope still requires that exact userid in
the staff allowlist. `UNRESOLVED` profiles fail closed in custom scope, while
`all_nthu` continues to allow them when `inschool=true`. `inschool=false`
always denies first.

## Policy checks

- `all_nthu` allows every `inschool=true` profile and denies `not_inschool`.
- custom `022` with staff disabled allows only `physics`.
- custom `022` plus staff allowlist `W90001` allows `physics` and
  `staff_allowed`; unresolved profiles remain denied.
- staff-only `W90001` allows only `staff_allowed` among the student/staff cases.

Restore local QA policy to `all_nthu`, no departments, staff access `none`, and
no staff userids when testing is complete.

## Local administrator QA fixture

Set `DEV_QA_ADMIN_PASSWORD` only in the command environment, then run
`python -m app.scripts.ensure_local_admin_qa` inside the development backend.
The command refuses non-development/test environments and missing passwords,
checks the database schema before writing, and creates or updates only the
exact `dev-local-admin` / `dev-local-admin@example.invalid` fixture. Browser QA
then uses the normal local `/auth/login` flow; there is no development login
bypass route and the password is not stored in the repository.
