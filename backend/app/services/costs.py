"""
Quanto UM vídeo custou a nós — e as tarifas correntes que dizem isso.

Este módulo é o lado do CUSTO. O lado da receita é `credits.py` (o que o
usuário pagou) e `payments.py` (o que entrou pelo gateway). O monitor cruza os
dois; nenhum dos dois sabe do outro.

## A regra que dá sentido ao histórico

Tarifa muda: a Anthropic reprecifica, o dólar sobe, a AssemblyAI troca de
modelo. Se o custo fosse recalculado na hora de LER, corrigir uma tarifa hoje
reescreveria o lucro de todos os meses passados — e o painel deixaria de bater
com as faturas que já foram pagas.

Por isso o cálculo acontece UMA vez, no fim do processamento, e o resultado vai
para `usage_events` junto de um `rate_snapshot` com as tarifas usadas. A
`cost_config` guarda o que vale AGORA, para o evento seguinte e para projeção.

## O que este módulo não faz

Não estima o que pode medir. Minutos vêm da duração real da mídia baixada;
tokens vêm do campo `usage` que a própria API devolve. `storage_usd_per_video` é
a única estimativa, e está marcada como tal.
"""

import logging
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CostConfig

logger = logging.getLogger(__name__)

CONFIG_ID = 1

#: Um milhão de tokens — a unidade em que as tarifas de LLM são cotadas.
MTOK = Decimal("1000000")

#: Os valores com que a configuração nasce. A migração 0010 semeia ESTES mesmos
#: valores, escritos lá literalmente (migração não importa código da aplicação),
#: e `test_costs.py` compara as duas cópias para não divergirem em silêncio.
#:
#: `tax_pct_on_revenue` é PLACEHOLDER até o contador confirmar.
CONFIG_PADRAO: dict = {
    "assemblyai_usd_per_min": Decimal("0.0035"),
    "llm_rates": {
        "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
        "claude-opus-4-8": {"input": 5.00, "output": 25.00},
    },
    "storage_usd_per_video": Decimal("0.005"),
    "fx_usd_brl": Decimal("5.40"),
    "fx_eur_brl": Decimal("5.90"),
    "fixed_cost_brl_month": Decimal("57"),
    "tax_pct_on_revenue": Decimal("15"),
    "gateway_fee_pct": Decimal("1.0"),
}

_CAMPOS_EDITAVEIS = frozenset(CONFIG_PADRAO)


async def get_config(db: AsyncSession) -> CostConfig:
    """As tarifas vigentes, criando a linha com os padrões se ainda não existir.

    Em produção a linha nasce com a migração 0010; este caminho existe para o
    banco montado direto pelo metadata (os testes) e para um banco novo que
    ainda não migrou.
    """
    config = await db.scalar(select(CostConfig).where(CostConfig.id == CONFIG_ID))
    if config is None:
        logger.info("cost_config ausente; criando a linha 1 com os padrões")
        config = CostConfig(id=CONFIG_ID, **CONFIG_PADRAO)
        db.add(config)
        await db.flush()
    return config


async def update_config(
    db: AsyncSession, *, updated_by_user_id: str | None = None, **campos
) -> CostConfig:
    """Altera as tarifas correntes. Não toca em evento nenhum já gravado."""
    config = await get_config(db)

    desconhecidos = set(campos) - _CAMPOS_EDITAVEIS
    if desconhecidos:
        raise ValueError(f"campos de custo desconhecidos: {sorted(desconhecidos)}")

    for chave, valor in campos.items():
        setattr(config, chave, valor)
    config.updated_by_user_id = updated_by_user_id

    await db.flush()
    logger.info("cost_config alterada: %s", sorted(campos))
    return config


@dataclass
class Custo:
    """O custo de um vídeo, decomposto, mais as tarifas que o produziram."""

    transcription_cost_usd: Decimal
    analysis_cost_usd: Decimal
    storage_cost_usd: Decimal
    total_cost_usd: Decimal
    total_cost_brl: Decimal
    rate_snapshot: dict[str, Any] = field(default_factory=dict)


