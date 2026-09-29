#!/usr/bin/env bash
set -euo pipefail

for f in pagila-schema.sql pagila-data.sql; do
  if [[ ! -f "/pagila/$f" ]]; then
    echo "/pagila/$f is missing: run \`make fetch-data\` (or \`make up\`) on the host first" >&2
    exit 1
  fi
done

echo "loading pagila schema + data"
psql -v ON_ERROR_STOP=1 --no-psqlrc -q -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f /pagila/pagila-schema.sql
psql -v ON_ERROR_STOP=1 --no-psqlrc -q -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f /pagila/pagila-data.sql
