from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "q11msp16_device_logs"
down_revision: Union[str, Sequence[str], None] = "p10msp15_arp_mac_own_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "device_logs",
        sa.Column("device", sa.String(), primary_key=True),
        sa.Column("log_output", sa.Text(), nullable=True),
    )
    op.add_column("devices", sa.Column("logs_synced_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("devices", sa.Column("logs_sync_error", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("devices", "logs_sync_error")
    op.drop_column("devices", "logs_synced_at")
    op.drop_table("device_logs")
