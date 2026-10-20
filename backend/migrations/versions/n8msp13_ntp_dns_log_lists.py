from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "n8msp13_ntp_dns_log_lists"
down_revision: Union[str, Sequence[str], None] = "m7msp12_running_config"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RENAMES = (
    ("ntp_server", "ntp_servers"),
    ("dns_server", "dns_servers"),
    ("log_server", "log_servers"),
)


def upgrade() -> None:
    op.add_column(
        "device_global_config",
        sa.Column("snmp_trap_hosts", sa.JSON(), nullable=True),
    )
    is_sqlite = op.get_bind().dialect.name == "sqlite"
    if is_sqlite:
        with op.batch_alter_table("device_global_config") as batch_op:
            for old, new in _RENAMES:
                batch_op.add_column(sa.Column(new, sa.JSON(), nullable=True))
                batch_op.drop_column(old)
    else:
        for old, new in _RENAMES:
            op.execute(
                f"ALTER TABLE device_global_config "
                f"ALTER COLUMN {old} TYPE json USING "
                f"(CASE WHEN {old} IS NULL THEN NULL ELSE to_jsonb(ARRAY[{old}]) END)"
            )
            op.alter_column("device_global_config", old, new_column_name=new)
    op.execute("UPDATE device_global_config SET acls = NULL WHERE acls IS NOT NULL")


def downgrade() -> None:
    is_sqlite = op.get_bind().dialect.name == "sqlite"
    if is_sqlite:
        with op.batch_alter_table("device_global_config") as batch_op:
            for old, new in _RENAMES:
                batch_op.add_column(sa.Column(old, sa.String(), nullable=True))
                batch_op.drop_column(new)
    else:
        for old, new in _RENAMES:
            op.alter_column("device_global_config", new, new_column_name=old)
            op.execute(
                f"ALTER TABLE device_global_config "
                f"ALTER COLUMN {old} TYPE varchar USING "
                f"(CASE WHEN {old} IS NULL THEN NULL ELSE ({old}->>0) END)"
            )
    op.drop_column("device_global_config", "snmp_trap_hosts")
