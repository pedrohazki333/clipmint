"""assinatura: o estado 'pending' e o link de autorizacao

A 0006 permitia `active`, `canceled` e `paused` em `subscriptions.status`. Falta
o estado em que a assinatura passa mais tempo no comeco: **criada no gateway e
esperando a pessoa autorizar**.

O fluxo escolhido (ver DECISOES D116) e o `preapproval` SEM `card_token_id`: o
Mercado Pago devolve um link, a pessoa entra o cartao NA PAGINA DELE, e so
depois a assinatura vira autorizada. Entre uma coisa e outra existe uma linha
real, que precisa de um estado real — usar `paused` para isso seria mentir no
banco para nao mexer num CHECK.

`init_point` guarda esse link: sem ele, quem fecha a aba no meio do caminho nao
tem como voltar, e clicar de novo criaria uma segunda assinatura no gateway.

Revision ID: 0008_assinatura_pendente
Revises: 0007_ledger_job_delete
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008_assinatura_pendente"
down_revision: Union[str, None] = "0007_ledger_job_delete"
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[Sequence[str], None] = None

_CHECK = "ck_subscriptions_status"
_ANTIGO = "status IN ('active', 'canceled', 'paused')"
_NOVO = "status IN ('pending', 'active', 'canceled', 'paused')"


def upgrade() -> None:
    op.add_column("subscriptions", sa.Column("init_point", sa.String(), nullable=True))

    # O CHECK e aplicado pelos DOIS dialetos (diferente da chave estrangeira da
    # 0007, que o SQLite ignora): aqui a alteracao precisa acontecer nos dois.
    # No SQLite isso significa recriar a tabela, que e o que o batch mode faz.
    with op.batch_alter_table("subscriptions", schema=None) as batch_op:
        batch_op.drop_constraint(_CHECK, type_="check")
        batch_op.create_check_constraint(_CHECK, _NOVO)


def downgrade() -> None:
    with op.batch_alter_table("subscriptions", schema=None) as batch_op:
        batch_op.drop_constraint(_CHECK, type_="check")
        batch_op.create_check_constraint(_CHECK, _ANTIGO)

    op.drop_column("subscriptions", "init_point")
