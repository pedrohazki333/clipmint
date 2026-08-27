"""
Assinatura mensal: criar, acompanhar, cancelar, e creditar cada ciclo.

## O fluxo, e por que ele é assim

O `preapproval` é criado **sem `card_token_id`**. Com ele, o cartão teria que
ser digitado na nossa página e tokenizado por nós — escopo de PCI que um produto
recém-lançado, com recebedor em CPF, não tem por que assumir. Sem ele a
assinatura nasce `pending`, o gateway devolve um `init_point`, e o cartão é
digitado na página do Mercado Pago. Nós nunca vemos número de cartão.

## Onde os créditos do ciclo entram

Pelo MESMO caminho da recarga avulsa: cada cobrança de ciclo vira uma linha em
`payments` (com `tipo='assinatura'` e `subscription_id`), e o crédito é lançado
por `payments._marcar_pago_e_creditar`. Não existe um segundo mecanismo de
crédito aqui, de propósito — a idempotência que a Fatia 2 construiu
(`gateway_payment_id` único + transição condicional de status) vale igual para
o ciclo, e um caminho paralelo teria que reconstruir tudo isso e erraria.

## O que continua NÃO verificado

Nada disto foi exercido contra o Mercado Pago de verdade: não há credencial
nesta máquina. O formato do `authorized_payment`, o nome do campo que liga a
cobrança à assinatura e o vocabulário completo de status são o que a
documentação descreve, e estão isolados em `mercadopago.py` para serem
confirmados contra o sandbox antes do primeiro cliente real.
"""

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status as http_status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Payment, Subscription, User
from app.services import billing, mercadopago, payments

logger = logging.getLogger(__name__)

#: Estados em que a assinatura ainda ocupa o lugar: não dá para ter duas.
VIVAS = ("pending", "active", "paused")


def _agora() -> datetime:
    return datetime.now(timezone.utc)


async def plano(db: AsyncSession, plan_code: str) -> dict[str, Any]:
    """O plano da configuração, ou 422. O preço sai daqui, nunca do cliente."""
    config = await billing.get_config(db)
    for p in config.planos or []:
        if str(p.get("code")) == plan_code:
            return p
    disponiveis = [str(p.get("code")) for p in (config.planos or [])]
    raise HTTPException(
        status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=f"Plano {plan_code!r} não existe. Disponíveis: {disponiveis}.",
    )


async def do_usuario(db: AsyncSession, user_id: str) -> Subscription | None:
    """A assinatura viva desta pessoa, se houver."""
    return await db.scalar(
        select(Subscription)
        .where(Subscription.user_id == user_id, Subscription.status.in_(VIVAS))
        .order_by(Subscription.created_at.desc())
    )


async def assinar(db: AsyncSession, user: User, plan_code: str) -> Subscription:
    """Cria a assinatura no gateway e devolve a linha com o link de autorização."""
    if not settings.public_base_url:
        # Mandar alguém para o gateway sem caminho de volta deixaria a pessoa
        # presa lá com o cartão já autorizado. Falha fechado.
        logger.error("PUBLIC_BASE_URL vazia: assinatura recusada")
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Assinaturas ainda não estão configuradas neste servidor.",
        )

    existente = await do_usuario(db, user.id)
    if existente is not None:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=(
                "Você já tem uma assinatura. Cancele a atual antes de assinar "
                "outro plano."
            ),
        )

    p = await plano(db, plan_code)
    valor = Decimal(str(p["valor_brl"]))
    creditos = int(p["creditos_mes"])

    # A linha nasce antes da chamada ao gateway, pelo mesmo motivo do top-up: se
    # o processo morrer no meio, o pior caso é uma assinatura pendente sem link
    # (que ninguém consegue autorizar), e não uma assinatura viva no Mercado
    # Pago sem registro aqui.
    assinatura = Subscription(
        user_id=user.id,
        plan_code=plan_code,
        # Cópia congelada: quem assinou o Pro a R$ 99,90 continua nesse valor
        # quando o Pro subir de preço.
        valor_brl=valor,
        creditos_mes=creditos,
        status="pending",
        gateway="mercadopago",
    )
    db.add(assinatura)
    await db.commit()

    try:
        criada = await mercadopago.criar_preapproval(
            titulo=f"ClipMint {p.get('nome', plan_code)}",
            valor=valor,
            email=user.email,
            referencia=assinatura.id,
            back_url=f"{settings.public_base_url.rstrip('/')}/recarga",
        )
    except mercadopago.MercadoPagoNaoConfigurado as exc:
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Pagamentos ainda não estão configurados neste servidor.",
        ) from exc
    except mercadopago.MercadoPagoIndisponivel as exc:
        logger.error("Gateway indisponível ao criar assinatura: %s", exc)
        raise HTTPException(
            status_code=http_status.HTTP_502_BAD_GATEWAY,
            detail="Não foi possível iniciar a assinatura agora. Tente de novo.",
        ) from exc

    assinatura.gateway_preapproval_id = criada.gateway_preapproval_id
    assinatura.init_point = criada.init_point
    assinatura.status = criada.status
    await db.commit()
    await db.refresh(assinatura)

    logger.info(
        "Assinatura %s criada para %s (plano %s)", assinatura.id, user.id, plan_code
    )
    return assinatura


