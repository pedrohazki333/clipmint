"""perfil: desfaz a caixa da facecam por canal

A 0012 congelava a caixa da facecam no perfil, supondo que o canal e sempre o
mesmo e a cam nao anda de lugar. **A suposicao esta errada** — o dono do produto
apontou: nem todo video do mesmo canal tem a facecam na mesma posicao. Layout de
live muda entre gravacoes, e um preset por canal aplicaria a caixa errada nos
videos que mudaram, silenciosamente e em todos eles.

A correcao certa e por VIDEO: a deteccao automatica continua sendo o padrao, e
quando ela erra o dono corrige aquele job — `jobs.facecam_rect`, que ja existe e
ja tem precedencia sobre a deteccao. Nada por canal.

Coluna nova e vazia em producao (nenhum perfil chegou a fixar caixa), entao
derrubar nao perde dado de ninguem.

Revision ID: 0014_facecam_so_por_video
Revises: 0013_recuperacao_de_senha
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014_facecam_so_por_video"
down_revision: Union[str, None] = "0013_recuperacao_de_senha"
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("profiles", schema=None) as batch_op:
        batch_op.drop_column("facecam_rect")


def downgrade() -> None:
    with op.batch_alter_table("profiles", schema=None) as batch_op:
        batch_op.add_column(sa.Column("facecam_rect", sa.Text(), nullable=True))
