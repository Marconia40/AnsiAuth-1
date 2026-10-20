from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "k5msp10_svis"
down_revision: Union[str, Sequence[str], None] = "j4msp9_device_sync_metadata"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "device_svis",
        sa.Column("vlan_id", sa.Integer(), nullable=False),
        sa.Column("device", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("admin_up", sa.Boolean(), nullable=True),
        sa.Column("ipv4_address", sa.String(), nullable=True),
        sa.Column("ipv4_address_secondary", sa.String(), nullable=True),
        sa.Column("ipv6_address", sa.String(), nullable=True),
        sa.Column("acl_in", sa.String(), nullable=True),
        sa.Column("acl_out", sa.String(), nullable=True),
        sa.Column("dhcp_relay_servers", sa.JSON(), nullable=True),
        sa.Column("operational_up", sa.Boolean(), nullable=True),
        sa.PrimaryKeyConstraint("vlan_id", "device"),
    )
    op.add_column(
        "devices",
        sa.Column("svis_synced_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "devices",
        sa.Column("svis_sync_error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("devices", "svis_sync_error")
    op.drop_column("devices", "svis_synced_at")
    op.drop_table("device_svis")
