"""monitor: custo por video processado e as tarifas correntes

Duas tabelas, e as duas sao o LADO DO CUSTO. O `credit_ledger` da 0006 registra
o que o usuario pagou; estas registram o que nos pagamos. E o cruzamento dos
dois que diz se um cliente da lucro.

`usage_events` e um registro por VIDEO, nao por clipe: a fatura da AssemblyAI e
da Anthropic e por minuto de video, e um job que gera oito clipes custa o mesmo
que um que gera dois.

`cost_config` guarda as tarifas CORRENTES. O historico nao mora la — cada evento
congela no `rate_snapshot` as tarifas que usou, e e isso que faz corrigir uma
tarifa hoje nao reescrever o lucro do mes passado.

As tarifas de LLM ficam num MAPA por modelo (`llm_rates`), e nao em duas colunas
fixas: o modelo de analise pode mudar, e com colunas o evento antigo passaria a
ser lido com a tarifa do modelo novo. Semeadas com os dois modelos plausiveis
hoje — o `claude-sonnet-4-6`, que e o que o `config.py` roda de fato, e o
`claude-opus-4-8`, para a troca nao exigir migracao.

Revision ID: 0010_monitor_financeiro
Revises: 0009_trial_120
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_monitor_financeiro"
down_revision: Union[str, None] = "0009_trial_120"
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[Sequence[str], None] = None

JSONVariant = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

#: Tarifas iniciais. Precos de tabela da Anthropic e da AssemblyAI consultados
#: em 27/08/2026; o imposto e PLACEHOLDER ate o contador confirmar.
CONFIG_INICIAL = {
    "id": 1,
    "assemblyai_usd_per_min": 0.0035,
    "llm_rates": {
        "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
        "claude-opus-4-8": {"input": 5.00, "output": 25.00},
    },
    "storage_usd_per_video": 0.005,
    "fx_usd_brl": 5.40,
    "fx_eur_brl": 5.90,
    "fixed_cost_brl_month": 57,
    "tax_pct_on_revenue": 15,
    "gateway_fee_pct": 1.0,
}


def upgrade() -> None:
    op.create_table(
        "cost_config",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("assemblyai_usd_per_min", sa.Numeric(12, 6), nullable=False),
        sa.Column("llm_rates", JSONVariant, nullable=False),
        sa.Column("storage_usd_per_video", sa.Numeric(12, 6), nullable=False),
        sa.Column("fx_usd_brl", sa.Numeric(12, 4), nullable=False),
        sa.Column("fx_eur_brl", sa.Numeric(12, 4), nullable=False),
        sa.Column("fixed_cost_brl_month", sa.Numeric(12, 2), nullable=False),
        sa.Column("tax_pct_on_revenue", sa.Numeric(6, 3), nullable=False),
        sa.Column("gateway_fee_pct", sa.Numeric(6, 3), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_by_user_id", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("id = 1", name="ck_cost_config_linha_unica"),
        sa.CheckConstraint("fx_usd_brl > 0", name="ck_cost_config_fx_positivo"),
        sa.CheckConstraint(
            "tax_pct_on_revenue >= 0", name="ck_cost_config_imposto_nao_negativo"
        ),
    )

    op.bulk_insert(
        sa.table(
            "cost_config",
            sa.column("id", sa.Integer),
            sa.column("assemblyai_usd_per_min", sa.Numeric(12, 6)),
            sa.column("llm_rates", JSONVariant),
            sa.column("storage_usd_per_video", sa.Numeric(12, 6)),
            sa.column("fx_usd_brl", sa.Numeric(12, 4)),
            sa.column("fx_eur_brl", sa.Numeric(12, 4)),
            sa.column("fixed_cost_brl_month", sa.Numeric(12, 2)),
            sa.column("tax_pct_on_revenue", sa.Numeric(6, 3)),
            sa.column("gateway_fee_pct", sa.Numeric(6, 3)),
        ),
        [CONFIG_INICIAL],
    )

    op.create_table(
        "usage_events",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("job_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_video_url", sa.Text(), nullable=True),
        sa.Column("source_minutes", sa.Numeric(10, 3), nullable=True),
        sa.Column("transcription_provider", sa.String(), nullable=True),
        sa.Column("transcription_minutes", sa.Numeric(10, 3), nullable=True),
        sa.Column("transcription_cost_usd", sa.Numeric(12, 6), nullable=False),
        sa.Column("analysis_model", sa.String(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("analysis_cost_usd", sa.Numeric(12, 6), nullable=False),
        sa.Column("storage_cost_usd", sa.Numeric(12, 6), nullable=False),
        sa.Column("total_cost_usd", sa.Numeric(12, 6), nullable=False),
        sa.Column("total_cost_brl", sa.Numeric(12, 4), nullable=False),
        sa.Column("rate_snapshot", JSONVariant, nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("credits_charged", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('success', 'failed', 'deleted')", name="ck_usage_events_status"
        ),
        sa.CheckConstraint("credits_charged >= 0", name="ck_usage_events_creditos"),
    )
    with op.batch_alter_table("usage_events", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_usage_events_user_id"), ["user_id"], unique=False
        )
        batch_op.create_index(
            "ix_usage_events_user_created", ["user_id", "created_at"], unique=False
        )
        batch_op.create_index(
            "ix_usage_events_created_at", ["created_at"], unique=False
        )
        # Um video, um evento: a garantia mora no banco, para um caminho
        # terminal disparado duas vezes nao contar o custo em dobro.
        batch_op.create_index(
            "uq_usage_events_job",
            ["job_id"],
            unique=True,
            postgresql_where=sa.text("job_id IS NOT NULL"),
            sqlite_where=sa.text("job_id IS NOT NULL"),
        )


def downgrade() -> None:
    with op.batch_alter_table("usage_events", schema=None) as batch_op:
        batch_op.drop_index("uq_usage_events_job")
        batch_op.drop_index("ix_usage_events_created_at")
        batch_op.drop_index("ix_usage_events_user_created")
        batch_op.drop_index(batch_op.f("ix_usage_events_user_id"))
    op.drop_table("usage_events")
    op.drop_table("cost_config")
