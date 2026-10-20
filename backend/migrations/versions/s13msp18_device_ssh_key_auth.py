from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "s13msp18_device_ssh_key_auth"
down_revision: Union[str, Sequence[str], None] = "r12msp17_port_storm_control"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "devices",
        sa.Column("auth_method", sa.String(), nullable=False, server_default="password"),
    )
    op.add_column(
        "devices",
        sa.Column("encrypted_private_key", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("devices", "encrypted_private_key")
    op.drop_column("devices", "auth_method")
