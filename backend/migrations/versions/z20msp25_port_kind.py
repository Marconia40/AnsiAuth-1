from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "z20msp25_port_kind"
down_revision: Union[str, Sequence[str], None] = "y19msp24_refresh_session"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "device_ports",
        sa.Column("kind", sa.String(), nullable=False, server_default="physical"),
    )


def downgrade() -> None:
    op.drop_column("device_ports", "kind")
