from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e2msp2_backfill"
down_revision: Union[str, Sequence[str], None] = "e1msp1_additive"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


BASE_INFRA_NAME = "Base Infrastructure"
BASE_INFRA_KIND = "BASE_INFRASTRUCTURE"
REGULAR_KIND = "REGULAR"
DEFAULT_GROUP_NAME = "Default"


def _assert_zero(bind, sql: str, msg: str) -> None:
    n = bind.execute(sa.text(sql)).scalar() or 0
    if n:
        raise RuntimeError(f"MSP M2 verification failed: {msg} (got {n})")


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    _drop_global_unique_on_device_groups_name(bind, is_pg)

    op.execute(sa.text(f"""
        INSERT INTO sites (name, description, kind, created_at, updated_at)
        SELECT :name, :desc, :kind, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
         WHERE NOT EXISTS (
             SELECT 1 FROM sites WHERE kind = :kind
         )
    """).bindparams(
        name=BASE_INFRA_NAME,
        desc="System-managed base infrastructure site.",
        kind=BASE_INFRA_KIND,
    ))

    op.execute(sa.text(f"""
        INSERT INTO device_groups (name, description, site_id, is_default, created_at)
        SELECT :name, :desc, s.id, {_true(is_pg)}, CURRENT_TIMESTAMP
          FROM sites s
         WHERE s.kind = :kind
           AND s.default_group_id IS NULL
           AND NOT EXISTS (
               SELECT 1 FROM device_groups g
                WHERE g.site_id = s.id AND g.is_default = {_true(is_pg)}
           )
    """).bindparams(
        name=DEFAULT_GROUP_NAME,
        desc=f"Default group for {BASE_INFRA_NAME}.",
        kind=BASE_INFRA_KIND,
    ))

    op.execute(sa.text(f"""
        UPDATE sites
           SET default_group_id = (
               SELECT g.id FROM device_groups g
                WHERE g.site_id = sites.id AND g.is_default = {_true(is_pg)}
                LIMIT 1
           )
         WHERE default_group_id IS NULL
           AND kind = :kind
    """).bindparams(kind=BASE_INFRA_KIND))

    op.execute(sa.text(f"""
        UPDATE device_groups
           SET is_default = {_true(is_pg)}
         WHERE name = :name
           AND is_default = {_false(is_pg)}
           AND site_id IN (
               SELECT id FROM sites
                WHERE default_group_id IS NULL AND kind = :kind
           )
    """).bindparams(name=DEFAULT_GROUP_NAME, kind=REGULAR_KIND))

    op.execute(sa.text(f"""
        INSERT INTO device_groups (name, description, site_id, is_default, created_at)
        SELECT :name, 'Default group for site ' || s.name, s.id, {_true(is_pg)}, CURRENT_TIMESTAMP
          FROM sites s
         WHERE s.kind = :kind
           AND s.default_group_id IS NULL
           AND NOT EXISTS (
               SELECT 1 FROM device_groups g
                WHERE g.site_id = s.id AND g.is_default = {_true(is_pg)}
           )
    """).bindparams(name=DEFAULT_GROUP_NAME, kind=REGULAR_KIND))

    op.execute(sa.text(f"""
        UPDATE sites
           SET default_group_id = (
               SELECT g.id FROM device_groups g
                WHERE g.site_id = sites.id AND g.is_default = {_true(is_pg)}
                LIMIT 1
           )
         WHERE default_group_id IS NULL
           AND kind = :kind
    """).bindparams(kind=REGULAR_KIND))


    op.execute(sa.text("""
        UPDATE devices
           SET device_group_id = (
               SELECT default_group_id FROM sites
                WHERE kind = :kind
                LIMIT 1
           )
         WHERE device_group_id IS NULL
           AND site_id IS NULL
    """).bindparams(kind=BASE_INFRA_KIND))

    op.execute(sa.text("""
        UPDATE devices
           SET device_group_id = (
               SELECT MIN(m.group_id)
                 FROM device_group_members m
                 JOIN device_groups g ON g.id = m.group_id
                WHERE m.device_name = devices.name
                  AND g.site_id = devices.site_id
           )
         WHERE device_group_id IS NULL
           AND site_id IS NOT NULL
           AND (
               SELECT COUNT(DISTINCT m.group_id)
                 FROM device_group_members m
                 JOIN device_groups g ON g.id = m.group_id
                WHERE m.device_name = devices.name
                  AND g.site_id = devices.site_id
           ) = 1
    """))

    op.execute(sa.text("""
        UPDATE devices
           SET device_group_id = (
               SELECT s.default_group_id FROM sites s WHERE s.id = devices.site_id
           )
         WHERE device_group_id IS NULL
           AND site_id IS NOT NULL
    """))

    if is_pg:
        op.execute(sa.text("""
            INSERT INTO audit_logs (timestamp, "user", action, resource, resource_id,
                                    status, details)
            SELECT CURRENT_TIMESTAMP,
                   'msp_migration',
                   'msp_migration_ambiguous_group_assignment',
                   'device',
                   d.name,
                   'success',
                   json_build_object(
                       'previous_groups', array_agg(DISTINCT dgm.group_id ORDER BY dgm.group_id),
                       'assigned_to', d.device_group_id
                   )
              FROM devices d
              JOIN device_group_members dgm ON dgm.device_name = d.name
              JOIN device_groups g ON g.id = dgm.group_id
             WHERE d.site_id = g.site_id
               AND NOT EXISTS (
                   SELECT 1 FROM audit_logs al
                    WHERE al.action = 'msp_migration_ambiguous_group_assignment'
                      AND al.resource_id = d.name
               )
             GROUP BY d.name, d.device_group_id
            HAVING COUNT(DISTINCT dgm.group_id) > 1
        """))
    else:
        op.execute(sa.text("""
            INSERT INTO audit_logs (timestamp, "user", action, resource, resource_id,
                                    status, details)
            SELECT CURRENT_TIMESTAMP,
                   'msp_migration',
                   'msp_migration_ambiguous_group_assignment',
                   'device',
                   d.name,
                   'success',
                   '{"previous_groups": [' ||
                       group_concat(DISTINCT dgm.group_id) ||
                   '], "assigned_to": ' ||
                       CAST(d.device_group_id AS TEXT) ||
                   '}'
              FROM devices d
              JOIN device_group_members dgm ON dgm.device_name = d.name
              JOIN device_groups g ON g.id = dgm.group_id
             WHERE d.site_id = g.site_id
               AND NOT EXISTS (
                   SELECT 1 FROM audit_logs al
                    WHERE al.action = 'msp_migration_ambiguous_group_assignment'
                      AND al.resource_id = d.name
               )
             GROUP BY d.name, d.device_group_id
            HAVING COUNT(DISTINCT dgm.group_id) > 1
        """))

    op.execute(sa.text("""
        DELETE FROM device_group_members
         WHERE group_id IN (
             SELECT id FROM device_groups WHERE site_id IS NULL
         )
    """))
    op.execute(sa.text("DELETE FROM device_groups WHERE site_id IS NULL"))

    op.execute(sa.text(f"""
        UPDATE users
           SET is_system_admin = {_true(is_pg)}
         WHERE role IN ('admin', 'super-admin')
           AND is_system_admin = {_false(is_pg)}
    """))

    op.execute(sa.text("""
        INSERT INTO role_assignments
               (user_id, site_id, device_group_id, role, created_at, created_by_user_id)
        SELECT u.id, uas.site_id, NULL, u.role, CURRENT_TIMESTAMP, NULL
          FROM users u
          JOIN user_allowed_sites uas ON uas.user_id = u.id
          JOIN sites s ON s.id = uas.site_id
         WHERE u.role IN ('operator', 'observer')
           AND s.kind = :kind
           AND NOT EXISTS (
               SELECT 1 FROM role_assignments ra
                WHERE ra.user_id = u.id
                  AND ra.site_id = uas.site_id
                  AND ra.device_group_id IS NULL
           )
    """).bindparams(kind=REGULAR_KIND))

    _assert_zero(
        bind,
        "SELECT COUNT(*) FROM devices WHERE device_group_id IS NULL",
        "devices with no device_group_id",
    )
    _assert_zero(
        bind,
        "SELECT COUNT(*) FROM device_groups WHERE site_id IS NULL",
        "device_groups with no site_id",
    )
    _assert_zero(
        bind,
        "SELECT COUNT(*) FROM sites WHERE default_group_id IS NULL",
        "sites with no default_group_id",
    )
    _assert_zero(
        bind,
        "SELECT COUNT(*) FROM users "
        "WHERE role IN ('admin', 'super-admin') AND is_system_admin = "
        + _false(is_pg),
        "admin/super-admin users not marked is_system_admin",
    )

    base_infra_count = bind.execute(sa.text(
        "SELECT COUNT(*) FROM sites WHERE kind = :kind"
    ).bindparams(kind=BASE_INFRA_KIND)).scalar() or 0
    if base_infra_count != 1:
        raise RuntimeError(
            f"MSP M2 verification failed: expected exactly 1 Base-Infrastructure "
            f"site, got {base_infra_count}"
        )


def downgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    op.execute(sa.text(
        "DELETE FROM audit_logs WHERE action LIKE 'msp_migration_%'"
    ))
    op.execute(sa.text("DELETE FROM role_assignments"))
    op.execute(sa.text("UPDATE devices SET device_group_id = NULL"))
    op.execute(sa.text("UPDATE sites SET default_group_id = NULL"))
    op.execute(sa.text(
        f"UPDATE users SET is_system_admin = {_false(is_pg)}"
    ))
    op.execute(sa.text(f"""
        DELETE FROM device_groups
         WHERE is_default = {_true(is_pg)}
           AND description LIKE 'Default group for%'
    """))
    op.execute(sa.text(
        "DELETE FROM sites WHERE kind = :kind"
    ).bindparams(kind=BASE_INFRA_KIND))

    _restore_global_unique_on_device_groups_name(bind, is_pg)


def _true(is_pg: bool) -> str:
    return "TRUE" if is_pg else "1"


def _false(is_pg: bool) -> str:
    return "FALSE" if is_pg else "0"


def _drop_global_unique_on_device_groups_name(bind, is_pg: bool) -> None:
    if is_pg:
        exists = bind.execute(sa.text("""
            SELECT 1 FROM information_schema.table_constraints
             WHERE table_name = 'device_groups'
               AND constraint_name = 'uq_device_group_name'
        """)).scalar()
        if exists:
            op.drop_constraint(
                "uq_device_group_name", "device_groups", type_="unique"
            )
        exists_ix = bind.execute(sa.text("""
            SELECT 1 FROM pg_indexes
             WHERE tablename = 'device_groups'
               AND indexname = 'ix_device_groups_name'
        """)).scalar()
        if exists_ix:
            op.drop_index("ix_device_groups_name", table_name="device_groups")
    else:
        indexes = {
            r[1]
            for r in bind.execute(
                sa.text("PRAGMA index_list('device_groups')")
            ).fetchall()
        }
        if "ix_device_groups_name" in indexes:
            with op.batch_alter_table("device_groups") as batch_op:
                batch_op.drop_constraint(
                    "uq_device_group_name", type_="unique"
                )
                batch_op.drop_index("ix_device_groups_name")
                batch_op.create_index(
                    "ix_device_groups_name_nonunique", ["name"], unique=False
                )


