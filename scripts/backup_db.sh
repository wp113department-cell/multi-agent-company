#!/usr/bin/env bash
# backup_db.sh — Postgres backup for the Gridiron Developer Department.
#
# audit_v1.md Release Blocker #7: "No database backup mechanism exists
# anywhere in the codebase." This is that mechanism: a pg_dump-based,
# custom-format (-Fc) backup — chosen over plain SQL because -Fc supports
# selective/parallel restore via pg_restore and is compressed by default.
#
# Zero-hardcoding: every credential/host/path comes from DATABASE_URL (the
# same DSN the app itself uses, per CLAUDE.md) or explicit env overrides —
# nothing is baked into this script.
#
# Usage:
#   DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/dbname ./scripts/backup_db.sh
#   BACKUP_DIR=/var/backups/gridiron BACKUP_RETENTION_COUNT=14 ./scripts/backup_db.sh
#
# Required tool: pg_dump, matching (or newer than) the server's major
# version (the shipped docker-compose db image is pgvector/pgvector:pg16).
set -euo pipefail

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "ERROR: DATABASE_URL is not set. Refusing to guess a connection target." >&2
  echo "Set it to the same DSN the backend app uses, e.g.:" >&2
  echo "  DATABASE_URL=postgresql+asyncpg://gridiron:PASSWORD@127.0.0.1:5432/gridiron_dev" >&2
  exit 1
fi

command -v pg_dump >/dev/null 2>&1 || {
  echo "ERROR: pg_dump not found on PATH. Install the postgresql-client package" >&2
  echo "matching the server's major version (pg16 for the shipped compose db)." >&2
  exit 1
}

# pg_dump/libpq don't understand SQLAlchemy's "+asyncpg"/"+psycopg" driver
# suffix in the scheme — strip it so the same DSN the app uses also works
# unmodified here (no second, drift-prone copy of the connection string).
PG_DSN="$(printf '%s' "$DATABASE_URL" | sed -E 's#^postgresql\+[a-zA-Z0-9]+://#postgresql://#')"

BACKUP_DIR="${BACKUP_DIR:-./backups}"
BACKUP_RETENTION_COUNT="${BACKUP_RETENTION_COUNT:-30}"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"

mkdir -p "$BACKUP_DIR"
OUT_FILE="${BACKUP_DIR}/gridiron_${TIMESTAMP}.dump"
TMP_FILE="${OUT_FILE}.partial"

echo "Starting backup -> ${OUT_FILE}"

# Custom format (-Fc): compressed, supports pg_restore -j (parallel) and
# selective table restore. Dump to a .partial name first and rename only
# on success so a crashed/killed backup never leaves a file that looks
# complete but isn't.
if pg_dump --dbname="$PG_DSN" --format=custom --no-owner --no-privileges \
    --file="$TMP_FILE"; then
  mv "$TMP_FILE" "$OUT_FILE"
else
  echo "ERROR: pg_dump failed — removing partial output." >&2
  rm -f "$TMP_FILE"
  exit 1
fi

# Verification (matches CLAUDE.md's "it ran and passed" bar, not "it should
# have worked"): a real backup file must exist and be non-empty, and
# pg_restore --list must be able to parse its own table of contents.
if [[ ! -s "$OUT_FILE" ]]; then
  echo "ERROR: backup file is empty or missing after pg_dump reported success." >&2
  exit 1
fi
if ! pg_restore --list "$OUT_FILE" >/dev/null 2>&1; then
  echo "ERROR: pg_restore --list could not read the produced backup file — treating as corrupt." >&2
  exit 1
fi

SIZE_HUMAN="$(du -h "$OUT_FILE" | cut -f1)"
echo "Backup verified OK: ${OUT_FILE} (${SIZE_HUMAN})"

# Retention: keep the newest N dumps in BACKUP_DIR, delete the rest. Applies
# only to files this script itself produces (gridiron_*.dump), never touches
# unrelated files an operator may have placed alongside them.
if [[ "$BACKUP_RETENTION_COUNT" -gt 0 ]]; then
  mapfile -t OLD_BACKUPS < <(ls -1t "${BACKUP_DIR}"/gridiron_*.dump 2>/dev/null | tail -n +$((BACKUP_RETENTION_COUNT + 1)))
  for f in "${OLD_BACKUPS[@]:-}"; do
    [[ -n "$f" ]] || continue
    echo "Pruning old backup (beyond retention count ${BACKUP_RETENTION_COUNT}): $f"
    rm -f "$f"
  done
fi

echo "Done."
