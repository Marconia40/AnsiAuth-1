from typing import Sequence, Union

from alembic import op


revision: str = "a21msp26_audit_rls"
down_revision: Union[str, Sequence[str], None] = "z20msp25_port_kind"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_USUARIO = "current_setting('app.user_id', TRUE)::int"


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("DROP POLICY IF EXISTS audit_logs_read ON audit_logs")
    op.execute(f"""
        CREATE POLICY audit_logs_read ON audit_logs FOR SELECT USING (
            current_setting('app.is_system_admin', TRUE)::bool
            OR (
                audit_logs.device IS NOT NULL AND EXISTS (
                    SELECT 1 FROM devices d
                      JOIN device_groups g ON g.id = d.device_group_id
                      JOIN role_assignments ra
                        ON ra.site_id = g.site_id
                       AND (ra.device_group_id IS NULL OR ra.device_group_id = g.id)
                     WHERE d.name = audit_logs.device
                       AND ra.user_id = {_USUARIO}
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
                       AND ra.user_id = {_USUARIO}
                )
            )
            OR (
                resource = 'site'
                AND audit_logs.resource_id ~ '^[0-9]+$'
                AND EXISTS (
                    SELECT 1 FROM role_assignments ra
                     WHERE ra.site_id = audit_logs.resource_id::int
                       AND ra.user_id = {_USUARIO}
                )
            )
            OR (
                resource = 'role_assignment'
                AND (audit_logs.details ->> 'site_id') ~ '^[0-9]+$'
                AND EXISTS (
                    SELECT 1 FROM role_assignments ra
                     WHERE ra.site_id = (audit_logs.details ->> 'site_id')::int
                       AND ra.device_group_id IS NULL
                       AND ra.user_id = {_USUARIO}
                )
            )
            OR (
                resource IN ('auth', 'user')
                AND EXISTS (
                    SELECT 1 FROM users u
                     WHERE u.id = {_USUARIO}
                       AND u.username = audit_logs."user"
                )
            )
        )
    """)


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("DROP POLICY IF EXISTS audit_logs_read ON audit_logs")
    op.execute(f"""
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
                       AND ra.user_id = {_USUARIO}
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
                       AND ra.user_id = {_USUARIO}
                )
            )
            OR (
                resource = 'site'
                AND audit_logs.resource_id ~ '^[0-9]+$'
                AND EXISTS (
                    SELECT 1 FROM role_assignments ra
                     WHERE ra.site_id = audit_logs.resource_id::int
                       AND ra.user_id = {_USUARIO}
                )
            )
            OR (
                resource IN ('auth', 'user')
                AND EXISTS (
                    SELECT 1 FROM users u
                     WHERE u.id = {_USUARIO}
                       AND u.username = audit_logs."user"
                )
            )
        )
    """)
