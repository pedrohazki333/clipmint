"""trial: 120 creditos, para caber um video real antes de assinar

O bonus de boas-vindas nasceu em 30 creditos e o aviso de saldo baixo em 120 —
que e um video medio deste produto (~2h). O resultado e que TODO usuario novo
entrava ja vendo o alerta ambar, e o alerta estava certo: com 30 creditos nao
dava para processar um video tipico. O trial existe para a pessoa ver o produto
funcionar UMA vez, e com 30 ela nao chegava la.

A migracao so troca o valor se ele ainda for o padrao antigo (30). Se o dono ja
tiver ajustado a configuracao pela UI, este deploy nao pode desfazer isso —
migracao de dado que sobrescreve escolha do operador e a que ninguem espera.

Nao mexe em saldo de ninguem: o bonus e concedido no cadastro, e quem ja se
cadastrou ja recebeu o que valia na epoca.

Revision ID: 0009_trial_120
Revises: 0008_assinatura_pendente
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009_trial_120"
down_revision: Union[str, None] = "0008_assinatura_pendente"
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[Sequence[str], None] = None

_ANTIGO = 30
_NOVO = 120


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE billing_config SET creditos_gratis_cadastro = :novo "
            "WHERE id = 1 AND creditos_gratis_cadastro = :antigo"
        ).bindparams(novo=_NOVO, antigo=_ANTIGO)
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE billing_config SET creditos_gratis_cadastro = :antigo "
            "WHERE id = 1 AND creditos_gratis_cadastro = :novo"
        ).bindparams(novo=_NOVO, antigo=_ANTIGO)
    )
