from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "v16msp21_svi_ipv4_secondary_list"
down_revision: Union[str, Sequence[str], None] = "u15msp20_audit_summary"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    is_sqlite = op.get_bind().dialect.name == "sqlite"
    if is_sqlite:
        with op.batch_alter_table("device_svis") as batch_op:
            batch_op.drop_column("ipv4_address_secondary")
            batch_op.add_column(sa.Column("ipv4_address_secondary", sa.JSON(), nullable=True))
    else:
        op.execute(
            "ALTER TABLE device_svis "
            "ALTER COLUMN ipv4_address_secondary TYPE json USING "
            "(CASE WHEN ipv4_address_secondary IS NULL THEN NULL "
            "ELSE to_jsonb(ARRAY[ipv4_address_secondary]) END)"
        )


def downgrade() -> None:
    is_sqlite = op.get_bind().dialect.name == "sqlite"
    if is_sqlite:
        with op.batch_alter_table("device_svis") as batch_op:
            batch_op.drop_column("ipv4_address_secondary")
            batch_op.add_column(sa.Column("ipv4_address_secondary", sa.String(), nullable=True))
    else:
        op.execute(
            "ALTER TABLE device_svis "
            "ALTER COLUMN ipv4_address_secondary TYPE varchar USING "
            "(CASE WHEN ipv4_address_secondary IS NULL THEN NULL "
            "ELSE (ipv4_address_secondary->>0) END)"
        )
