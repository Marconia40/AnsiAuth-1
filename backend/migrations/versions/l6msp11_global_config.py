from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "l6msp11_global_config"
down_revision: Union[str, Sequence[str], None] = "k5msp10_svis"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "device_global_config",
        sa.Column("device", sa.String(), nullable=False),
        sa.Column("hostname", sa.String(), nullable=True),
        sa.Column("device_version", sa.String(), nullable=True),
        sa.Column("snmp_enabled", sa.Boolean(), nullable=True),
        sa.Column("snmp_version", sa.String(), nullable=True),
        sa.Column("snmp_community", sa.String(), nullable=True),
        sa.Column("snmp_permission", sa.String(), nullable=True),
        sa.Column("ntp_server", sa.String(), nullable=True),
        sa.Column("dns_server", sa.String(), nullable=True),
        sa.Column("log_server", sa.String(), nullable=True),
        sa.Column("log_level", sa.String(), nullable=True),
        sa.Column("routes", sa.JSON(), nullable=True),
        sa.Column("acls", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("device"),
    )
    op.add_column(
        "devices",
        sa.Column("global_config_synced_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "devices",
        sa.Column("global_config_sync_error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("devices", "global_config_sync_error")
    op.drop_column("devices", "global_config_synced_at")
    op.drop_table("device_global_config")
