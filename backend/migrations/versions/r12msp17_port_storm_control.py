from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "r12msp17_port_storm_control"
down_revision: Union[str, Sequence[str], None] = "q11msp16_device_logs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "device_ports",
        sa.Column("storm_control_enabled", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "device_ports",
        sa.Column("storm_control_threshold", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("device_ports", "storm_control_threshold")
    op.drop_column("device_ports", "storm_control_enabled")
