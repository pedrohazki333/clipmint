"""stage_log: quanto cada etapa do pipeline levou

A tela mostrava uma porcentagem fixa por etapa (12% durante todo o download) e
ficava parada nela por vinte minutos. Para mostrar o tempo real de cada etapa é
preciso registrá-lo, e é isso que esta coluna guarda.

Revision ID: 0004_stage_log
Revises: 0003_sessoes
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_stage_log"
down_revision: Union[str, None] = "0003_sessoes"
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("stage_log", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.drop_column("stage_log")
