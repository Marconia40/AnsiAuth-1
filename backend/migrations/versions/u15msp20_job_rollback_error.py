from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "u15msp20_job_rollback_err"
down_revision: Union[str, Sequence[str], None] = "t14msp19_job_err_class"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("rollback_error", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "rollback_error")
