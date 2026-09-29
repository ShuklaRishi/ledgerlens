#!/usr/bin/env bash
# Download the Pagila sample database at a pinned commit and verify checksums.
#
# Pinned to tag pagila-v3.1.0: payment/rental dates are in 2022 and the dump runs on
# Postgres 16. Pagila v4.x targets Postgres 18 (uuidv7() defaults, pg_partman).
# Licence: MIT-style, (c) Devrim Gündüz; fetched alongside as db/pagila/LICENSE.txt.
set -euo pipefail

REF="fef9675714cfba1756df4719b5e36075a7ddf90e" # pagila-v3.1.0
BASE="https://raw.githubusercontent.com/devrimgunduz/pagila/${REF}"
DIR="$(cd "$(dirname "$0")" && pwd)/pagila"
mkdir -p "$DIR"

sha256() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1
  else shasum -a 256 "$1" | cut -d' ' -f1; fi
}

while read -r expected file; do
  if [[ -f "$DIR/$file" && "$(sha256 "$DIR/$file")" == "$expected" ]]; then
    continue
  fi
  echo "fetching $file"
  curl -fsSL "$BASE/$file" -o "$DIR/$file.tmp"
  if [[ "$(sha256 "$DIR/$file.tmp")" != "$expected" ]]; then
    rm -f "$DIR/$file.tmp"
    echo "checksum mismatch for $file" >&2
    exit 1
  fi
  mv "$DIR/$file.tmp" "$DIR/$file"
done <<'EOF'
8ce358e4c8014087b85296694a0893887bd7a4190e3ce407f2721b86b98e5707 pagila-schema.sql
fb81bec377687c83e11d2a24916ae28656d85550bf0ada798305bf7e2af9823b pagila-data.sql
516e7dac679ac1eeb62d5614b01c4e7318154e9a147377d6264954215997ff38 LICENSE.txt
EOF

echo "pagila ${REF:0:10} ready in db/pagila"
