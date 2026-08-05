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

## What backup_db.sh/restore_db.sh deliberately do NOT do

- No automatic scheduling (see "Scheduling" above — this is an
  environment-specific operator decision, not something to hardcode here).
- No off-host upload (S3/GCS/etc.) — `BACKUP_DIR` is a local path; wire
  offsite replication at the infrastructure layer (e.g. a sync job on
  `BACKUP_DIR`, or point it directly at a mounted network volume).
- No encryption-at-rest of the dump file itself — rely on the storage
  layer's own encryption (encrypted EBS volume, encrypted S3 bucket, etc.)
  if the backup destination requires it.
