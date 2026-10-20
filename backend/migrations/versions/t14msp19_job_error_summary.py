from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "t14msp19_job_error_summary"
down_revision: Union[str, Sequence[str], None] = "s13msp18_device_ssh_key_auth"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("parameters_summary", sa.Text(), nullable=True),
    )
    op.add_column(
        "jobs",
        sa.Column("error_summary", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("jobs", "error_summary")
    op.drop_column("jobs", "parameters_summary")
