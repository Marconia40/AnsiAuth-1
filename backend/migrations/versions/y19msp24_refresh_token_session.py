from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "y19msp24_refresh_session"
down_revision: Union[str, Sequence[str], None] = "x18msp23_device_fks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"

    with op.batch_alter_table("refresh_tokens", schema=None) as batch_op:
        batch_op.add_column(sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("session_id", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("session_started_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("parent_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("ip_address", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("user_agent", sa.String(), nullable=True))

    if is_sqlite:
        uuid_expr = "lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' || substr(lower(hex(randomblob(2))),2) || '-' || substr('89ab',abs(random())%4+1,1) || substr(lower(hex(randomblob(2))),2) || '-' || lower(hex(randomblob(6)))"
    else:
        uuid_expr = "gen_random_uuid()::text"

    op.execute(
        sa.text(
            f"UPDATE refresh_tokens "
            f"SET last_used_at = created_at, "
            f"    session_started_at = created_at, "
            f"    session_id = {uuid_expr} "
            f"WHERE last_used_at IS NULL"
        )
    )

    with op.batch_alter_table("refresh_tokens", schema=None) as batch_op:
        batch_op.alter_column("last_used_at", nullable=False)
        batch_op.alter_column("session_id", nullable=False)
        batch_op.alter_column("session_started_at", nullable=False)
        batch_op.create_index(
            "ix_refresh_tokens_session_id", ["session_id"], unique=False
        )
        batch_op.create_index(
            "ix_refresh_tokens_parent_id", ["parent_id"], unique=False
        )
        batch_op.create_foreign_key(
            "fk_refresh_tokens_parent_id",
            "refresh_tokens",
            ["parent_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("refresh_tokens", schema=None) as batch_op:
        batch_op.drop_constraint("fk_refresh_tokens_parent_id", type_="foreignkey")
        batch_op.drop_index("ix_refresh_tokens_parent_id")
        batch_op.drop_index("ix_refresh_tokens_session_id")
        batch_op.drop_column("user_agent")
        batch_op.drop_column("ip_address")
        batch_op.drop_column("parent_id")
        batch_op.drop_column("session_started_at")
        batch_op.drop_column("session_id")
        batch_op.drop_column("last_used_at")