async def sincronizar(db: AsyncSession, assinatura: Subscription) -> Subscription:
    """Pergunta ao gateway o estado real da assinatura e aplica.

    Mesmo princípio do pagamento (D106): quem diz se a assinatura está ativa é
    uma consulta autenticada, nunca o corpo de uma notificação.
    """
    if not assinatura.gateway_preapproval_id:
        return assinatura

    bruto = await mercadopago.consultar_preapproval(assinatura.gateway_preapproval_id)
    novo = mercadopago.traduzir_status_assinatura(bruto)

    if novo != assinatura.status:
        if novo == "active" and assinatura.started_at is None:
            assinatura.started_at = _agora()
        if novo == "canceled" and assinatura.canceled_at is None:
            assinatura.canceled_at = _agora()
        assinatura.status = novo
        assinatura.updated_at = _agora()
        await db.commit()
        await db.refresh(assinatura)
        logger.info("Assinatura %s agora é %s", assinatura.id, novo)

    return assinatura


async def cancelar(db: AsyncSession, assinatura: Subscription) -> Subscription:
    """Cancela no gateway e aqui.

    O gateway primeiro: marcar como cancelada aqui e falhar lá deixaria a pessoa
    achando que parou de pagar enquanto o cartão continua sendo debitado — o
    erro mais caro possível nesta direção.
    """
    if assinatura.gateway_preapproval_id:
        try:
            await mercadopago.cancelar_preapproval(assinatura.gateway_preapproval_id)
        except mercadopago.MercadoPagoIndisponivel as exc:
            logger.error("Falha ao cancelar %s no gateway: %s", assinatura.id, exc)
            raise HTTPException(
                status_code=http_status.HTTP_502_BAD_GATEWAY,
                detail=(
                    "Não foi possível cancelar agora. Tente de novo em instantes "
                    "— sua assinatura NÃO foi cancelada."
                ),
            ) from exc

    assinatura.status = "canceled"
    assinatura.canceled_at = _agora()
    assinatura.updated_at = _agora()
    await db.commit()
    await db.refresh(assinatura)
    logger.info("Assinatura %s cancelada", assinatura.id)
    return assinatura


async def _pagamento_do_ciclo(
    db: AsyncSession, assinatura: Subscription, authorized_payment_id: str, valor: Decimal
) -> Payment:
    """Acha ou cria a linha de `payments` desta cobrança de ciclo.

    O índice único em `gateway_payment_id` é quem resolve a corrida: duas
    notificações simultâneas do mesmo ciclo tentam inserir, uma ganha, a outra
    leva IntegrityError e relê. O savepoint é o que permite tratar isso sem
    envenenar a transação inteira no Postgres.
    """
    existente = await db.scalar(
        select(Payment).where(Payment.gateway_payment_id == authorized_payment_id)
    )
    if existente is not None:
        return existente

    novo = Payment(
        user_id=assinatura.user_id,
        gateway="mercadopago",
        gateway_payment_id=authorized_payment_id,
        tipo="assinatura",
        subscription_id=assinatura.id,
        amount_brl_gross=valor,
        credits_granted=int(assinatura.creditos_mes),
        status="pending",
    )
    try:
        async with db.begin_nested():
            db.add(novo)
        return novo
    except IntegrityError:
        achado = await db.scalar(
            select(Payment).where(Payment.gateway_payment_id == authorized_payment_id)
        )
        if achado is None:
            raise
        return achado


async def creditar_ciclo(
    db: AsyncSession, authorized_payment_id: str
) -> Payment | None:
    """Uma cobrança de ciclo foi notificada: confere e concede os créditos do mês.

    `None` quando a cobrança não é nossa, não foi paga, ou a assinatura não é
    conhecida — nos três casos não há o que creditar, e inventar seria pior.
    """
    bruto = await mercadopago.consultar_authorized_payment(authorized_payment_id)

    preapproval_id = str(
        bruto.get("preapproval_id") or mercadopago._percorrer(bruto, "preapproval_id") or ""
    )
    if not preapproval_id:
        logger.warning(
            "Cobrança de ciclo %s sem preapproval_id — nada a creditar",
            authorized_payment_id,
        )
        return None

    assinatura = await db.scalar(
        select(Subscription).where(
            Subscription.gateway_preapproval_id == preapproval_id
        )
    )
    if assinatura is None:
        logger.info("Ciclo de assinatura desconhecida: %s", preapproval_id)
        return None

    if mercadopago.traduzir_status(bruto) != "paid":
        logger.info(
            "Ciclo %s ainda não pago (%s)", authorized_payment_id, bruto.get("status")
        )
        return None

    pagamento = await _pagamento_do_ciclo(
        db, assinatura, authorized_payment_id, Decimal(str(assinatura.valor_brl))
    )
    creditou = await payments._marcar_pago_e_creditar(
        db,
        pagamento,
        bruto,
        descricao=f"Assinatura {assinatura.plan_code} — créditos do mês",
    )

    if creditou:
        # A assinatura está viva e pagou: se ela ainda constava como pendente
        # (a notificação do ciclo pode chegar antes da autorização), o pagamento
        # é a prova de que está ativa.
        if assinatura.status != "active":
            assinatura.status = "active"
            assinatura.started_at = assinatura.started_at or _agora()
        assinatura.current_period_end = _agora() + timedelta(days=30)
        assinatura.updated_at = _agora()

    await db.commit()
    await db.refresh(pagamento)
    return pagamento
