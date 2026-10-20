from typing import Sequence, Union

from alembic import op


revision: str = 'd8a5f2c1b630'
down_revision: Union[str, Sequence[str], None] = 'c4f7e2a9b610'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TRIGGER_SQL = """
CREATE TRIGGER IF NOT EXISTS audit_log_immutable
BEFORE UPDATE ON audit_logs
BEGIN
    SELECT RAISE(ABORT, 'audit_logs rows are immutable — use append_audit_event() instead');
END
"""


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS audit_log_immutable")


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        op.execute(_TRIGGER_SQL)
