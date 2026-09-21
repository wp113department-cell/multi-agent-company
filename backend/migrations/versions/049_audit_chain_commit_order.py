"""audit_log hash chain: keep seq order == chain order under concurrent inserts.

Found in verification batch B7 by inserting concurrently against real Postgres and running the
chain verifier: `seq` (BIGSERIAL) is assigned BEFORE the BEFORE-INSERT trigger runs, i.e. before
the trigger takes pg_advisory_xact_lock. Two concurrent inserts could therefore take their seq
values in one order and the lock in the other; the trigger's "previous row" (highest seq) then was
not the last row committed, and two rows ended up claiming the same prev_hash — a fork. 14 forks in
a 545-row table, none of them tampering, all indistinguishable from tampering.

Fix: after the lock is held, the trigger re-draws `seq` from the same sequence, so seq order is the
order the lock was granted, which is the order the chain is built in. Rows written before this
migration keep their (possibly forked) links; the verifier is told where the fork-free region
begins through the system_settings key below.

Revision ID: 049
Revises: 048
"""

from typing import Sequence, Union

from alembic import op

revision: str = "049"
down_revision: Union[str, None] = "048"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_FUNCTION = """
CREATE OR REPLACE FUNCTION audit_log_set_chain_hash() RETURNS trigger AS $$
DECLARE
    prev_h text;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtext('audit_log_chain'));
    {reseq}
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
"""


def upgrade() -> None:
    op.execute(
        _FUNCTION.format(
            reseq="NEW.seq := nextval(pg_get_serial_sequence('audit_log', 'seq'));"
        )
    )
    op.execute(
        "INSERT INTO system_settings (key, value) "
        "SELECT 'audit_chain_fork_free_since_seq', (COALESCE(max(seq), 0) + 1)::text FROM audit_log "
        "ON CONFLICT (key) DO NOTHING"
    )


def downgrade() -> None:
    op.execute(_FUNCTION.format(reseq=""))
    op.execute("DELETE FROM system_settings WHERE key = 'audit_chain_fork_free_since_seq'")
