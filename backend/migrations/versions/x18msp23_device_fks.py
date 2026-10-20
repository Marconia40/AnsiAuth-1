from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "x18msp23_device_fks"
down_revision: Union[str, Sequence[str], None] = "u15msp20_job_rollback_err"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_SATELLITE_TABLES: list[tuple[str, str]] = [
    ("device_vlans", "fk_device_vlans_device"),
    ("device_ports", "fk_device_ports_device"),
    ("device_svis", "fk_device_svis_device"),
    ("device_global_config", "fk_device_global_config_device"),
    ("device_arp_mac", "fk_device_arp_mac_device"),
    ("device_logs", "fk_device_logs_device"),
]


def upgrade() -> None:
    conn = op.get_bind()

    for table, _ in _SATELLITE_TABLES:
        conn.execute(
            sa.text(
                f"DELETE FROM {table} "
                f"WHERE device NOT IN (SELECT name FROM devices)"
            )
        )

    for table, fk_name in _SATELLITE_TABLES:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.create_foreign_key(
                fk_name,
                "devices",
                ["device"],
                ["name"],
                ondelete="CASCADE",
            )


def downgrade() -> None:
    for table, fk_name in _SATELLITE_TABLES:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_constraint(fk_name, type_="foreignkey")
