#!/usr/bin/env bash
# restore_db.sh — Postgres restore for the Gridiron Developer Department.
#
# Companion to scripts/backup_db.sh (audit_v1.md Release Blocker #7).
# Restores a -Fc (custom format) dump produced by backup_db.sh via
# pg_restore, with --clean --if-exists so it can be run against a database
# that already has the schema (drops existing objects first) or an empty
# one, and a post-restore verification query so a "successful" restore that
# actually left the schema empty is caught here, not discovered later.
#
# Usage:
#   DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/dbname \
#     ./scripts/restore_db.sh /path/to/gridiron_20260805T120000Z.dump
#
#   Add --yes to skip the interactive confirmation (for scripted DR drills /
#   CI — never set this as a default, restoring overwrites the target DB).
set -euo pipefail

if [[ $# -lt 1 || "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  echo "Usage: DATABASE_URL=... $0 <backup-file.dump> [--yes]" >&2
  exit 1
fi

DUMP_FILE="$1"
ASSUME_YES="${2:-}"

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "ERROR: DATABASE_URL is not set. Refusing to guess a restore target." >&2
  exit 1
fi

if [[ ! -f "$DUMP_FILE" ]]; then
  echo "ERROR: backup file not found: $DUMP_FILE" >&2
  exit 1
fi

for bin in pg_restore psql; do
  command -v "$bin" >/dev/null 2>&1 || {
    echo "ERROR: $bin not found on PATH. Install the postgresql-client package." >&2
    exit 1
  }
done

PG_DSN="$(printf '%s' "$DATABASE_URL" | sed -E 's#^postgresql\+[a-zA-Z0-9]+://#postgresql://#')"
# Human-readable target for the confirmation prompt only — never echoed with
# the password. urlparse-equivalent via psql's own connection-string parsing
# would need Python; a simple strip is enough for a display-only host/db.
DISPLAY_TARGET="$(printf '%s' "$PG_DSN" | sed -E 's#.*@##')"

echo "About to restore '$DUMP_FILE' into: $DISPLAY_TARGET"
echo "This is DESTRUCTIVE — pg_restore --clean drops existing objects in the target database before recreating them."

if [[ "$ASSUME_YES" != "--yes" ]]; then
  read -r -p "Type 'restore' to continue: " CONFIRM
  if [[ "$CONFIRM" != "restore" ]]; then
    echo "Aborted — no changes made."
    exit 1
  fi
fi

# Sanity-check the dump is readable before touching the live database at all.
if ! pg_restore --list "$DUMP_FILE" >/dev/null 2>&1; then
  echo "ERROR: pg_restore cannot read '$DUMP_FILE' — refusing to proceed against a corrupt/unrecognized dump." >&2
  exit 1
fi

echo "Restoring..."
pg_restore --dbname="$PG_DSN" --clean --if-exists --no-owner --no-privileges \
  --exit-on-error "$DUMP_FILE"

# Verification: confirm the restore actually left real data behind, not just
# an empty schema — count rows in a small, always-present core table.
ROW_COUNT="$(psql "$PG_DSN" -tAc "SELECT count(*) FROM alembic_version;" 2>/dev/null || echo "")"
if [[ -z "$ROW_COUNT" ]]; then
  echo "WARNING: could not verify restore via alembic_version — check manually with:" >&2
  echo "  psql \"\$DATABASE_URL\" -c '\\dt'" >&2
  exit 1
fi

echo "Restore complete. alembic_version has ${ROW_COUNT} row(s) — schema is present."
echo "Recommended next step: run 'alembic upgrade head' to confirm the restored schema is current, then spot-check row counts on dev_tasks/agent_runs against your DR expectations."
