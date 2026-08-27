"""
Lançar à mão o que não passou pelo gateway.

O webhook do Mercado Pago cobre o caminho normal. Isto cobre o resto, que num
negócio pequeno não é exceção rara:

  - Pix recebido direto na chave, fora do checkout;
  - cortesia, permuta, cliente antigo em acordo de boca;
  - estorno e chargeback, que precisam REVERTER receita já contada.

**Escreve nas MESMAS tabelas do gateway.** Não existe uma segunda contabilidade
para o que foi lançado à mão: `payments` e `subscriptions` são as mesmas, o
painel soma tudo junto, e o que distingue é a coluna `gateway`, que fica com
`manual`. Uma tabela paralela daria dois totais que discordariam no primeiro
fechamento de mês.

## Idempotência de um lançamento manual

`gateway_payment_id` é único, e o lançamento manual usa `manual:<referência>`.
Quando o dono informa a referência do Pix (o E2E do comprovante), registrar o
mesmo recebimento duas vezes é RECUSADO pelo banco — que é o erro mais provável
aqui: conferir o extrato, lançar, e lançar de novo na semana seguinte.

Sem referência, cada lançamento é único por construção e a proteção não existe.
Por isso o campo é pedido, não obrigatório: quem tem o comprovante ganha a
garantia, quem não tem consegue lançar mesmo assim.
"""

import logging
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from fastapi import HTTPException, status as http_status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import STATUS_PAGAMENTO, Payment, Subscription, User
from app.services import payments as payments_service

logger = logging.getLogger(__name__)

GATEWAY = "manual"

#: Estados para os quais um pagamento pode ser movido à mão. `pending` fica de
#: fora: um lançamento manual só é feito depois de o dinheiro ter entrado.
STATUS_ALVO = ("paid", "refunded", "chargeback")


def _agora() -> datetime:
    return datetime.now(timezone.utc)


async def _usuario_por_email(db: AsyncSession, email: str) -> User:
    normalizado = (email or "").strip().lower()
    user = await db.scalar(select(User).where(User.email == normalizado))
    if user is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=f"Não existe conta com o e-mail {normalizado!r}.",
        )
    return user


async def registrar_pagamento(
    db: AsyncSession,
    *,
    email: str,
    valor_brl: Decimal,
    taxa_brl: Decimal | None = None,
    creditos: int = 0,
    conceder_creditos: bool = False,
    referencia: str | None = None,
    pago_em: datetime | None = None,
    plan_code: str | None = None,
) -> Payment:
    """Registra um recebimento que não veio pelo gateway.

    `conceder_creditos` separa duas coisas que costumam ser confundidas:
    registrar RECEITA (o que o monitor precisa) e entregar CRÉDITO ao usuário (o
    que ele espera se pagou de verdade). Um Pix recebido na chave quer os dois;
    uma correção de contabilidade quer só o primeiro. Conceder por padrão daria
    crédito de graça toda vez que o dono só quisesse acertar o extrato.

    O crédito, quando concedido, passa pelo MESMO caminho do gateway
    (`payments._marcar_pago_e_creditar`): a idempotência da Fatia 2 vale igual, e
    um segundo mecanismo de crédito erraria onde aquele já acerta.
    """
    user = await _usuario_por_email(db, email)

    if valor_brl < 0:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="O valor não pode ser negativo. Para reverter receita, mude o "
            "status do pagamento para estorno ou chargeback.",
        )
    if conceder_creditos and creditos <= 0:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Para conceder créditos, informe quantos.",
        )

    identificador = f"{GATEWAY}:{(referencia or uuid4().hex).strip()}"
    quando = pago_em or _agora()

    pagamento = Payment(
        user_id=user.id,
        gateway=GATEWAY,
        gateway_payment_id=identificador,
        tipo="assinatura" if plan_code else "topup",
        amount_brl_gross=valor_brl,
        gateway_fee_brl=taxa_brl,
        amount_brl_net=None if taxa_brl is None else valor_brl - taxa_brl,
        credits_granted=int(creditos or 0),
        # Nasce PENDENTE mesmo tendo sido recebido: quem move para `paid` é a
        # transição condicional de `_marcar_pago_e_creditar`, e é ela que
        # garante que o crédito saia uma vez só.
        status="pending",
        paid_at=None,
        status_updated_at=_agora(),
        raw_gateway_payload={
            "origem": "lançamento manual",
            "referencia": referencia,
            "plan_code": plan_code,
        },
    )
    db.add(pagamento)

    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=(
                f"Já existe um lançamento com a referência {referencia!r}. "
                f"Este recebimento provavelmente já foi registrado."
            ),
        ) from exc

    if conceder_creditos:
        await payments_service._marcar_pago_e_creditar(
            db,
            pagamento,
            {"origem": "manual", "referencia": referencia},
            descricao=f"Crédito lançado à mão ({creditos} créditos)",
        )
        # A transição acima usa o instante de agora; se o dono informou quando
        # o dinheiro entrou, é essa data que vale para o mês fechar certo.
        pagamento.paid_at = quando
    else:
        pagamento.status = "paid"
        pagamento.paid_at = quando
        pagamento.status_updated_at = _agora()

    await db.flush()
    logger.info(
        "Pagamento manual de R$ %s para %s (créditos: %s)",
        valor_brl,
        user.email,
        creditos if conceder_creditos else 0,
    )
    return pagamento


