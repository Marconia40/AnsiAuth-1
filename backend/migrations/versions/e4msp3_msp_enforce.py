from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e4msp3_enforce"
down_revision: Union[str, Sequence[str], None] = "e2msp2_backfill"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


BASE_INFRA_SITE_KIND = "BASE_INFRASTRUCTURE"


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    _preflight_verify(bind)

    _flip_not_null(is_pg)

    _create_partial_unique_indexes(is_pg)

    _swap_to_per_site_unique_name(bind, is_pg)

    _tighten_device_groups_site_fk(bind, is_pg)


def downgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    _relax_device_groups_site_fk(bind, is_pg)

    _swap_back_to_global_lookup_index(bind, is_pg)

    op.drop_index("ux_device_groups_one_default_per_site", table_name="device_groups")
    op.drop_index("ux_sites_single_base_infra", table_name="sites")

    if is_pg:
        op.alter_column("device_groups", "site_id", existing_type=sa.Integer(), nullable=True)
        op.alter_column("devices", "device_group_id", existing_type=sa.Integer(), nullable=True)
    else:
        with op.batch_alter_table("device_groups") as batch:
            batch.alter_column("site_id", existing_type=sa.Integer(), nullable=True)
        with op.batch_alter_table("devices") as batch:
            batch.alter_column("device_group_id", existing_type=sa.Integer(), nullable=True)


def _preflight_verify(bind) -> None:
    checks = [
        (
            "SELECT COUNT(*) FROM devices WHERE device_group_id IS NULL",
            "devices with NULL device_group_id",
        ),
        (
            "SELECT COUNT(*) FROM device_groups WHERE site_id IS NULL",
            "device_groups with NULL site_id",
        ),
        (
            "SELECT COUNT(*) FROM sites WHERE default_group_id IS NULL",
            "sites with NULL default_group_id",
        ),
        (
            "SELECT COUNT(*) FROM users WHERE role IN ('admin','super-admin') "
            "AND is_system_admin = 0",
            "admin/super-admin users with is_system_admin=FALSE",
        ),
    ]
    for sql, label in checks:
        sql_pg = sql.replace("= 0", "= FALSE") if bind.dialect.name == "postgresql" else sql
        n = bind.execute(sa.text(sql_pg)).scalar_one()
        if n:
            raise RuntimeError(
                f"M3 preflight failed: {n} row(s) — {label}. "
                "Phase-2 backfill (e2msp2_backfill) must complete cleanly before "
                "M3 can enforce NOT NULL. Investigate via the post-migration "
                "report script (backend/scripts/msp_post_backfill_report.py) "
                "and re-run M2 if necessary."
            )

    base_infra_count = bind.execute(sa.text(
        "SELECT COUNT(*) FROM sites WHERE kind = 'BASE_INFRASTRUCTURE'"
    )).scalar_one()
    if base_infra_count != 1:
        raise RuntimeError(
            f"M3 preflight failed: expected exactly 1 BASE_INFRASTRUCTURE site, "
            f"found {base_infra_count}. Run Phase-2 backfill first."
        )


def _flip_not_null(is_pg: bool) -> None:
    if is_pg:
        op.alter_column("devices", "device_group_id",
                        existing_type=sa.Integer(), nullable=False)
        op.alter_column("device_groups", "site_id",
                        existing_type=sa.Integer(), nullable=False)
    else:
        with op.batch_alter_table("devices") as batch:
            batch.alter_column("device_group_id",
                               existing_type=sa.Integer(), nullable=False)
        with op.batch_alter_table("device_groups") as batch:
            batch.alter_column("site_id",
                               existing_type=sa.Integer(), nullable=False)


def _create_partial_unique_indexes(is_pg: bool) -> None:
    op.create_index(
        "ux_sites_single_base_infra",
        "sites",
        ["kind"],
        unique=True,
        postgresql_where=sa.text("kind = 'BASE_INFRASTRUCTURE'"),
        sqlite_where=sa.text("kind = 'BASE_INFRASTRUCTURE'"),
    )
    op.create_index(
        "ux_device_groups_one_default_per_site",
        "device_groups",
        ["site_id"],
        unique=True,
        postgresql_where=sa.text("is_default = TRUE"),
        sqlite_where=sa.text("is_default = 1"),
    )


