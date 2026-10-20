from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "p10msp15_arp_mac_own_table"
down_revision: Union[str, Sequence[str], None] = "o9msp14_arp_mac_cache"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "device_arp_mac",
        sa.Column("device", sa.String(), primary_key=True),
        sa.Column("arp_table", sa.JSON(), nullable=True),
        sa.Column("mac_table", sa.JSON(), nullable=True),
    )
    op.execute(
        "INSERT INTO device_arp_mac (device, arp_table, mac_table) "
        "SELECT device, arp_table, mac_table FROM device_global_config "
        "WHERE arp_table IS NOT NULL OR mac_table IS NOT NULL"
    )
    op.drop_column("device_global_config", "arp_table")
    op.drop_column("device_global_config", "mac_table")

    op.add_column("devices", sa.Column("arp_mac_synced_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("devices", sa.Column("arp_mac_sync_error", sa.Text(), nullable=True))
    op.execute(
        "UPDATE devices SET arp_mac_synced_at = global_config_synced_at "
        "WHERE name IN (SELECT device FROM device_arp_mac)"
    )


def downgrade() -> None:
    op.add_column("device_global_config", sa.Column("arp_table", sa.JSON(), nullable=True))
    op.add_column("device_global_config", sa.Column("mac_table", sa.JSON(), nullable=True))
    op.execute(
        "UPDATE device_global_config g SET "
        "arp_table = a.arp_table, mac_table = a.mac_table "
        "FROM device_arp_mac a WHERE a.device = g.device"
    )
    op.drop_column("devices", "arp_mac_sync_error")
    op.drop_column("devices", "arp_mac_synced_at")
    op.drop_table("device_arp_mac")