def _usd(valor: Decimal) -> Decimal:
    """Seis casas: a tarifa de transcrição é 0,0035 e o arredondamento cedo some com ela."""
    return valor.quantize(Decimal("0.000001"), ROUND_HALF_UP)


def _brl(valor: Decimal) -> Decimal:
    return valor.quantize(Decimal("0.0001"), ROUND_HALF_UP)


def calcular(
    config: CostConfig,
    *,
    transcription_minutes: Decimal | float | int,
    transcription_provider: str,
    analysis_model: str | None,
    input_tokens: int,
    output_tokens: int,
    cobrar_storage: bool = True,
) -> Custo:
    """Calcula o custo de um vídeo e congela as tarifas usadas.

    Duas situações são MARCADAS no snapshot em vez de viradas em zero, porque um
    monitor que zera o que não reconhece mente para baixo — e custo subestimado
    é o erro que faz aceitar cliente deficitário:

      - **modelo sem tarifa cadastrada**: a análise entra como 0 e o snapshot
        registra `analysis_rate_missing`, para o painel poder mostrar a lacuna;
      - **provedor de transcrição diferente do cotado**: usa a tarifa que existe
        e registra `transcription_rate_mismatch`, porque um custo aproximado e
        sinalizado vale mais que um zero silencioso.
    """
    minutos = Decimal(str(transcription_minutes or 0))
    por_minuto = Decimal(str(config.assemblyai_usd_per_min))
    transcricao = _usd(por_minuto * minutos)

    tarifas = dict(config.llm_rates or {})
    tarifa = tarifas.get(analysis_model or "")
    faltou_tarifa = tarifa is None

    if faltou_tarifa:
        if input_tokens or output_tokens:
            logger.warning(
                "Sem tarifa cadastrada para o modelo %r — a análise deste vídeo "
                "entra com custo 0 e fica marcada no snapshot. Cadastre em "
                "cost_config.llm_rates.",
                analysis_model,
            )
        analise = Decimal("0")
        entrada = saida = Decimal("0")
    else:
        entrada = Decimal(str(tarifa.get("input", 0)))
        saida = Decimal(str(tarifa.get("output", 0)))
        analise = _usd(
            (Decimal(input_tokens or 0) / MTOK * entrada)
            + (Decimal(output_tokens or 0) / MTOK * saida)
        )

    storage = (
        _usd(Decimal(str(config.storage_usd_per_video))) if cobrar_storage else Decimal("0")
    )

    total_usd = _usd(transcricao + analise + storage)
    fx = Decimal(str(config.fx_usd_brl))
    total_brl = _brl(total_usd * fx)

    provedor_cotado = "assemblyai"
    snapshot: dict[str, Any] = {
        "assemblyai_usd_per_min": str(por_minuto),
        "storage_usd_per_video": str(config.storage_usd_per_video),
        "fx_usd_brl": str(fx),
        "analysis_model": analysis_model,
        "llm_input_usd_per_mtok": str(entrada),
        "llm_output_usd_per_mtok": str(saida),
        "transcription_provider": transcription_provider,
    }
    if faltou_tarifa:
        snapshot["analysis_rate_missing"] = True
    if transcription_provider and transcription_provider != provedor_cotado:
        snapshot["transcription_rate_mismatch"] = True
        logger.warning(
            "Transcrição por %r mas a tarifa cadastrada é da %s — custo "
            "aproximado, marcado no snapshot.",
            transcription_provider,
            provedor_cotado,
        )

    return Custo(
        transcription_cost_usd=transcricao,
        analysis_cost_usd=analise,
        storage_cost_usd=storage,
        total_cost_usd=total_usd,
        total_cost_brl=total_brl,
        rate_snapshot=snapshot,
    )
