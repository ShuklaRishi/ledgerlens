#!/usr/bin/env bash
# agent_ro: the only role the agent connects with. SELECT on Pagila and the semantic layer,
# nothing else. Read-only is enforced by grants; default_transaction_read_only and the
# statement timeout are a second layer, not the guarantee (a session can SET them off).
set -euo pipefail

psql -v ON_ERROR_STOP=1 --no-psqlrc -q -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -v db="$POSTGRES_DB" \
  -v ro_password="${AGENT_RO_PASSWORD:?AGENT_RO_PASSWORD must be set}" <<'SQL'
-- The Pagila dump ends with GRANT ALL ON SCHEMA public TO PUBLIC, which would let any
-- role create tables. Take CREATE back, and temp tables too.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE TEMPORARY ON DATABASE :"db" FROM PUBLIC;

-- Pagila ships functions, one of them SECURITY DEFINER (rewards_report runs as the
-- owner and creates a table). The agent only needs built-ins from pg_catalog.
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC;

CREATE ROLE agent_ro LOGIN PASSWORD :'ro_password'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION CONNECTION LIMIT 20;
GRANT CONNECT ON DATABASE :"db" TO agent_ro;
GRANT USAGE ON SCHEMA public TO agent_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO agent_ro;

-- Least privilege: the agent never needs staff password hashes or photos.
REVOKE SELECT ON public.staff FROM agent_ro;
GRANT SELECT (staff_id, first_name, last_name, address_id, email, store_id, active, username, last_update)
  ON public.staff TO agent_ro;

-- Embeddings are written by the owner during `make seed`; the agent can only read them.
GRANT USAGE ON SCHEMA semantic TO agent_ro;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA semantic GRANT SELECT ON TABLES TO agent_ro;

ALTER ROLE agent_ro SET default_transaction_read_only = on;
ALTER ROLE agent_ro SET statement_timeout = '15s';
ALTER ROLE agent_ro SET idle_in_transaction_session_timeout = '60s';
SQL

echo "agent_ro created (read-only)"
