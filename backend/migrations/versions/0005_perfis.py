"""perfis: a conta deixa de ser um enum em codigo

Antes, "conta" era um valor fixo (`podcast` | `gameplay` | `siege`) escrito em
`app/features.py`, com uma pasta de presets no disco. Isso bastava enquanto as
contas eram fixas e eram do dono da instalacao; num produto multiusuario, cada
um precisa das suas.

O que NAO muda: `jobs.source_type` continua sendo a fonte de verdade do
pipeline. O perfil e quem FORNECE esse valor na criacao do job. `jobs.profile_id`
e nulo permitido porque os jobs anteriores nao tem perfil, e inventar um seria
pior que admitir a ausencia.

Esta migracao NAO cria perfil nenhum: quem semeia um perfil por nicho ja usado e
o startup (app/services/profiles.py), que sabe quais nichos este build permite.

Revision ID: 0005_perfis
Revises: 0004_stage_log
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_perfis"
down_revision: Union[str, None] = "0004_stage_log"
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "profiles",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("avatar", sa.String(), nullable=True),
        sa.Column("default_layout_mode", sa.String(), nullable=False),
        sa.Column("default_subtitle_mode", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("profiles", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_profiles_user_id"), ["user_id"], unique=False
        )

    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("profile_id", sa.String(), nullable=True))
        batch_op.create_index(
            batch_op.f("ix_jobs_profile_id"), ["profile_id"], unique=False
        )
        batch_op.create_foreign_key(
            "fk_jobs_profile_id_profiles", "profiles", ["profile_id"], ["id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.drop_constraint("fk_jobs_profile_id_profiles", type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_jobs_profile_id"))
        batch_op.drop_column("profile_id")

    with op.batch_alter_table("profiles", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_profiles_user_id"))
    op.drop_table("profiles")
