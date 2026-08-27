"""ledger: o extrato sobrevive ao job apagado, e devolve a reserva uma vez so

Duas correcoes no `credit_ledger`, as duas descobertas ao ligar o consumo de
credito no pipeline:

1. **`ref_usage_id` passa a ser ON DELETE SET NULL.** A 0006 criou a chave
   estrangeira comum, e com ela o DELETE de um job seria RECUSADO enquanto
   houvesse lancamento apontando para ele — o extrato passaria a mandar no que o
   usuario pode fazer com o trabalho dele. Apagar o lancamento junto tambem nao
   serve: e registro financeiro. O elo nao se perde: `descricao` guarda o id do
   job em texto.

2. **Indice unico parcial para `release`.** Hold e debito ja tinham o seu na
   0006; a devolucao ficou de fora. Sem ele, uma reconciliacao repetida
   devolveria a reserva duas vezes — credito de graca.

**A alteracao da chave estrangeira so acontece no Postgres**, e nao por
preguica: o SQLite nao aplica chave estrangeira a menos que `PRAGMA
foreign_keys` seja ligado, e este projeto nunca liga (o proprio
`app/scripts/migrate_to_postgres.py` conta com isso). Ou seja, no SQLite a
restricao ja nao barrava o DELETE — nao ha o que corrigir. Alem disso, a FK que
a 0006 criou nasceu SEM NOME no SQLite: o `credit_ledger_ref_usage_id_fkey` e
um nome que o Postgres gera sozinho, e tentar removê-lo pelo nome quebra a
cadeia de migracoes inteira no SQLite — que e o banco dos testes e da versao
pessoal. Foi assim que este caso apareceu.

O indice unico de `release`, esse, vale nos dois.

Revision ID: 0007_ledger_job_delete
Revises: 0006_billing
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007_ledger_job_delete"
down_revision: Union[str, None] = "0006_billing"
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[Sequence[str], None] = None

#: Nome com que a 0006 criou a chave estrangeira. O Alembic nomeia FK de tabela
#: nova sem convencao explicita, entao no Postgres ela nasceu como
#: `credit_ledger_ref_usage_id_fkey` (padrao do proprio Postgres).
_FK_ANTIGA = "credit_ledger_ref_usage_id_fkey"
_FK_NOVA = "fk_credit_ledger_ref_usage_id_jobs"


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.drop_constraint(_FK_ANTIGA, "credit_ledger", type_="foreignkey")
        op.create_foreign_key(
            _FK_NOVA,
            "credit_ledger",
            "jobs",
            ["ref_usage_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.create_index(
        "uq_credit_ledger_release_por_job",
        "credit_ledger",
        ["ref_usage_id"],
        unique=True,
        postgresql_where=sa.text("tipo = 'release' AND ref_usage_id IS NOT NULL"),
        sqlite_where=sa.text("tipo = 'release' AND ref_usage_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_credit_ledger_release_por_job", table_name="credit_ledger")

    if op.get_bind().dialect.name == "postgresql":
        op.drop_constraint(_FK_NOVA, "credit_ledger", type_="foreignkey")
        op.create_foreign_key(
            _FK_ANTIGA, "credit_ledger", "jobs", ["ref_usage_id"], ["id"]
        )
