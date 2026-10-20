from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "g1msp6_jobs_op"
down_revision: Union[str, Sequence[str], None] = "f6msp5_rls"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("operation", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.drop_column("operation")
