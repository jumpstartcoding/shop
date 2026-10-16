#!/usr/bin/env bash
# Restore a backup made by backup-dump.sh into an EMPTY database.
#
#   infra/scripts/restore.sh shop-2026-10-15T0717Z.dump "postgresql://user:pass@host/restore_check"
#
# Refuses to touch a database that already has the app's tables, so it can't overwrite
# production by accident. See docs/BACKUPS.md for the full procedure.
set -euo pipefail

dump="${1:?usage: restore.sh DUMP_FILE TARGET_DATABASE_URL}"
target="${2:?usage: restore.sh DUMP_FILE TARGET_DATABASE_URL}"
target="${target/postgresql+psycopg:\/\//postgresql://}"

existing="$(psql "$target" -Atc "select count(*) from information_schema.tables where table_schema = 'public'")"
if [[ "$existing" != "0" ]]; then
  echo "Refusing: the target database already has $existing tables. Restore into an empty database." >&2
  exit 1
fi

pg_restore --no-owner --no-privileges --exit-on-error --dbname="$target" "$dump"

psql "$target" -At <<'SQL'
select 'schema version: ' || version_num from alembic_version;
select 'customers: ' || count(*) from customers;
select 'vehicles: ' || count(*) from vehicles;
select 'work orders: ' || count(*) from work_orders;
select 'invoices: ' || count(*) from invoices;
select 'payments: ' || count(*) from payments;
select 'newest invoice: ' || coalesce(max(created_at)::text, 'none') from invoices;
SQL
echo "Restore finished."