def _swap_to_per_site_unique_name(bind, is_pg: bool) -> None:
    if is_pg:
        exists_ix = bind.execute(sa.text("""
            SELECT 1 FROM pg_indexes
             WHERE tablename = 'device_groups'
               AND indexname = 'ix_device_groups_name_nonunique'
        """)).scalar()
        if exists_ix:
            op.drop_index("ix_device_groups_name_nonunique", table_name="device_groups")
        exists_uc = bind.execute(sa.text("""
            SELECT 1 FROM information_schema.table_constraints
             WHERE table_name = 'device_groups'
               AND constraint_name = 'uq_device_group_site_name'
        """)).scalar()
        if not exists_uc:
            op.create_unique_constraint(
                "uq_device_group_site_name", "device_groups", ["site_id", "name"],
            )
    else:
        indexes = {
            r[1] for r in bind.execute(
                sa.text("PRAGMA index_list('device_groups')")
            ).fetchall()
        }
        with op.batch_alter_table("device_groups") as batch:
            if "ix_device_groups_name_nonunique" in indexes:
                batch.drop_index("ix_device_groups_name_nonunique")
            batch.create_unique_constraint(
                "uq_device_group_site_name", ["site_id", "name"],
            )


def _swap_back_to_global_lookup_index(bind, is_pg: bool) -> None:
    if is_pg:
        exists_uc = bind.execute(sa.text("""
            SELECT 1 FROM information_schema.table_constraints
             WHERE table_name = 'device_groups'
               AND constraint_name = 'uq_device_group_site_name'
        """)).scalar()
        if exists_uc:
            op.drop_constraint(
                "uq_device_group_site_name", "device_groups", type_="unique",
            )
        exists_ix = bind.execute(sa.text("""
            SELECT 1 FROM pg_indexes
             WHERE tablename = 'device_groups'
               AND indexname = 'ix_device_groups_name_nonunique'
        """)).scalar()
        if not exists_ix:
            op.create_index(
                "ix_device_groups_name_nonunique",
                "device_groups",
                ["name"],
                unique=False,
            )
    else:
        indexes = {
            r[1] for r in bind.execute(
                sa.text("PRAGMA index_list('device_groups')")
            ).fetchall()
        }
        with op.batch_alter_table("device_groups") as batch:
            batch.drop_constraint("uq_device_group_site_name", type_="unique")
            if "ix_device_groups_name_nonunique" not in indexes:
                batch.create_index(
                    "ix_device_groups_name_nonunique", ["name"], unique=False,
                )


_FK_NAME = "fk_device_groups_site_id"


def _tighten_device_groups_site_fk(bind, is_pg: bool) -> None:
    if is_pg:
        exists = bind.execute(sa.text("""
            SELECT 1 FROM information_schema.table_constraints
             WHERE table_name = 'device_groups'
               AND constraint_name = :fk
        """), {"fk": _FK_NAME}).scalar()
        if exists:
            op.drop_constraint(_FK_NAME, "device_groups", type_="foreignkey")
        op.create_foreign_key(
            _FK_NAME,
            "device_groups", "sites",
            ["site_id"], ["id"],
            ondelete="RESTRICT",
        )
    else:
        with op.batch_alter_table("device_groups") as batch:
            batch.drop_constraint(_FK_NAME, type_="foreignkey")
            batch.create_foreign_key(
                _FK_NAME,
                "sites",
                ["site_id"], ["id"],
                ondelete="RESTRICT",
            )


def _relax_device_groups_site_fk(bind, is_pg: bool) -> None:
    if is_pg:
        exists = bind.execute(sa.text("""
            SELECT 1 FROM information_schema.table_constraints
             WHERE table_name = 'device_groups'
               AND constraint_name = :fk
        """), {"fk": _FK_NAME}).scalar()
        if exists:
            op.drop_constraint(_FK_NAME, "device_groups", type_="foreignkey")
        op.create_foreign_key(
            _FK_NAME,
            "device_groups", "sites",
            ["site_id"], ["id"],
            ondelete="SET NULL",
        )
    else:
        with op.batch_alter_table("device_groups") as batch:
            batch.drop_constraint(_FK_NAME, type_="foreignkey")
            batch.create_foreign_key(
                _FK_NAME,
                "sites",
                ["site_id"], ["id"],
                ondelete="SET NULL",
            )
