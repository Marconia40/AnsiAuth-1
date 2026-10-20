from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e5msp4_cleanup"
down_revision: Union[str, Sequence[str], None] = "e4msp3_enforce"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_DEVICES_SITE_ID_INDEX = "ix_devices_site_id"
_DEVICES_SITE_ID_FK = "fk_devices_site_id"


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    _drop_devices_site_id(bind, is_pg)

    op.drop_table("device_group_members")

    op.drop_table("user_allowed_sites")

    _drop_users_role(is_pg)


def downgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    op.execute(
        "SELECT 'M4 downgrade cannot restore dropped data — restore from the "
        "pre-Phase-5 snapshot instead (see phase-5-cleanup.md sec 8).'"
    )


    _recreate_users_role(is_pg)

    _recreate_user_allowed_sites()

    _recreate_device_group_members()

    _recreate_devices_site_id(bind, is_pg)


def _drop_devices_site_id(bind, is_pg: bool) -> None:
    if is_pg:
        idx_exists = bind.execute(sa.text("""
            SELECT 1 FROM pg_indexes
             WHERE tablename = 'devices'
               AND indexname = :name
        """), {"name": _DEVICES_SITE_ID_INDEX}).scalar()
        if idx_exists:
            op.drop_index(_DEVICES_SITE_ID_INDEX, table_name="devices")

        fk_exists = bind.execute(sa.text("""
            SELECT 1 FROM information_schema.table_constraints
             WHERE table_name = 'devices'
               AND constraint_name = :name
        """), {"name": _DEVICES_SITE_ID_FK}).scalar()
        if fk_exists:
            op.drop_constraint(_DEVICES_SITE_ID_FK, "devices", type_="foreignkey")

        op.drop_column("devices", "site_id")
    else:
        with op.batch_alter_table("devices") as batch:
            batch.drop_index(_DEVICES_SITE_ID_INDEX)
            batch.drop_constraint(_DEVICES_SITE_ID_FK, type_="foreignkey")
            batch.drop_column("site_id")


def _recreate_devices_site_id(bind, is_pg: bool) -> None:
    if is_pg:
        op.add_column(
            "devices",
            sa.Column("site_id", sa.Integer(), nullable=True),
        )
        op.create_foreign_key(
            _DEVICES_SITE_ID_FK,
            "devices", "sites",
            ["site_id"], ["id"],
            ondelete="SET NULL",
        )
        op.create_index(_DEVICES_SITE_ID_INDEX, "devices", ["site_id"], unique=False)
    else:
        with op.batch_alter_table("devices") as batch:
            batch.add_column(sa.Column("site_id", sa.Integer(), nullable=True))
            batch.create_foreign_key(
                _DEVICES_SITE_ID_FK, "sites", ["site_id"], ["id"],
                ondelete="SET NULL",
            )
            batch.create_index(_DEVICES_SITE_ID_INDEX, ["site_id"], unique=False)


def _recreate_device_group_members() -> None:
    op.create_table(
        "device_group_members",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("device_name", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["device_name"], ["devices.name"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["group_id"], ["device_groups.id"], ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("group_id", "device_name", name="uq_group_member"),
    )
    with op.batch_alter_table("device_group_members") as batch:
        batch.create_index(
            "ix_device_group_members_group_id", ["group_id"], unique=False,
        )
        batch.create_index(
            "ix_device_group_members_device_name", ["device_name"], unique=False,
        )


def _recreate_user_allowed_sites() -> None:
    op.create_table(
        "user_allowed_sites",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "site_id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
    )
    with op.batch_alter_table("user_allowed_sites") as batch:
        batch.create_index(
            "ix_user_allowed_sites_user_id", ["user_id"], unique=False,
        )
        batch.create_index(
            "ix_user_allowed_sites_site_id", ["site_id"], unique=False,
        )


def _drop_users_role(is_pg: bool) -> None:
    if is_pg:
        op.drop_column("users", "role")
    else:
        with op.batch_alter_table("users") as batch:
            batch.drop_column("role")


def _recreate_users_role(is_pg: bool) -> None:
    default_role = sa.text("'observer'")
    if is_pg:
        op.add_column(
            "users",
            sa.Column(
                "role", sa.String(), nullable=False, server_default=default_role,
            ),
        )
    else:
        with op.batch_alter_table("users") as batch:
            batch.add_column(
                sa.Column(
                    "role", sa.String(), nullable=False,
                    server_default=default_role,
                ),
            )
