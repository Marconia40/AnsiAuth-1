from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "o9msp14_arp_mac_cache"
down_revision: Union[str, Sequence[str], None] = "n8msp13_ntp_dns_log_lists"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("device_global_config", sa.Column("arp_table", sa.JSON(), nullable=True))
    op.add_column("device_global_config", sa.Column("mac_table", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("device_global_config", "mac_table")
    op.drop_column("device_global_config", "arp_table")
