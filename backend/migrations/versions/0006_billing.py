"""billing: creditos, pagamentos e assinaturas

Cria o schema de cobranca do produto publico. A unidade e o CREDITO: 1 credito =
1 minuto de video de origem, sempre inteiro.

O que esta migracao NAO faz, de proposito:

  - nao concede credito de boas-vindas a quem ja tem conta. Quem existia comeca
    em zero; o bonus e concedido no cadastro, daqui para a frente. Dar credito
    retroativo seria distribuir dinheiro por efeito colateral de um deploy.
  - nao toca no pipeline. O consumo de credito entra depois, na sua fatia.

As tres restricoes que carregam o peso do desenho:

  - `payments.gateway_payment_id` UNIQUE: a idempotencia do webhook mora no
    banco. Duas notificacoes simultaneas do mesmo pagamento passariam por
    qualquer verificacao feita em Python; nenhuma passa por um indice unico.
  - indices unicos parciais no ledger: um pagamento credita uma vez, um job
    segura uma vez e cobra uma vez.
  - `CHECK (id = 1)` em billing_config: e o que mantem a configuracao sendo uma
    configuracao, em vez de virar um historico acidental.

Revision ID: 0006_billing
Revises: 0005_perfis
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_billing"
down_revision: Union[str, None] = "0005_perfis"
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[Sequence[str], None] = None


#: JSONB no Postgres, JSON comum no SQLite dos testes.
JSONVariant = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


#: Precos e cotas iniciais. `planos` sao PLACEHOLDER: os valores de Essencial e
#: Pro sao para o dono ajustar pela configuracao, nao numeros pesquisados.
CONFIG_INICIAL = {
    "id": 1,
    "credito_avulso_brl": 0.12,
    "pacotes": [
        {"creditos": 300, "preco_brl": None},
        {"creditos": 600, "preco_brl": None},
        {"creditos": 1500, "preco_brl": None},
    ],
    "planos": [
        {
            "code": "essencial",
            "nome": "Essencial",
            "valor_brl": "49.90",
            "creditos_mes": 500,
        },
        {
            "code": "pro",
            "nome": "Pro",
            "valor_brl": "99.90",
            "creditos_mes": 1200,
        },
    ],
    "creditos_gratis_cadastro": 30,
    # Um video medio deste produto tem ~2h: "saldo baixo" e nao ter para mais um.
    "saldo_baixo_threshold": 120,
}


def upgrade() -> None:
    # ── subscriptions vem antes de payments: payments referencia ela ──────────
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("plan_code", sa.String(), nullable=False),
        sa.Column("valor_brl", sa.Numeric(12, 2), nullable=False),
        sa.Column("creditos_mes", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("gateway", sa.String(), nullable=False),
        sa.Column("gateway_preapproval_id", sa.String(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "gateway_preapproval_id", name="uq_subscriptions_gateway_preapproval_id"
        ),
        sa.CheckConstraint(
            "status IN ('active', 'canceled', 'paused')", name="ck_subscriptions_status"
        ),
        sa.CheckConstraint("creditos_mes >= 0", name="ck_subscriptions_creditos_mes"),
        sa.CheckConstraint("valor_brl >= 0", name="ck_subscriptions_valor"),
    )
    with op.batch_alter_table("subscriptions", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_subscriptions_user_id"), ["user_id"], unique=False
        )

    op.create_table(
        "payments",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("gateway", sa.String(), nullable=False),
        sa.Column("gateway_payment_id", sa.String(), nullable=False),
        sa.Column("tipo", sa.String(), nullable=False),
        sa.Column("subscription_id", sa.String(), nullable=True),
        sa.Column("amount_brl_gross", sa.Numeric(12, 2), nullable=False),
        sa.Column("gateway_fee_brl", sa.Numeric(12, 2), nullable=True),
        sa.Column("amount_brl_net", sa.Numeric(12, 2), nullable=True),
        sa.Column("credits_granted", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("status_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pix_qr_code", sa.Text(), nullable=True),
        sa.Column("pix_qr_base64", sa.Text(), nullable=True),
        sa.Column("pix_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_gateway_payload", JSONVariant, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["subscription_id"], ["subscriptions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('pending', 'paid', 'refunded', 'chargeback')",
            name="ck_payments_status",
        ),
        sa.CheckConstraint("tipo IN ('topup', 'assinatura')", name="ck_payments_tipo"),
        sa.CheckConstraint("credits_granted >= 0", name="ck_payments_creditos"),
        sa.CheckConstraint("amount_brl_gross >= 0", name="ck_payments_valor"),
    )
    with op.batch_alter_table("payments", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_payments_user_id"), ["user_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_payments_subscription_id"), ["subscription_id"], unique=False
        )
        # UNIQUE, e nao apenas indexado: e esta restricao que garante que o
        # mesmo pagamento do gateway nunca vira duas linhas.
        batch_op.create_index(
            batch_op.f("ix_payments_gateway_payment_id"),
            ["gateway_payment_id"],
            unique=True,
        )

    op.create_table(
        "credit_ledger",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("tipo", sa.String(), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("balance_after", sa.Integer(), nullable=False),
        sa.Column("ref_payment_id", sa.String(), nullable=True),
        sa.Column("ref_usage_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("descricao", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["ref_payment_id"], ["payments.id"]),
        sa.ForeignKeyConstraint(["ref_usage_id"], ["jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "tipo IN ('topup', 'debito', 'estorno', 'bonus', 'ajuste', 'hold', 'release')",
            name="ck_credit_ledger_tipo",
        ),
        sa.CheckConstraint("amount <> 0", name="ck_credit_ledger_amount_nao_zero"),
    )
    with op.batch_alter_table("credit_ledger", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_credit_ledger_user_id"), ["user_id"], unique=False
        )
        batch_op.create_index(
            "ix_credit_ledger_user_created", ["user_id", "created_at"], unique=False
        )
        # ── "cobra uma vez so", garantido pelo banco ──────────────────────────
        batch_op.create_index(
            "uq_credit_ledger_topup_por_pagamento",
            ["ref_payment_id"],
            unique=True,
            postgresql_where=sa.text("tipo = 'topup' AND ref_payment_id IS NOT NULL"),
            sqlite_where=sa.text("tipo = 'topup' AND ref_payment_id IS NOT NULL"),
        )
        batch_op.create_index(
            "uq_credit_ledger_hold_por_job",
            ["ref_usage_id"],
            unique=True,
            postgresql_where=sa.text("tipo = 'hold' AND ref_usage_id IS NOT NULL"),
            sqlite_where=sa.text("tipo = 'hold' AND ref_usage_id IS NOT NULL"),
        )
        batch_op.create_index(
            "uq_credit_ledger_debito_por_job",
            ["ref_usage_id"],
            unique=True,
            postgresql_where=sa.text("tipo = 'debito' AND ref_usage_id IS NOT NULL"),
            sqlite_where=sa.text("tipo = 'debito' AND ref_usage_id IS NOT NULL"),
        )

    op.create_table(
        "billing_config",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("credito_avulso_brl", sa.Numeric(12, 4), nullable=False),
        sa.Column("pacotes", JSONVariant, nullable=False),
        sa.Column("planos", JSONVariant, nullable=False),
        sa.Column("creditos_gratis_cadastro", sa.Integer(), nullable=False),
        sa.Column("saldo_baixo_threshold", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_by_user_id", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("id = 1", name="ck_billing_config_linha_unica"),
        sa.CheckConstraint(
            "credito_avulso_brl > 0", name="ck_billing_config_preco_positivo"
        ),
        sa.CheckConstraint(
            "creditos_gratis_cadastro >= 0",
            name="ck_billing_config_bonus_nao_negativo",
        ),
    )

    # A linha 1 nasce com a migracao: sem ela o servico teria que lidar com
    # "ainda nao existe configuracao" em todo lugar que le preco.
    op.bulk_insert(
        sa.table(
            "billing_config",
            sa.column("id", sa.Integer),
            sa.column("credito_avulso_brl", sa.Numeric(12, 4)),
            sa.column("pacotes", JSONVariant),
            sa.column("planos", JSONVariant),
            sa.column("creditos_gratis_cadastro", sa.Integer),
            sa.column("saldo_baixo_threshold", sa.Integer),
        ),
        [CONFIG_INICIAL],
    )

    # server_default garante que as contas que ja existem fiquem em 0, e nao em
    # NULL — a coluna e NOT NULL e o cache nunca pode ser "desconhecido".
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "credit_balance",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("credit_balance")

    op.drop_table("billing_config")

    with op.batch_alter_table("credit_ledger", schema=None) as batch_op:
        batch_op.drop_index("uq_credit_ledger_debito_por_job")
        batch_op.drop_index("uq_credit_ledger_hold_por_job")
        batch_op.drop_index("uq_credit_ledger_topup_por_pagamento")
        batch_op.drop_index("ix_credit_ledger_user_created")
        batch_op.drop_index(batch_op.f("ix_credit_ledger_user_id"))
    op.drop_table("credit_ledger")

    with op.batch_alter_table("payments", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_payments_gateway_payment_id"))
        batch_op.drop_index(batch_op.f("ix_payments_subscription_id"))
        batch_op.drop_index(batch_op.f("ix_payments_user_id"))
    op.drop_table("payments")

    with op.batch_alter_table("subscriptions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_subscriptions_user_id"))
    op.drop_table("subscriptions")
