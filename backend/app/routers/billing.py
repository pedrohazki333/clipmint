"""
Recarga de créditos: criar a cobrança, acompanhar, e receber o aviso do gateway.

Três endpoints, e o terceiro é o único da API que não pertence a um usuário
logado — quem se identifica ali é o Mercado Pago, pela assinatura.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import current_user
from app.schemas import (
    BalanceResponse,
    CatalogResponse,
    EstimateRequest,
    EstimateResponse,
    LedgerEntryResponse,
    PaymentStatusResponse,
    SubscribeRequest,
    SubscriptionResponse,
    TopupRequest,
    TopupResponse,
)
from app.models import CreditLedger, Payment, Subscription, User
from app.services import (
    billing,
    credits,
    mercadopago,
    payments,
    quota,
    subscriptions,
    usage,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["billing"])


@router.post("/topup", response_model=TopupResponse, status_code=status.HTTP_201_CREATED)
async def criar_topup(
    payload: TopupRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> TopupResponse:
    """Gera a cobrança Pix de um pacote e devolve o QR e o copia-e-cola."""
    pagamento = await payments.criar_topup(db, user, payload.creditos)
    return TopupResponse(
        payment_id=pagamento.id,
        creditos=int(pagamento.credits_granted),
        valor_brl=pagamento.amount_brl_gross,
        status=pagamento.status,
        qr_code=pagamento.pix_qr_code,
        qr_code_base64=pagamento.pix_qr_base64,
        expires_at=pagamento.pix_expires_at,
    )


@router.get("/payments/{payment_id}", response_model=PaymentStatusResponse)
async def status_do_pagamento(
    payment_id: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> PaymentStatusResponse:
    """O estado da cobrança — e é este endpoint que a tela consulta em laço.

    Ele não se limita a ler o banco: pergunta ao gateway e aplica o resultado.
    É o que faz o Pix funcionar mesmo quando o webhook não chega — em
    desenvolvimento na máquina de casa ele NUNCA chega, porque o Mercado Pago
    não alcança um localhost. Sem isto, todo teste de ponta a ponta ficaria
    preso em "aguardando pagamento" com o dinheiro já pago.
    """
    pagamento = await db.scalar(select(Payment).where(Payment.id == payment_id))
    # 404 e não 403 quando é de outro usuário: quem não é dono não precisa nem
    # saber que o pagamento existe.
    if pagamento is None or pagamento.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Pagamento não encontrado."
        )

    try:
        pagamento = await payments.sincronizar(db, pagamento)
    except mercadopago.MercadoPagoIndisponivel as exc:
        # O gateway fora do ar não é erro do usuário nem motivo para esconder o
        # que já se sabe: devolve o último estado conhecido.
        logger.warning("Consulta ao gateway falhou para %s: %s", payment_id, exc)

    return PaymentStatusResponse(
        payment_id=pagamento.id,
        status=pagamento.status,
        creditos=int(pagamento.credits_granted),
        saldo=await credits.saldo(db, user.id),
    )


@router.post("/webhook", include_in_schema=False)
async def webhook(request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    """Notificação do Mercado Pago.

    Aberto na cerca de perímetro (ver `_ROTAS_ABERTAS` em main.py) porque quem
    chama é o gateway, que não tem sessão nem o token da instalação. O que
    autentica aqui é a assinatura HMAC — e por isso ela é obrigatória: sem
    segredo configurado, este endpoint recusa tudo.

    E, mesmo com assinatura válida, o corpo da notificação não é acreditado. Ele
    diz "olhe o recurso X"; quem diz se foi pago é a consulta ao gateway feita
    logo abaixo.
    """
    corpo = {}
    try:
        corpo = await request.json()
    except Exception:  # noqa: BLE001 - corpo vazio ou não-JSON é possível
        pass

    # O `data.id` chega na query string e/ou no corpo, conforme o tipo de
    # notificação. A assinatura é calculada sobre o que veio na query.
    data_id = request.query_params.get("data.id") or str(
        (corpo.get("data") or {}).get("id") or ""
    )

    if not mercadopago.assinatura_valida(
        x_signature=request.headers.get("x-signature"),
        x_request_id=request.headers.get("x-request-id"),
        data_id=data_id,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Assinatura inválida."
        )

    if not data_id:
        logger.warning("Webhook assinado mas sem data.id: %s", str(corpo)[:200])
        return {"ok": True}

    tipo = (
        request.query_params.get("type")
        or request.query_params.get("topic")
        or str(corpo.get("type") or corpo.get("topic") or "")
    ).lower()

    try:
        tratado = await _rotear_webhook(db, tipo, data_id)
    except mercadopago.MercadoPagoIndisponivel as exc:
        # 503 de propósito: o Mercado Pago reenvia o que falhou, e reenviar é
        # exatamente o que se quer quando a falha foi nossa e é temporária.
        logger.error("Gateway indisponível ao tratar webhook de %s: %s", data_id, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Não foi possível confirmar agora.",
        ) from exc

    if not tratado:
        # Assinatura válida, recurso desconhecido: é notificação de algo que este
        # build não trata. 200 para o MP parar de reenviar — reenviar não faria a
        # linha aparecer.
        logger.info("Webhook não tratado (tipo=%r, id=%s)", tipo, data_id)

    return {"ok": True}


#: Nomes que o Mercado Pago usa para cada assunto de notificação.
_TIPOS_CICLO = {"subscription_authorized_payment", "authorized_payment"}
_TIPOS_ASSINATURA = {"subscription_preapproval", "preapproval"}


async def _rotear_webhook(db: AsyncSession, tipo: str, data_id: str) -> bool:
    """Descobre a que este `data.id` se refere e trata. True se tratou.

    O roteamento é por tipo QUANDO ele é reconhecido, e por consulta ao NOSSO
    banco quando não é. A diferença importa: procurar em casa é barato e não
    falha; chutar um `GET /authorized_payments/<id>` com um id que não é disso
    devolveria 404, viraria 503 daqui, e o Mercado Pago ficaria reenviando para
    sempre uma notificação que nunca vamos conseguir tratar.
    """
    if tipo in _TIPOS_CICLO:
        return await subscriptions.creditar_ciclo(db, data_id) is not None

    if tipo in _TIPOS_ASSINATURA:
        assinatura = await db.scalar(
            select(Subscription).where(
                Subscription.gateway_preapproval_id == data_id
            )
        )
        if assinatura is None:
            return False
        await subscriptions.sincronizar(db, assinatura)
        return True

    # Tipo desconhecido ou ausente: procura em casa, sem chutar endpoint.
    if await payments.sincronizar_por_gateway_id(db, data_id) is not None:
        return True

    assinatura = await db.scalar(
        select(Subscription).where(Subscription.gateway_preapproval_id == data_id)
    )
    if assinatura is not None:
        await subscriptions.sincronizar(db, assinatura)
        return True

    return False


# ─── O que as telas leem ──────────────────────────────────────────────────────


@router.get("/balance", response_model=BalanceResponse)
async def saldo_atual(
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> BalanceResponse:
    """Saldo e se ele está baixo. É a chamada da navbar, feita em toda página."""
    config = await billing.get_config(db)
    saldo = await credits.saldo(db, user.id)
    limite = int(config.saldo_baixo_threshold or 0)
    return BalanceResponse(
        saldo=saldo, threshold=limite, baixo=bool(limite and saldo < limite)
    )


@router.get("/catalog", response_model=CatalogResponse)
async def catalogo(
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> CatalogResponse:
    """Pacotes e planos com o preço JÁ RESOLVIDO pelo servidor.

    O preço de cada pacote sai de `billing.preco_do_pacote`, a mesma função que
    a criação da cobrança usa. Se a tela calculasse o preço sozinha, ela e a
    cobrança poderiam discordar — e quem discordaria por último é a fatura.
    """
    config = await billing.get_config(db)
    return CatalogResponse(
        credito_avulso_brl=config.credito_avulso_brl,
        pacotes=[
            {
                "creditos": int(p["creditos"]),
                "preco_brl": billing.preco_do_pacote(config, int(p["creditos"])),
            }
            for p in (config.pacotes or [])
        ],
        planos=[
            {
                "code": str(pl["code"]),
                "nome": str(pl["nome"]),
                "valor_brl": pl["valor_brl"],
                "creditos_mes": int(pl["creditos_mes"]),
            }
            for pl in (config.planos or [])
        ],
    )


@router.get("/ledger", response_model=list[LedgerEntryResponse])
async def extrato(
    limit: int = 50,
    offset: int = 0,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> list[CreditLedger]:
    """O extrato desta pessoa, do mais recente para trás.

    Devolve o extrato CRU, com hold e release inclusive, e não um resumo já
    mastigado: é o registro do que aconteceu com o dinheiro dela, e esconder as
    linhas intermediárias é o que faz o usuário achar que foi cobrado duas vezes
    quando vê só o débito ao lado da reserva.
    """
    limite = max(1, min(limit, 200))
    linhas = await db.execute(
        select(CreditLedger)
        .where(CreditLedger.user_id == user.id)
        .order_by(CreditLedger.created_at.desc(), CreditLedger.id.desc())
        .limit(limite)
        .offset(max(0, offset))
    )
    return linhas.scalars().all()


@router.post("/estimate", response_model=EstimateResponse)
async def estimar(
    payload: EstimateRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> EstimateResponse:
    """Quanto ESTE vídeo vai custar, antes de gastar qualquer coisa.

    Passa pelas mesmas guardas da criação do job — live e teto de duração — e
    levanta os mesmos 422. É de propósito: uma tela que promete um vídeo que o
    servidor vai recusar em seguida é pior que nenhuma tela.

    O custo é calculado pela MESMA função que reserva o crédito
    (`usage.custo_em_creditos`); duas fórmulas dariam dois números, e o que a
    pessoa aprovou seria o errado.
    """
    meta = await quota.probe(payload.youtube_url)
    quota.check_live(meta)
    quota.check_duration(meta)

    custo = usage.custo_em_creditos(meta.duration)
    saldo = await credits.saldo(db, user.id)
    return EstimateResponse(
        minutos=int(meta.duration // 60),
        creditos=custo,
        saldo=saldo,
        suficiente=saldo >= custo,
        faltam=max(0, custo - saldo),
    )


# ─── Assinatura ───────────────────────────────────────────────────────────────


@router.post(
    "/subscribe",
    response_model=SubscriptionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def assinar(
    payload: SubscribeRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> Subscription:
    """Inicia a assinatura e devolve o link onde a pessoa autoriza o cartão.

    O cartão é digitado NA PÁGINA DO MERCADO PAGO, nunca aqui — ver
    services/subscriptions.py.
    """
    return await subscriptions.assinar(db, user, payload.plan_code)


@router.get("/subscription", response_model=SubscriptionResponse | None)
async def minha_assinatura(
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> Subscription | None:
    """A assinatura viva desta pessoa, ou `null`.

    Sincroniza com o gateway quando ainda está pendente: é assim que a tela
    descobre que a autorização foi concluída, sem depender de o webhook ter
    chegado (mesma razão do polling do Pix — D115).
    """
    assinatura = await subscriptions.do_usuario(db, user.id)
    if assinatura is None:
        return None

    if assinatura.status == "pending":
        try:
            assinatura = await subscriptions.sincronizar(db, assinatura)
        except mercadopago.MercadoPagoIndisponivel as exc:
            logger.warning("Consulta da assinatura %s falhou: %s", assinatura.id, exc)

    return assinatura


@router.post("/subscription/cancel", response_model=SubscriptionResponse)
async def cancelar_assinatura(
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> Subscription:
    """Cancela a assinatura. Os créditos já concedidos continuam no saldo."""
    assinatura = await subscriptions.do_usuario(db, user.id)
    if assinatura is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Você não tem uma assinatura ativa.",
        )
    return await subscriptions.cancelar(db, assinatura)
