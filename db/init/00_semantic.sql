-- pgvector lives in its own schema so `public` stays pure Pagila: the agent's
-- table/column allowlist is read from information_schema for `public` only, and the
-- function-level REVOKE in 20_roles.sh can't accidentally strip pgvector's operators.
CREATE SCHEMA semantic;
CREATE EXTENSION IF NOT EXISTS vector SCHEMA semantic;
