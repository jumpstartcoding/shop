#!/usr/bin/env bash
# Dump the database to a compressed custom-format file and check it can be read back.
#
#   DATABASE_URL=postgresql://... infra/scripts/backup-dump.sh shop.dump
#
# Used by .github/workflows/backup.yml (inside the postgres:18 image so pg_dump is never
# older than the server). Fails loudly if the dump is empty or unreadable.
set -euo pipefail

out="${1:?usage: backup-dump.sh OUTPUT_FILE}"
: "${DATABASE_URL:?DATABASE_URL is not set}"

# The app's SQLAlchemy URL names its driver; pg_dump wants a plain libpq URL.
url="${DATABASE_URL/postgresql+psycopg:\/\//postgresql://}"
url="${url/postgres:\/\//postgresql://}"

pg_dump "$url" --format=custom --compress=9 --no-owner --no-privileges --file="$out"

# A dump that pg_restore can list is structurally sound; check the core tables are in it.
toc="$(pg_restore --list "$out")"
for table in businesses customers vehicles work_orders estimates invoices payments \
  document_versions authorizations audit_logs alembic_version; do
  if ! grep -q "TABLE DATA public ${table} " <<<"$toc"; then
    echo "Backup check failed: table ${table} is missing from the dump." >&2
    exit 1
  fi
done

echo "Dump OK: $(du -h "$out" | cut -f1), $(grep -c 'TABLE DATA' <<<"$toc") tables, sha256 $(sha256sum "$out" | cut -c1-16)"
