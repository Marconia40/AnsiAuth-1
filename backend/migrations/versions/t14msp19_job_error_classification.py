from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "t14msp19_job_err_class"
down_revision: Union[str, Sequence[str], None] = "w17msp22_storm_action"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("error_type", sa.String(), nullable=True))
    op.add_column("jobs", sa.Column("error_reason", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "error_reason")
    op.drop_column("jobs", "error_type")
