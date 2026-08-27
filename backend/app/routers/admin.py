"""
O painel do dono: quanto entrou, quanto custou, quanto sobrou.

**Tudo aqui é fechado por `require_owner`, no BACKEND.** Esconder na interface
não é proteção: um usuário comum que descubra a URL tem que levar 403 do
servidor, não uma tela em branco. O router também só é registrado no build
público — na versão pessoal não há receita nem cliente para monitorar.

Não confundir com Siege X e Melhorar vídeo, que ficam FORA do build público.
Este fica dentro dele, e é justamente por isso que a porta precisa de fechadura.
"""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import require_owner
from app.schemas import (
    CostConfigResponse,
    CostConfigUpdate,
    ManualPaymentRequest,
    ManualStatusRequest,
    ManualSubscriptionRequest,
    OverviewComparadoResponse,
    OverviewResponse,
    PaymentAdminResponse,
    SerieDiaResponse,
    SubscriptionAdminResponse,
    UsuarioNoPeriodoResponse,
)
from app.models import Payment, Subscription, User
from app.services import admin_metrics, costs, manual_entries

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


def _periodo(mes: str | None) -> admin_metrics.Periodo:
    """`YYYY-MM` no fuso de São Paulo. Omitido = mês corrente."""
    if not mes:
        return admin_metrics.mes_corrente()
    try:
        quando = datetime.strptime(mes, "%Y-%m")
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Período inválido. Use o formato AAAA-MM, por exemplo 2026-08.",
        ) from exc
    return admin_metrics.mes(quando.year, quando.month)


@router.get("/overview", response_model=OverviewComparadoResponse)
async def overview(
    mes: str | None = None,
    _: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> OverviewComparadoResponse:
    """O mês pedido e o anterior, lado a lado.

    Os dois juntos porque um número sozinho não diz se melhorou: R$ 400 de lucro
    é ótimo depois de R$ 100 e péssimo depois de R$ 900.
    """
    periodo = _periodo(mes)
    return OverviewComparadoResponse(
        atual=OverviewResponse.model_validate(
            await admin_metrics.visao_geral(db, periodo)
        ),
        anterior=OverviewResponse.model_validate(
            await admin_metrics.visao_geral(db, admin_metrics.mes_anterior(periodo))
        ),
    )


@router.get("/series", response_model=list[SerieDiaResponse])
async def series(
    mes: str | None = None,
    _: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> list:
    """Receita, custo e lucro por dia do mês, no fuso de São Paulo.

    Devolve o mês INTEIRO, com zeros nos dias sem movimento: um gráfico que pula
    os dias vazios comprime o eixo e faz uma semana parada parecer um dia.
    """
    return await admin_metrics.serie_diaria(db, _periodo(mes))


@router.get("/users", response_model=list[UsuarioNoPeriodoResponse])
async def users(
    mes: str | None = None,
    _: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> list:
    """Receita contra custo por usuário, do mais deficitário para o mais lucrativo."""
    return await admin_metrics.por_usuario(db, _periodo(mes))


@router.get("/cost-config", response_model=CostConfigResponse)
async def ler_tarifas(
    _: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    return await costs.get_config(db)


@router.put("/cost-config", response_model=CostConfigResponse)
async def alterar_tarifas(
    payload: CostConfigUpdate,
    dono: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    """Altera as tarifas correntes.

    Não toca em evento já gravado: cada um congelou as suas no `rate_snapshot`.
    Corrigir o câmbio hoje muda a projeção e os eventos futuros, nunca o lucro
    do mês passado.
    """
    campos = payload.model_dump(exclude_none=True)
    if not campos:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Nenhum campo para alterar.",
        )
    config = await costs.update_config(db, updated_by_user_id=dono.id, **campos)
    await db.commit()
    await db.refresh(config)
    return config


# ─── Lançamento manual ────────────────────────────────────────────────────────
#
# Escreve nas MESMAS tabelas do gateway — o que distingue é `gateway='manual'`.
# Uma segunda contabilidade daria dois totais que discordariam no primeiro
# fechamento de mês.


@router.get("/payments", response_model=list[PaymentAdminResponse])
async def listar_pagamentos(
    limite: int = 50,
    _: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> list:
    """Os pagamentos mais recentes, do gateway e manuais juntos."""
    linhas = await db.execute(
        select(Payment)
        .order_by(Payment.created_at.desc(), Payment.id.desc())
        .limit(max(1, min(limite, 200)))
    )
    return linhas.scalars().all()


@router.post(
    "/payments",
    response_model=PaymentAdminResponse,
    status_code=status.HTTP_201_CREATED,
)
async def lancar_pagamento(
    payload: ManualPaymentRequest,
    _: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    """Registra um recebimento que não passou pelo gateway."""
    pagamento = await manual_entries.registrar_pagamento(
        db,
        email=payload.email,
        valor_brl=payload.valor_brl,
        taxa_brl=payload.taxa_brl,
        creditos=payload.creditos,
        conceder_creditos=payload.conceder_creditos,
        referencia=payload.referencia,
        pago_em=payload.pago_em,
        plan_code=payload.plan_code,
    )
    await db.commit()
    await db.refresh(pagamento)
    return pagamento


@router.patch("/payments/{payment_id}", response_model=PaymentAdminResponse)
async def mudar_status_do_pagamento(
    payment_id: str,
    payload: ManualStatusRequest,
    _: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    """Marca estorno ou chargeback, tirando a receita do mês.

    Não mexe no saldo de créditos: retirar crédito de quem já processou vídeo
    deixaria a conta negativa. Se for para cobrar de volta, isso é um `ajuste`
    explícito no extrato.
    """
    pagamento = await manual_entries.mudar_status(
        db, payment_id=payment_id, novo=payload.status
    )
    await db.commit()
    await db.refresh(pagamento)
    return pagamento


@router.post(
    "/subscriptions",
    response_model=SubscriptionAdminResponse,
    status_code=status.HTTP_201_CREATED,
)
async def lancar_assinatura(
    payload: ManualSubscriptionRequest,
    _: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    """Registra uma assinatura acordada fora do gateway, para ela contar no MRR."""
    assinatura = await manual_entries.registrar_assinatura(
        db,
        email=payload.email,
        plan_code=payload.plan_code,
        valor_brl=payload.valor_brl,
        creditos_mes=payload.creditos_mes,
        started_at=payload.started_at,
    )
    await db.commit()
    await db.refresh(assinatura)
    return assinatura


@router.get("/subscriptions", response_model=list[SubscriptionAdminResponse])
async def listar_assinaturas(
    _: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> list:
    linhas = await db.execute(
        select(Subscription).order_by(Subscription.created_at.desc())
    )
    return linhas.scalars().all()


@router.delete("/subscriptions/{subscription_id}", response_model=SubscriptionAdminResponse)
async def encerrar_assinatura_manual(
    subscription_id: str,
    _: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    """Encerra uma assinatura MANUAL. As do gateway saem pelo fluxo do usuário,
    que avisa o Mercado Pago antes — encerrar aqui deixaria o cartão sendo
    debitado (D118)."""
    assinatura = await manual_entries.cancelar_assinatura(
        db, subscription_id=subscription_id
    )
    await db.commit()
    await db.refresh(assinatura)
    return assinatura
