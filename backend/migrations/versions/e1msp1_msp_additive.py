from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e1msp1_additive"
down_revision: Union[str, Sequence[str], None] = "d8a5f2c1b630"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("sites", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "kind",
                sa.String(length=32),
                nullable=False,
                server_default="REGULAR",
            )
        )
        batch_op.add_column(
            sa.Column("default_group_id", sa.Integer(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_sites_default_group_id",
            "device_groups",
            ["default_group_id"],
            ["id"],
            ondelete="RESTRICT",
            use_alter=True,
        )

    with op.batch_alter_table("device_groups", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "is_default",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )

    with op.batch_alter_table("devices", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("device_group_id", sa.Integer(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_devices_device_group_id",
            "device_groups",
            ["device_group_id"],
            ["id"],
            ondelete="RESTRICT",
            use_alter=True,
        )
        batch_op.create_index(
            "ix_devices_device_group_id", ["device_group_id"], unique=False
        )

    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "is_system_admin",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )

    op.create_table(
        "role_assignments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "site_id",
            sa.Integer(),
            sa.ForeignKey("sites.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "device_group_id",
            sa.Integer(),
            sa.ForeignKey("device_groups.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "created_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.CheckConstraint(
            "role IN ('observer', 'operator', 'admin')",
            name="ck_role_assignments_role",
        ),
        sa.UniqueConstraint(
            "user_id",
            "site_id",
            "device_group_id",
            name="uq_role_assignments_scope",
        ),
    )
    op.create_index(
        "ix_role_assignments_user_id", "role_assignments", ["user_id"]
    )
    op.create_index(
        "ix_role_assignments_site_id", "role_assignments", ["site_id"]
    )
    op.create_index(
        "ix_role_assignments_device_group_id",
        "role_assignments",
        ["device_group_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_role_assignments_device_group_id", table_name="role_assignments"
    )
    op.drop_index(
        "ix_role_assignments_site_id", table_name="role_assignments"
    )
    op.drop_index(
        "ix_role_assignments_user_id", table_name="role_assignments"
    )
    op.drop_table("role_assignments")

    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("is_system_admin")

    with op.batch_alter_table("devices", schema=None) as batch_op:
        batch_op.drop_index("ix_devices_device_group_id")
        batch_op.drop_constraint(
            "fk_devices_device_group_id", type_="foreignkey"
        )
        batch_op.drop_column("device_group_id")

    with op.batch_alter_table("device_groups", schema=None) as batch_op:
        batch_op.drop_column("is_default")

    with op.batch_alter_table("sites", schema=None) as batch_op:
        batch_op.drop_constraint(
            "fk_sites_default_group_id", type_="foreignkey"
        )
        batch_op.drop_column("default_group_id")
        batch_op.drop_column("kind")
