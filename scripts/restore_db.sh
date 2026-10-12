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
# Sol A39 (2026-10-12): verify the restore against the manifest written at
# backup time — schema revision, the exact row count of every table and the
# encryption-key fingerprint — instead of only "alembic_version has a row".
MANIFEST="${DUMP_FILE%.dump}.manifest"
if [[ ! -f "$MANIFEST" ]]; then
  ROW_COUNT="$(psql "$PG_DSN" -tAc "SELECT count(*) FROM alembic_version;" 2>/dev/null || echo "")"
  if [[ -z "$ROW_COUNT" ]]; then
    echo "ERROR: restore could not be verified (no manifest, no alembic_version)." >&2
    exit 1
  fi
  echo "WARNING: no manifest next to this backup (made before 2026-10-12);" >&2
  echo "only the schema table could be checked (${ROW_COUNT} row)." >&2
  exit 0
fi

PROBLEMS=0
WANT_REV="$(sed -n 's/^revision=//p' "$MANIFEST")"
GOT_REV="$(psql "$PG_DSN" -tAc 'SELECT version_num FROM alembic_version' 2>/dev/null || echo missing)"
if [[ "$WANT_REV" != "$GOT_REV" ]]; then
  echo "MISMATCH schema revision: backup ${WANT_REV}, restored ${GOT_REV}" >&2
  PROBLEMS=$((PROBLEMS + 1))
fi
TABLES=0
while IFS='=' read -r key want; do
  table="${key#rows.}"
  got="$(psql "$PG_DSN" -tAc "SELECT count(*) FROM public.\"${table}\"" 2>/dev/null || echo missing)"
  TABLES=$((TABLES + 1))
  if [[ "$got" != "$want" ]]; then
    echo "MISMATCH ${table}: backup ${want} rows, restored ${got}" >&2
    PROBLEMS=$((PROBLEMS + 1))
  fi
done < <(grep '^rows\.' "$MANIFEST")

WANT_KEY="$(sed -n 's/^key_fingerprint=//p' "$MANIFEST")"
if [[ -n "$WANT_KEY" ]]; then
  if [[ -z "${CREDENTIAL_ENCRYPTION_KEY:-}" ]]; then
    echo "WARNING: this backup's saved credentials were encrypted with a key;" >&2
    echo "set CREDENTIAL_ENCRYPTION_KEY to the same key or they cannot be read." >&2
  elif [[ "$(printf '%s' "$CREDENTIAL_ENCRYPTION_KEY" | sha256sum | cut -c1-16)" != "$WANT_KEY" ]]; then
    echo "MISMATCH encryption key: CREDENTIAL_ENCRYPTION_KEY is not the key this" >&2
    echo "backup's saved credentials were encrypted with; they will not decrypt." >&2
    PROBLEMS=$((PROBLEMS + 1))
  fi
fi

if [[ $PROBLEMS -gt 0 ]]; then
  echo "Restore finished with ${PROBLEMS} problem(s) — see above." >&2
  exit 1
fi
echo "Restore verified: revision ${GOT_REV}, ${TABLES} tables with the same row counts as the backup."
REPOS_FILE="$(dirname "$DUMP_FILE")/repos_$(basename "${DUMP_FILE%.dump}" | sed 's/^gridiron_//').tar.gz"
if [[ -f "$REPOS_FILE" ]]; then
  echo "Project folders for this backup: ${REPOS_FILE}"
  echo "  restore with: tar -xzf '${REPOS_FILE}' -C \"\$REPOS_DIR\""
fi
