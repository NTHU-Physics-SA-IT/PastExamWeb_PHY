-- Apply as a database owner after creating the separately managed runtime and
-- migrator roles. Names are psql variables; this file contains no credentials.
--
-- psql --set=migrator_role=... --set=runtime_role=... --file this-file

\if :{?migrator_role}
\else
\quit
\endif
\if :{?runtime_role}
\else
\quit
\endif

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO :"runtime_role";
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public
  TO :"runtime_role";
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public
  TO :"runtime_role";
ALTER DEFAULT PRIVILEGES FOR ROLE :"migrator_role" IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO :"runtime_role";
ALTER DEFAULT PRIVILEGES FOR ROLE :"migrator_role" IN SCHEMA public
  GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO :"runtime_role";
