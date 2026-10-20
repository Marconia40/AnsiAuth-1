from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "i3msp8_device_vlans_ports"
down_revision: Union[str, Sequence[str], None] = "h2msp7_drop_gj"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "device_vlans",
        sa.Column("vlan_id", sa.Integer(), nullable=False),
        sa.Column("device", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("vlan_id", "device"),
    )
    op.create_table(
        "device_ports",
        sa.Column("interface", sa.String(), nullable=False),
        sa.Column("device", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("admin_up", sa.Boolean(), nullable=True),
        sa.Column("mode", sa.String(), nullable=True),
        sa.Column("access_vlan", sa.Integer(), nullable=True),
        sa.Column("allowed_vlans", sa.JSON(), nullable=True),
        sa.Column("poe_enabled", sa.Boolean(), nullable=True),
        sa.PrimaryKeyConstraint("interface", "device"),
    )


def downgrade() -> None:
    op.drop_table("device_ports")
    op.drop_table("device_vlans")
