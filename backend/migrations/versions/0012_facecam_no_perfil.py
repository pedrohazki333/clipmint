"""perfil: a caixa da facecam fixada pelo dono do canal

A caixa da cam e detectada por heuristica a cada job. Quando ela erra, o painel
do clipe sai com uma tira de gameplay no topo e a cabeca do streamer cortada —
aconteceu em 01/09/2026, com a cam do Mount saindo 540x440 em vez de 552x359
porque a borda de cima tinha um decimo do gradiente das outras tres.

O detector foi corrigido, mas detectar continua sendo palpite: cada canal novo
e uma aposta. Esta coluna deixa o dono do perfil CONGELAR a caixa depois de
conferir um video — o canal e sempre o mesmo, a cam fica sempre no mesmo lugar,
e o que era palpite por video vira dado por canal.

Fica no PERFIL, nao no usuario: uma pessoa pode cortar dois canais com layouts
diferentes, e a caixa e propriedade do canal.

NULO e o normal e significa "detecte" — nao existe caixa padrao razoavel para
inventar. A ordem no pipeline passa a ser: caixa do job (informada na geracao)
-> caixa do perfil -> deteccao automatica.

Texto com JSON, igual a `jobs.facecam_rect`: as duas guardam a mesma coisa e
divergir no tipo so criaria duas formas de ler o mesmo dado.

Revision ID: 0012_facecam_no_perfil
Revises: 0011_pagamento_expirado
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012_facecam_no_perfil"
down_revision: Union[str, None] = "0011_pagamento_expirado"
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("profiles", schema=None) as batch_op:
        batch_op.add_column(sa.Column("facecam_rect", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("profiles", schema=None) as batch_op:
        batch_op.drop_column("facecam_rect")
