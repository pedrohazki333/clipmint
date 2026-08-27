"""pagamento: o estado de cobranca que morreu sem ser paga

A 0006 permitia `pending`, `paid`, `refunded` e `chargeback` em
`payments.status`. Faltava o desfecho mais comum de um Pix: o QR expirar sem
ninguem pagar.

Sem esse estado, uma cobranca expirada ficava `pending` para sempre — e a tela
de recarga, que para de consultar quando o pagamento sai de pendente, seguia
mostrando "Aguardando pagamento" num codigo que ja nao pode ser pago.

`expired` e `failed` do gateway colapsam neste unico valor de proposito: a
CAUSA e diferente, mas a resposta e a mesma dos dois lados. Para o usuario,
"gere outra cobranca"; para o monitor, "isto nunca foi receita". Um segundo
valor daria uma distincao que ninguem usaria.

A lista completa de status da Orders API foi confirmada na documentacao em
27/08/2026: created, processed, processing, action_required, canceled,
charged_back, expired, failed, refunded.

Revision ID: 0011_pagamento_expirado
Revises: 0010_monitor_financeiro
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0011_pagamento_expirado"
down_revision: Union[str, None] = "0010_monitor_financeiro"
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[Sequence[str], None] = None

_CHECK = "ck_payments_status"
_ANTIGO = "status IN ('pending', 'paid', 'refunded', 'chargeback')"
_NOVO = "status IN ('pending', 'paid', 'refunded', 'chargeback', 'expired')"


def upgrade() -> None:
    # O CHECK e aplicado pelos DOIS dialetos (diferente da chave estrangeira da
    # 0007): no SQLite isso significa recriar a tabela, que e o que o batch faz.
    with op.batch_alter_table("payments", schema=None) as batch_op:
        batch_op.drop_constraint(_CHECK, type_="check")
        batch_op.create_check_constraint(_CHECK, _NOVO)


def downgrade() -> None:
    op.execute("UPDATE payments SET status = 'pending' WHERE status = 'expired'")
    with op.batch_alter_table("payments", schema=None) as batch_op:
        batch_op.drop_constraint(_CHECK, type_="check")
        batch_op.create_check_constraint(_CHECK, _ANTIGO)
