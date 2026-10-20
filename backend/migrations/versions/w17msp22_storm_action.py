from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "w17msp22_storm_action"
down_revision: Union[str, Sequence[str], None] = "v16msp21_svi_ipv4_secondary_list"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "device_ports",
        sa.Column("storm_control_action", sa.String(), nullable=True),
    )
    op.add_column(
        "device_ports",
        sa.Column("storm_control_trap", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("device_ports", "storm_control_trap")
    op.drop_column("device_ports", "storm_control_action")
