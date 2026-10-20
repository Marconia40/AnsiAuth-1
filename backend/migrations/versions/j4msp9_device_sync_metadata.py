from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "j4msp9_device_sync_metadata"
down_revision: Union[str, Sequence[str], None] = "i3msp8_device_vlans_ports"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "devices",
        sa.Column("vlans_synced_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "devices",
        sa.Column("vlans_sync_error", sa.Text(), nullable=True),
    )
    op.add_column(
        "devices",
        sa.Column("ports_synced_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "devices",
        sa.Column("ports_sync_error", sa.Text(), nullable=True),
    )
    op.add_column(
        "device_ports",
        sa.Column("operational_up", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "device_ports",
        sa.Column("speed", sa.String(), nullable=True),
    )
    op.add_column(
        "device_ports",
        sa.Column("duplex", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("device_ports", "duplex")
    op.drop_column("device_ports", "speed")
    op.drop_column("device_ports", "operational_up")
    op.drop_column("devices", "ports_sync_error")
    op.drop_column("devices", "ports_synced_at")
    op.drop_column("devices", "vlans_sync_error")
    op.drop_column("devices", "vlans_synced_at")
