#!/usr/bin/env bash
# Evidence script (Audits 06/13/14): migration drills on a THROWAWAY database.
# Never touches gridiron_dev. Run from backend/.
#  1. empty DB -> upgrade head      2. alembic check (ORM vs schema drift)
#  3. downgrade base -> upgrade head (x2)   4. stairway: each revision down/up/down
set -euo pipefail
DB=gridiron_audit_empty
docker exec crr2906-db-1 sh -c "psql -U \"\$POSTGRES_USER\" -d postgres -qc 'DROP DATABASE IF EXISTS $DB' -c 'CREATE DATABASE $DB'"
export DATABASE_URL=$(grep -E "^DATABASE_URL=" .env | cut -d= -f2- | sed "s#/gridiron_dev#/$DB#")
A=.venv/bin/alembic
$A upgrade head && echo "UPGRADE FROM EMPTY: ok ($($A current | tail -1))"
$A check 2>&1 | grep "INFO  \[alembic.autogenerate" | sed -E 's/.*compare\.[a-z]+\] //' \
  | grep -vE "removed index|added index|removed unique constraint|added unique constraint" || true
for i in 1 2; do $A downgrade base && $A upgrade head && echo "ROUND TRIP $i: ok"; done
n=$($A history | grep -c -- '->')
for i in $(seq 1 "$n"); do $A downgrade -1 && $A upgrade +1 && $A downgrade -1; done
echo "STAIRWAY: ok over $n revisions"
docker exec crr2906-db-1 sh -c "psql -U \"\$POSTGRES_USER\" -d postgres -qc 'DROP DATABASE $DB'"
