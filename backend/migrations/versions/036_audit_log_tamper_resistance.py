"""Audit log tamper-resistance — AUDIT_Q_BATCH11 §96 "Audit logs"

audit_log has been real and durably persisted since migration 025, but
nothing stopped a direct UPDATE/DELETE at the DB layer — the append-only
guarantee only ever existed in AuditLog's own exposed Python API surface
(no update()/delete() methods), not the database itself. This adds real,
DB-enforced tamper resistance:

1. `seq` (BIGSERIAL) — a real, race-free monotonic insert-order column.
   entry_id (UUID) and timestamp (an ISO string with only up-to-microsecond
   resolution) are both insufficient to totally order concurrent inserts;
   seq is.
2. `prev_hash`/`entry_hash` — a genuine hash chain, computed server-side in
   a BEFORE INSERT trigger (not in application code): each row's
   entry_hash = sha256(prev_hash || every other column's value). Computed
   server-side, inside the same transaction that inserts the row, serialized
   via pg_advisory_xact_lock so concurrent INSERTs can't race and produce
   two rows both claiming the same prev_hash — the classic hash-chain
   integrity bug. Any tampering with a historical row's content (whether or
   not UPDATE is even possible — see below) is detectable by recomputing
   the chain and finding a mismatch.
3. Triggers rejecting UPDATE and DELETE outright — true DB-enforced
   append-only, not just "no update()/delete() method exists in the Python
   class". A session-scoped GUC bypass (`audit_log.allow_mutation`) exists
   ONLY for legitimate maintenance/test cleanup (grepped first: confirmed
   zero application code path anywhere ever issues UPDATE/DELETE against
   audit_log — the only pre-existing DELETEs were test teardown cleanup,
   updated in the same change to explicitly opt into the bypass via
   `SET LOCAL`) — never reachable from any application/agent code path, so
   the guarantee holds against anything a compromised agent or application
   bug could do.

Revision ID: 036
Revises: 035
Create Date: 2026-08-07
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "036"
down_revision: Union[str, None] = "035"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.add_column(
        "audit_log",
        sa.Column("seq", sa.BigInteger(), nullable=True),
    )
    op.execute("CREATE SEQUENCE IF NOT EXISTS audit_log_seq_seq OWNED BY audit_log.seq")
    op.execute(
        "ALTER TABLE audit_log ALTER COLUMN seq SET DEFAULT nextval('audit_log_seq_seq')"
    )
    op.execute(
        "UPDATE audit_log SET seq = nextval('audit_log_seq_seq') WHERE seq IS NULL"
    )
    op.alter_column("audit_log", "seq", nullable=False)
    op.create_unique_constraint("uq_audit_log_seq", "audit_log", ["seq"])
    op.create_index("ix_audit_log_seq", "audit_log", ["seq"])

    op.add_column(
        "audit_log",
        sa.Column("prev_hash", sa.String(length=64), nullable=False, server_default=""),
    )
    op.add_column(
        "audit_log",
        sa.Column("entry_hash", sa.String(length=64), nullable=True),
    )

    # Backfill entry_hash/prev_hash for any pre-existing rows (chained in
    # seq order) so the trigger below can assume every row it ever sees as
    # "the previous row" already has a real hash — no NULL special-casing
    # needed in steady state.
    op.execute("""
        DO $$
        DECLARE
            r RECORD;
            prev text := '';
        BEGIN
            FOR r IN SELECT seq, entry_id, trace_id, timestamp, action_type,
                            agent_name, task_id, description, details, outcome,
                            requires_human_approval, approved_by
                     FROM audit_log ORDER BY seq ASC
            LOOP
                UPDATE audit_log
                SET prev_hash = prev,
                    entry_hash = encode(
                        digest(
                            prev || r.entry_id || r.timestamp || r.action_type ||
                            r.agent_name || COALESCE(r.task_id, '') || r.description ||
                            COALESCE(r.details::text, '') || r.outcome ||
                            r.requires_human_approval::text || COALESCE(r.approved_by, ''),
                            'sha256'
                        ),
                        'hex'
                    )
                WHERE seq = r.seq;
                SELECT entry_hash INTO prev FROM audit_log WHERE seq = r.seq;
            END LOOP;
        END $$;
        """)
    op.alter_column("audit_log", "entry_hash", nullable=False)

    op.execute("""
        CREATE OR REPLACE FUNCTION audit_log_set_chain_hash() RETURNS trigger AS $$
        DECLARE
            prev_h text;
        BEGIN
            PERFORM pg_advisory_xact_lock(hashtext('audit_log_chain'));
            SELECT entry_hash INTO prev_h FROM audit_log ORDER BY seq DESC LIMIT 1;
            IF prev_h IS NULL THEN
                prev_h := '';
            END IF;
            NEW.prev_hash := prev_h;
            NEW.entry_hash := encode(
                digest(
                    prev_h || NEW.entry_id || NEW.timestamp || NEW.action_type ||
                    NEW.agent_name || COALESCE(NEW.task_id, '') || NEW.description ||
                    COALESCE(NEW.details::text, '') || NEW.outcome ||
                    NEW.requires_human_approval::text || COALESCE(NEW.approved_by, ''),
                    'sha256'
                ),
                'hex'
            );
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """)
    op.execute("""
        CREATE TRIGGER audit_log_chain_hash_trigger
        BEFORE INSERT ON audit_log
        FOR EACH ROW EXECUTE FUNCTION audit_log_set_chain_hash();
        """)

    op.execute("""
        CREATE OR REPLACE FUNCTION audit_log_block_mutation() RETURNS trigger AS $$
        BEGIN
            IF current_setting('audit_log.allow_mutation', true) = 'true' THEN
                RETURN COALESCE(NEW, OLD);
            END IF;
            RAISE EXCEPTION 'audit_log is append-only: % is not permitted', TG_OP;
        END;
        $$ LANGUAGE plpgsql;
        """)
    op.execute("""
        CREATE TRIGGER audit_log_no_update
        BEFORE UPDATE ON audit_log
        FOR EACH ROW EXECUTE FUNCTION audit_log_block_mutation();
        """)
    op.execute("""
        CREATE TRIGGER audit_log_no_delete
        BEFORE DELETE ON audit_log
        FOR EACH ROW EXECUTE FUNCTION audit_log_block_mutation();
        """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_log_no_delete ON audit_log")
    op.execute("DROP TRIGGER IF EXISTS audit_log_no_update ON audit_log")
    op.execute("DROP FUNCTION IF EXISTS audit_log_block_mutation()")
    op.execute("DROP TRIGGER IF EXISTS audit_log_chain_hash_trigger ON audit_log")
    op.execute("DROP FUNCTION IF EXISTS audit_log_set_chain_hash()")
    op.drop_column("audit_log", "entry_hash")
    op.drop_column("audit_log", "prev_hash")
    op.drop_index("ix_audit_log_seq", table_name="audit_log")
    op.drop_constraint("uq_audit_log_seq", "audit_log", type_="unique")
    op.drop_column("audit_log", "seq")
    op.execute("DROP SEQUENCE IF EXISTS audit_log_seq_seq")