async def mudar_status(
    db: AsyncSession, *, payment_id: str, novo: str
) -> Payment:
    """Move um pagamento para estorno ou chargeback.

    Serve para QUALQUER pagamento, não só os manuais: um chargeback do cartão
    chega por e-mail do gateway antes de virar notificação, e o dono precisa
    poder tirar aquela receita do mês na hora.

    **Não mexe no saldo do usuário.** Tirar crédito de quem já processou vídeo
    deixaria a conta negativa e o extrato incoerente; se for para cobrar de
    volta, isso é um `ajuste` explícito no ledger, com registro de quem fez.
    """
    if novo not in STATUS_ALVO:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Status inválido. Use um de: {', '.join(STATUS_ALVO)}.",
        )
    assert novo in STATUS_PAGAMENTO

    pagamento = await db.scalar(select(Payment).where(Payment.id == payment_id))
    if pagamento is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Pagamento não encontrado.",
        )

    pagamento.status = novo
    pagamento.status_updated_at = _agora()
    if novo != "paid":
        # Sai da receita do mês: o painel conta `status = 'paid'` por `paid_at`.
        pagamento.paid_at = None
    await db.flush()
    logger.info("Pagamento %s agora é %s", payment_id, novo)
    return pagamento


async def registrar_assinatura(
    db: AsyncSession,
    *,
    email: str,
    plan_code: str,
    valor_brl: Decimal,
    creditos_mes: int,
    started_at: datetime | None = None,
) -> Subscription:
    """Registra uma assinatura acordada fora do gateway.

    Sem isso, um assinante de acordo de boca some do MRR — que é um dos números
    que este painel existe para mostrar.
    """
    user = await _usuario_por_email(db, email)

    viva = await db.scalar(
        select(Subscription).where(
            Subscription.user_id == user.id,
            Subscription.status.in_(("pending", "active", "paused")),
        )
    )
    if viva is not None:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="Esta conta já tem uma assinatura viva.",
        )

    assinatura = Subscription(
        user_id=user.id,
        plan_code=plan_code,
        valor_brl=valor_brl,
        creditos_mes=int(creditos_mes or 0),
        status="active",
        gateway=GATEWAY,
        # Sem preapproval: não há recorrência automática num acordo de boca, e
        # deixar o campo nulo é o que impede o webhook de tentar casar com ela.
        gateway_preapproval_id=None,
        started_at=started_at or _agora(),
    )
    db.add(assinatura)
    await db.flush()
    logger.info("Assinatura manual %s para %s", plan_code, user.email)
    return assinatura


async def cancelar_assinatura(db: AsyncSession, *, subscription_id: str) -> Subscription:
    """Encerra uma assinatura manual. Os créditos já concedidos ficam."""
    assinatura = await db.scalar(
        select(Subscription).where(Subscription.id == subscription_id)
    )
    if assinatura is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Assinatura não encontrada.",
        )
    if assinatura.gateway != GATEWAY:
        # Cancelar uma assinatura de cartão aqui marcaria como encerrada sem
        # avisar o Mercado Pago — e o cartão continuaria sendo debitado (D118).
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=(
                "Esta assinatura é do gateway. Cancele pelo fluxo do usuário, "
                "que avisa o Mercado Pago antes de encerrar."
            ),
        )

    assinatura.status = "canceled"
    assinatura.canceled_at = _agora()
    assinatura.updated_at = _agora()
    await db.flush()
    return assinatura
