from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f6msp5_rls"
down_revision: Union[str, Sequence[str], None] = "e5msp4_cleanup"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_SCOPED_TABLES = ("sites", "device_groups", "devices", "audit_logs")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    for table in _SCOPED_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

    _install_read_policies()
    _install_write_policies()
    _demote_app_role(bind)


def _demote_app_role(bind) -> None:
    role = bind.execute(sa.text("SELECT current_user")).scalar_one()
    if role in ("postgres", "rds_superuser", "cloudsqlsuperuser"):
        return
    bootstrap_role = bind.execute(
        sa.text("SELECT rolname FROM pg_roles WHERE oid = 10")
    ).scalar()
    if role == bootstrap_role:
        import logging
        logging.getLogger("alembic.migration").warning(
            "MSP Phase 6: role '%s' is the Postgres bootstrap user and "
            "cannot be demoted. RLS policies installed but NOT enforced — "
            "the connecting SUPERUSER bypasses them silently. To enable "
            "RLS enforcement, connect the app as a separate non-SUPERUSER "
            "role that only owns runtime privileges on the schema. See "
            "docs/upgrades/phases/phase-6-rls-and-optional.md.",
            role,
        )
        return
    es_super, bypass = bind.execute(
        sa.text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
    ).one()
    if not es_super and not bypass:
        return
    op.execute(f'ALTER ROLE "{role}" NOSUPERUSER NOBYPASSRLS')


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    role = bind.execute(sa.text("SELECT current_user")).scalar_one()
    bootstrap_role = bind.execute(
        sa.text("SELECT rolname FROM pg_roles WHERE oid = 10")
    ).scalar()
    if role not in ("postgres", "rds_superuser", "cloudsqlsuperuser") \
            and role != bootstrap_role:
        op.execute(f'ALTER ROLE "{role}" SUPERUSER BYPASSRLS')

    for table, policy in _all_policies():
        op.execute(f"DROP POLICY IF EXISTS {policy} ON {table}")

    for table in reversed(_SCOPED_TABLES):
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")


def _all_policies():
    pairs = []
    for table in _SCOPED_TABLES:
        pairs.append((table, f"{table}_read"))
        pairs.append((table, f"{table}_insert"))
        pairs.append((table, f"{table}_update"))
        pairs.append((table, f"{table}_delete"))
    return pairs


def _install_read_policies() -> None:
    op.execute("""
        CREATE POLICY sites_read ON sites FOR SELECT USING (
            current_setting('app.is_system_admin', TRUE)::bool
            OR (
                kind <> 'BASE_INFRASTRUCTURE'
                AND EXISTS (
                    SELECT 1 FROM role_assignments ra
                     WHERE ra.user_id = current_setting('app.user_id', TRUE)::int
                       AND ra.site_id = sites.id
                )
            )
        )
    """)

    op.execute("""
        CREATE POLICY device_groups_read ON device_groups FOR SELECT USING (
            current_setting('app.is_system_admin', TRUE)::bool
            OR EXISTS (
                SELECT 1 FROM role_assignments ra
                 WHERE ra.user_id = current_setting('app.user_id', TRUE)::int
                   AND ra.site_id = device_groups.site_id
                   AND (ra.device_group_id IS NULL
                        OR ra.device_group_id = device_groups.id)
            )
        )
    """)

    op.execute("""
        CREATE POLICY devices_read ON devices FOR SELECT USING (
            current_setting('app.is_system_admin', TRUE)::bool
            OR EXISTS (
                SELECT 1
                  FROM device_groups g
                  JOIN role_assignments ra
                    ON ra.site_id = g.site_id
                   AND (ra.device_group_id IS NULL
                        OR ra.device_group_id = g.id)
                 WHERE g.id = devices.device_group_id
                   AND ra.user_id = current_setting('app.user_id', TRUE)::int
            )
        )
    """)

    op.execute("""
        CREATE POLICY audit_logs_read ON audit_logs FOR SELECT USING (
            current_setting('app.is_system_admin', TRUE)::bool
            OR (
                resource = 'device' AND EXISTS (
                    SELECT 1 FROM devices d
                      JOIN device_groups g ON g.id = d.device_group_id
                      JOIN role_assignments ra
                        ON ra.site_id = g.site_id
                       AND (ra.device_group_id IS NULL OR ra.device_group_id = g.id)
                     WHERE d.name = audit_logs.resource_id
                       AND ra.user_id = current_setting('app.user_id', TRUE)::int
                )
            )
            OR (
                resource = 'device_group'
                AND audit_logs.resource_id ~ '^[0-9]+$'
                AND EXISTS (
                    SELECT 1 FROM device_groups g
                      JOIN role_assignments ra
                        ON ra.site_id = g.site_id
                       AND (ra.device_group_id IS NULL OR ra.device_group_id = g.id)
                     WHERE g.id = audit_logs.resource_id::int
                       AND ra.user_id = current_setting('app.user_id', TRUE)::int
                )
            )
            OR (
                resource = 'site'
                AND audit_logs.resource_id ~ '^[0-9]+$'
                AND EXISTS (
                    SELECT 1 FROM role_assignments ra
                     WHERE ra.site_id = audit_logs.resource_id::int
                       AND ra.user_id = current_setting('app.user_id', TRUE)::int
                )
            )
            OR (
                resource = 'user'
                AND EXISTS (
                    SELECT 1 FROM users u
                     WHERE u.id = current_setting('app.user_id', TRUE)::int
                       AND u.username = audit_logs."user"
                )
            )
            OR (
                resource = 'auth'
                AND EXISTS (
                    SELECT 1 FROM users u
                     WHERE u.id = current_setting('app.user_id', TRUE)::int
                       AND u.username = audit_logs."user"
                )
            )
        )
    """)


def _install_write_policies() -> None:
    for table in _SCOPED_TABLES:
        op.execute(f"""
            CREATE POLICY {table}_insert ON {table}
                FOR INSERT WITH CHECK (true)
        """)
        op.execute(f"""
            CREATE POLICY {table}_update ON {table}
                FOR UPDATE USING (true) WITH CHECK (true)
        """)
        op.execute(f"""
            CREATE POLICY {table}_delete ON {table}
                FOR DELETE USING (true)
        """)