def _restore_global_unique_on_device_groups_name(bind, is_pg: bool) -> None:
    if is_pg:
        exists = bind.execute(sa.text("""
            SELECT 1 FROM information_schema.table_constraints
             WHERE table_name = 'device_groups'
               AND constraint_name = 'uq_device_group_name'
        """)).scalar()
        if not exists:
            op.create_unique_constraint(
                "uq_device_group_name", "device_groups", ["name"]
            )
        exists_ix = bind.execute(sa.text("""
            SELECT 1 FROM pg_indexes
             WHERE tablename = 'device_groups'
               AND indexname = 'ix_device_groups_name'
        """)).scalar()
        if not exists_ix:
            op.create_index(
                "ix_device_groups_name", "device_groups", ["name"], unique=True
            )
    else:
        indexes = {
            r[1]
            for r in bind.execute(
                sa.text("PRAGMA index_list('device_groups')")
            ).fetchall()
        }
        if "ix_device_groups_name" not in indexes:
            with op.batch_alter_table("device_groups") as batch_op:
                if "ix_device_groups_name_nonunique" in indexes:
                    batch_op.drop_index("ix_device_groups_name_nonunique")
                batch_op.create_unique_constraint(
                    "uq_device_group_name", ["name"]
                )
                batch_op.create_index(
                    "ix_device_groups_name", ["name"], unique=True
                )
