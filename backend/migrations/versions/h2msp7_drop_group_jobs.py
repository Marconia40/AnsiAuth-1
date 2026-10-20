from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "h2msp7_drop_gj"
down_revision: Union[str, Sequence[str], None] = "g1msp6_jobs_op"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("group_jobs")


def downgrade() -> None:
    op.create_table(
        "group_jobs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("group_job_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("operation", sa.String(), nullable=True),
        sa.Column("playbook", sa.String(), nullable=True),
        sa.Column("parameters", sa.JSON(), nullable=True),
        sa.Column("device_results", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("group_jobs", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_group_jobs_group_job_id"), ["group_job_id"], unique=True)
        batch_op.create_index(batch_op.f("ix_group_jobs_status"), ["status"], unique=False)
