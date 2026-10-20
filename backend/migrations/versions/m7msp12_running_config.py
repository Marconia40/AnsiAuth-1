from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "m7msp12_running_config"
down_revision: Union[str, Sequence[str], None] = "l6msp11_global_config"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "device_global_config",
        sa.Column("running_config", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("device_global_config", "running_config")
