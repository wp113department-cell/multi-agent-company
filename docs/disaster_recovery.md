# Disaster Recovery Runbook

Status: real, tested mechanism (audit_v1.md Release Blocker #7 — "No
database backup mechanism exists anywhere in the codebase"). This
document and the two scripts it references (`scripts/backup_db.sh`,
`scripts/restore_db.sh`) are that mechanism.

## What this covers

- **Postgres data**: `dev_tasks`, `agent_runs`, `memory_embeddings`, chat
  history, LangGraph checkpoints, audit log, everything else in the
  database. Covered by `backup_db.sh`/`restore_db.sh` below.
- **Git worktrees / cloned repos** (`WORKTREES_DIR`, `REPOS_DIR`): NOT
  backed up by these scripts — see "Workspace durability" below. This is
  a real, separate gap: a DB-only restore without also fixing workspace
  durability can resume a graph pointing at a working tree that no
  longer exists.

## Backup

```bash
DATABASE_URL=postgresql+asyncpg://gridiron:PASSWORD@127.0.0.1:5432/gridiron_dev \
  BACKUP_DIR=/var/backups/gridiron \
  BACKUP_RETENTION_COUNT=30 \
  ./scripts/backup_db.sh
```

- Uses `pg_dump --format=custom` (compressed, supports selective/parallel
  restore via `pg_restore`).
- Verifies the produced file is non-empty and that `pg_restore --list` can
  read its own table of contents before declaring success — a `pg_dump`
  that "succeeded" but wrote nothing readable is treated as a failure.
- `BACKUP_RETENTION_COUNT` (default 30) prunes older `gridiron_*.dump`
  files in `BACKUP_DIR`, keeping the newest N.
- Requires `pg_dump` matching (or newer than) the server's major version.
  The shipped `docker-compose.yml` `db` service is `pgvector/pgvector:pg16`
  — if you don't have a matching client installed on the host, run the
  backup from a throwaway container instead:

  ```bash
  docker run --rm --network host \
    -v "$PWD:/workspace" \
    -e DATABASE_URL="$DATABASE_URL" \
    -e BACKUP_DIR=/workspace/backups \
    pgvector/pgvector:pg16 bash /workspace/scripts/backup_db.sh
  ```

### Scheduling

Not scheduled by this codebase (no cron/systemd-timer/CI job is shipped —
that's an operator decision tied to the actual deployment target). Options,
pick one appropriate to your environment:

- A `cron` entry / systemd timer running `backup_db.sh` on the DB host or a
  jump box with network access to Postgres.
- If Postgres is a managed service (RDS, Cloud SQL, etc.), prefer that
  provider's own automated snapshot mechanism as the primary safety net and
  use `backup_db.sh` for portable, provider-independent dumps (e.g. before
  a risky migration, or to move data between environments).
- A CI pipeline job on a schedule, writing to durable off-host storage
  (S3/GCS/etc. — mount or sync `BACKUP_DIR` there; this script itself only
  writes to local disk).

Whichever you choose, treat "backups exist" and "backups have been proven
restorable" as two separate facts — schedule periodic restore drills (see
below), not just periodic backups.

**Built-in option (recommended):** the `backup` service in `docker-compose.yml`
runs `backup_db.sh` every 24 h and keeps the newest 14 dumps. Put the target
folder (on another disk) in the repo-root `.env`, then start it:

```bash
# repo-root .env
GRIDIRON_BACKUP_DIR=/media/you/backupdisk/gridiron
# optional: BACKUP_RETENTION_COUNT=14  BACKUP_INTERVAL_SECONDS=86400

docker compose --profile backup up -d backup
docker logs crr2906-backup-1        # "Backup verified OK: …" each run
```

Verified 2026-10-02: 3 runs at a 20 s test interval, each dump self-verified,
retention pruning works, and a dump made by the service restored into an
empty database (migration 062, all rows).

Alternative: minimal working example (cron on the Docker host, daily at 02:30, 14 kept,
using the same image so no local `pg_dump` is needed — this is exactly how
the 2026-10-02 drill ran the script):

```cron
30 2 * * * cd /path/to/CRR2906 && docker run --rm --network crr2906_default \
  -e DATABASE_URL="postgresql://gridiron:PASSWORD@db:5432/gridiron_dev" \
  -e BACKUP_DIR=/backups -e BACKUP_RETENTION_COUNT=14 \
  -v "$PWD/scripts:/scripts:ro" -v /var/backups/gridiron:/backups \
  --entrypoint bash pgvector/pgvector:pg16 /scripts/backup_db.sh >> /var/log/gridiron-backup.log 2>&1
```

**RPO** = the schedule interval (24 h with the line above). Copy
`/var/backups/gridiron` off the host — a backup on the same disk does not
survive losing that disk.

### Measured drill (production audit 13, 2026-10-02)

| Step | Result |
|---|---|
| `backup_db.sh` (4.2 MB dump, 51 tables) | 3.5 s, self-verified |
| `restore_db.sh` into an empty database | 7.1 s, schema at head (062) |
| Restore into a brand-new Postgres server | OK, 373 tasks, 3 HNSW indexes, pgvector 0.8.6 |
| App started on the restored database | healthy in 7.2 s; login, task list and HNSW vector search work |

**RTO at this data size: under 1 minute** (backup → restore → healthy app ≈ 18 s, plus operator time).

## Restore

```bash
DATABASE_URL=postgresql+asyncpg://gridiron:PASSWORD@127.0.0.1:5432/gridiron_dev \
  ./scripts/restore_db.sh /var/backups/gridiron/gridiron_20260805T120000Z.dump
```

- Interactive by default — requires typing `restore` to confirm (this is
  destructive: `pg_restore --clean --if-exists` drops existing objects in
  the target database first). Pass `--yes` as a second argument for
  scripted/CI restore drills.
- Verifies the dump is readable (`pg_restore --list`) *before* touching the
  target database.
- After restoring, queries `alembic_version` to confirm the schema landed,
  and prints the row count.
- **Always run `alembic upgrade head` immediately after a restore** — the
  dump reflects the schema at backup time; if migrations have shipped
  since then, the restored DB needs to catch up before the app starts.

### Restoring into a fresh/different database

`restore_db.sh` target is whatever `DATABASE_URL` points at — point it at a
new, empty database (not the one you're recovering from) if you want to
verify a backup without touching production, e.g. during a drill:

```bash
createdb -h <host> -U gridiron restore_drill_test
DATABASE_URL=postgresql+asyncpg://gridiron:PASSWORD@<host>/restore_drill_test \
  ./scripts/restore_db.sh /var/backups/gridiron/latest.dump --yes
```

This exact flow (dump the real dev DB, restore into a throwaway
`restore_drill_test` database, compare row counts, drop it) was used to
verify both scripts end-to-end against the real running Postgres instance
before this runbook was written — not just read-through, actually run.

## Full recovery procedure (data loss / corrupted Postgres volume)

1. Provision a fresh Postgres instance (same major version as the lost
   one — check your most recent backup's `pg_restore --list` output if
   unsure, or the `docker-compose.yml` `db` image tag).
2. Set `DATABASE_URL` to point at it.
3. Run `restore_db.sh` with your most recent verified-good backup file.
4. Run `alembic upgrade head` from `backend/` to apply any migrations
   newer than the backup.
5. Restart the backend. On startup it will resume orphan-run recovery
   (`failure_ladder.py`) for any `agent_runs` that were `running` at
   backup time — expect those to transition to `failed` shortly after
   boot, which is correct: their actual worktree state is unknown and
   they cannot be safely resumed (see "Workspace durability" below).
6. Spot-check: `dev_tasks`/`agent_runs` row counts against your last known
   monitoring numbers; `SELECT max(created_at) FROM task_logs;` to confirm
   how much data (if any) was lost between the backup and the incident.

## Workspace durability (`/tmp` gap)

`WORKTREES_DIR` and `REPOS_DIR` (`backend/app/config.py`) default to
`/tmp/gridiron-worktrees` and `/tmp/gridiron-repos` — ephemeral storage
that does not survive a host restart, container recreation, or a routine
`/tmp` cleanup job. `Settings` now hard-fails startup when
`DEPLOYMENT_ENV=production` and either path (or `BG_PROCESS_REGISTRY_PATH`)
is still under `/tmp`, so this can no longer be a silent production
footgun — but it must still be *configured* correctly:

- Point `WORKTREES_DIR`/`REPOS_DIR`/`BG_PROCESS_REGISTRY_PATH` at a
  persistent-volume-backed path (a mounted disk, not container-ephemeral
  storage) in any real deployment.
- A DB restore alone does **not** recover worktree contents — a resumed
  `dev_tasks` row that references a worktree path lost along with the
  volume will show as a missing/inconsistent worktree on next dispatch,
  not a silent success. There is currently no automated worktree
  snapshot/backup in this codebase; the durable-volume requirement above
  is the primary mitigation until one exists.

## Secret rotation

None of these are rotated automatically. (With `SECRETS_MANAGER_ENABLED=true` values can come from AWS Secrets Manager instead of `.env`; rotate them there.) Rotate on staff change, suspected
leak, or on your policy interval. After any change to `backend/.env`,
restart the backend (settings are read at startup).

| Secret | Where | How to rotate | Effect |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | `backend/.env`, **or** saved from Settings in the UI (stored in the `settings` table, which overrides `.env`) | Create a new key in the Anthropic console → update it in Settings (or `.env` + restart) → revoke the old key in the console | Next LLM call uses the new key. If the UI-saved key is set, changing `.env` alone has no effect. |
| `VOYAGE_API_KEY` | `backend/.env` | New key in the Voyage dashboard → `.env` → restart → revoke old | Embeddings use the new key |
| `JWT_SECRET_KEY` | `backend/.env` (≥ 32 chars: `openssl rand -hex 32`) | Replace → restart | **Every session is invalidated**; all users log in again. Only one key is accepted at a time (no overlap window). |
| Postgres password | `docker-compose.yml` / DB server, `DATABASE_URL` in `backend/.env` | `ALTER USER gridiron PASSWORD '…'` → update `DATABASE_URL` → restart backend and workers | Brief 503s ("Database unavailable") until restarted |
| `GITHUB_TOKEN` | `backend/.env`, **or** saved from Settings in the UI (`settings` table, overrides `.env`) | New fine-grained token → update in Settings (or `.env` + restart) → revoke old | Push/PR tools use the new token |
| `CREDENTIAL_ENCRYPTION_KEY` | `backend/.env` (Fernet key) | **Do not just replace it**: it encrypts the UI-saved keys above. Note the saved keys, clear them in Settings, change the key, restart, save them again | Replacing it alone makes the stored keys unreadable |
| `SENTRY_DSN`, webhook URLs | `backend/.env` | Regenerate in the provider → `.env` → restart | — |

Verified on 2026-10-02: no real secret has ever been committed to git
(`What_is/AUDIT_REPORT/evidence/secret_history_scan.py`, 613 commits; the
matches are fake test fixtures and doc placeholders).

## Behaviour during outages (drilled 2026-10-02)

| Failure | What users see | Recovery |
|---|---|---|
| Redis down | Nothing — app keeps working (spend ledger and router cache fall back to in-process) | Automatic when Redis returns |
| Postgres down | `503 "Database unavailable, retry shortly"` + `Retry-After: 5`; `/health` 503; sessions stay valid | Automatic when Postgres returns — no backend restart |
| Backend killed mid-task | — | On restart, the orphaned run is marked failed and its task moves to **blocked** (reason `orphaned`) with a log line; restart the task from the UI |
| LLM key invalid / provider down | Run fails in ~1 s with `502` and the provider's message; one call, no retries on auth errors | After 5 consecutive failures the circuit breaker stops calling the provider until its cooldown ends |

## What backup_db.sh/restore_db.sh deliberately do NOT do

- No automatic scheduling (see "Scheduling" above — this is an
  environment-specific operator decision, not something to hardcode here).
- No off-host upload (S3/GCS/etc.) — `BACKUP_DIR` is a local path; wire
  offsite replication at the infrastructure layer (e.g. a sync job on
  `BACKUP_DIR`, or point it directly at a mounted network volume).
- No encryption-at-rest of the dump file itself — rely on the storage
  layer's own encryption (encrypted EBS volume, encrypted S3 bucket, etc.)
  if the backup destination requires it.
