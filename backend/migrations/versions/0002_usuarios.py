"""usuarios: tabela users e dono do job

Prepara o multiusuário do produto público. Ainda não há login (isso é a fatia
seguinte) — o schema nasce agora para o banco não precisar de uma segunda
migração depois de o Postgres já estar em produção.

`jobs.user_id` é NULO permitido de propósito: os jobs que já existiam não têm
dono, e inventar um seria pior que admitir a ausência.

Revision ID: 0002_usuarios
Revises: 0001_schema_inicial
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_usuarios"
down_revision: Union[str, None] = "0001_schema_inicial"
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_owner", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("users", schema=None) as batch_op:
        # Único: o mesmo endereço não pode virar duas contas. O índice serve à
        # unicidade E à busca do login.
        batch_op.create_index(
            batch_op.f("ix_users_email"), ["email"], unique=True
        )

    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("user_id", sa.String(), nullable=True))
        batch_op.create_index(
            batch_op.f("ix_jobs_user_id"), ["user_id"], unique=False
        )
        # "meus jobs, do mais novo para o mais velho" é a consulta mais repetida
        # do produto: todo polling da tela de conta passa por ela.
        batch_op.create_index(
            "ix_jobs_user_created", ["user_id", "created_at"], unique=False
        )
        batch_op.create_foreign_key(
            "fk_jobs_user_id_users", "users", ["user_id"], ["id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.drop_constraint("fk_jobs_user_id_users", type_="foreignkey")
        batch_op.drop_index("ix_jobs_user_created")
        batch_op.drop_index(batch_op.f("ix_jobs_user_id"))
        batch_op.drop_column("user_id")

    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_users_email"))
    op.drop_table("users")
