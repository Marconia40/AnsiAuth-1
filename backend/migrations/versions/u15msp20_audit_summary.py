from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "u15msp20_audit_summary"
down_revision: Union[str, Sequence[str], None] = "t14msp19_job_error_summary"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "audit_logs",
        sa.Column("summary", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("audit_logs", "summary")
