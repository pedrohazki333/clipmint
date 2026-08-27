"""
Compra de créditos: criar a cobrança e creditar quando ela for paga.

Duas propriedades sustentam este módulo, e as duas estão no BANCO, não aqui:

  - **crédito uma vez só.** Quem decide se este processo é o que credita é a
    transição de status do próprio pagamento, feita como UPDATE condicional:
    `... WHERE id = :id AND status <> 'paid'`. Duas notificações simultâneas do
    mesmo pagamento entram as duas; o lock de linha do Postgres serializa, uma
    volta com rowcount 1 e credita, a outra volta com 0 e não faz nada. O índice
    único do ledger (`ref_payment_id` com `tipo='topup'`) fica como segunda
    barreira, para o caso de um caminho de escrita novo esquecer esta regra.

  - **preço não vem do cliente.** O usuário escolhe um PACOTE; o valor sai da
    billing_config no servidor e é congelado na linha de `payments`.
"""

import logging
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException, status as http_status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Payment, User
from app.services import billing, credits, mercadopago

logger = logging.getLogger(__name__)


def _agora() -> datetime:
    return datetime.now(timezone.utc)


async def _validar_pacote(db: AsyncSession, creditos: int) -> Decimal:
    """O pacote existe na configuração? Devolve o preço que o servidor cobra.

    Só pacotes configurados são aceitos. Aceitar quantidade arbitrária abriria
    duas portas de uma vez: comprar 1 crédito por R$ 0,00 depois de arredondar,
    e transformar a tela de recarga num campo livre que ninguém revisou.
    """
    config = await billing.get_config(db)
    disponiveis = {int(p.get("creditos", 0)) for p in (config.pacotes or [])}
    if creditos not in disponiveis:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Pacote de {creditos} créditos não existe. Disponíveis: "
                f"{sorted(disponiveis)}."
            ),
        )
    return billing.preco_do_pacote(config, creditos)


async def criar_topup(db: AsyncSession, user: User, creditos: int) -> Payment:
    """Cria a cobrança Pix de um pacote e devolve o pagamento com o QR.

    A linha nasce e é COMMITADA antes de falar com o gateway, com um id de
    gateway provisório. A ordem é deliberada: se o processo morrer entre a
    cobrança e o registro dela, o pior caso é uma linha pendente sem QR — que
    ninguém consegue pagar e que expira sozinha. Ao contrário, uma cobrança
    existente no MP sem linha aqui seria um usuário que pagou e não recebeu.

    O id local vai como `X-Idempotency-Key` e como `external_reference`: um
    retry de rede não vira duas cobranças para a mesma compra.
    """
    valor = await _validar_pacote(db, creditos)

    pagamento = Payment(
        user_id=user.id,
        gateway="mercadopago",
        tipo="topup",
        amount_brl_gross=valor,
        credits_granted=creditos,
        status="pending",
        status_updated_at=_agora(),
    )
    # Provisório e único: a coluna é NOT NULL e UNIQUE, e o id de verdade só
    # existe depois da resposta do gateway.
    pagamento.gateway_payment_id = f"local:{pagamento.id}"
    db.add(pagamento)
    await db.commit()

    try:
        cobranca = await mercadopago.criar_cobranca_pix(
            valor=valor,
            descricao=f"{creditos} créditos ClipMint",
            email=user.email,
            referencia=pagamento.id,
            idempotency_key=pagamento.id,
        )
    except mercadopago.MercadoPagoNaoConfigurado as exc:
        logger.error("Cobrança impossível: %s", exc)
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Pagamentos ainda não estão configurados neste servidor.",
        ) from exc
    except mercadopago.MercadoPagoIndisponivel as exc:
        logger.error("Gateway indisponível ao criar cobrança: %s", exc)
        raise HTTPException(
            status_code=http_status.HTTP_502_BAD_GATEWAY,
            detail="Não foi possível gerar o Pix agora. Tente de novo em instantes.",
        ) from exc

    pagamento.gateway_payment_id = cobranca.gateway_payment_id
    pagamento.pix_qr_code = cobranca.qr_code
    pagamento.pix_qr_base64 = cobranca.qr_code_base64
    pagamento.pix_expires_at = cobranca.expires_at
    pagamento.raw_gateway_payload = cobranca.raw
    await db.commit()
    await db.refresh(pagamento)

    logger.info(
        "Cobrança Pix criada: %s créditos por R$ %s (pagamento %s)",
        creditos,
        valor,
        pagamento.id,
    )
    return pagamento


async def _marcar_pago_e_creditar(
    db: AsyncSession, pagamento: Payment, bruto: dict, descricao: str | None = None
) -> bool:
    """Transição para `paid` + crédito, uma vez só. True se ESTA chamada creditou.

    O UPDATE condicional é quem arbitra: só um processo consegue mudar o status
    de não-pago para pago, e só esse credita. A condição precisa estar DENTRO do
    UPDATE, e não num `if` antes dele: um `if` em Python lê um valor que já pode
    estar velho, enquanto o `WHERE status <> 'paid'` é avaliado pelo banco com a
    linha travada.

    Não commita — quem chamou fecha a transação. É o mesmo contrato de
    `credits.lancar`, e é o que permite um teste segurar a transação aberta para
    verificar que a segunda chamada realmente bloqueia.
    """
    resultado = await db.execute(
        update(Payment)
        .where(Payment.id == pagamento.id, Payment.status != "paid")
        .values(
            status="paid",
            paid_at=_agora(),
            status_updated_at=_agora(),
            raw_gateway_payload=bruto,
        )
    )
    if resultado.rowcount != 1:
        logger.info("Pagamento %s já estava creditado; nada a fazer", pagamento.id)
        return False

    await credits.lancar(
        db,
        user_id=pagamento.user_id,
        tipo="topup",
        amount=int(pagamento.credits_granted),
        ref_payment_id=pagamento.id,
        descricao=descricao or f"Compra de {pagamento.credits_granted} créditos",
    )
    logger.info(
        "Pagamento %s confirmado: +%s créditos para %s",
        pagamento.id,
        pagamento.credits_granted,
        pagamento.user_id,
    )
    return True


async def sincronizar(db: AsyncSession, pagamento: Payment) -> Payment:
    """Pergunta ao gateway o estado real e aplica o que ele responder.

    É o mesmo caminho do webhook e do polling da tela, de propósito: existir um
    só lugar que credita significa que o webhook não chegar (rede, servidor
    local, notificação perdida) não deixa ninguém sem crédito — a tela pergunta
    e resolve.
    """
    if pagamento.status == "paid":
        return pagamento
    if pagamento.gateway_payment_id.startswith("local:"):
        # A cobrança nunca chegou a existir no gateway; não há o que consultar.
        return pagamento

    bruto = await mercadopago.consultar(pagamento.gateway_payment_id)
    novo = mercadopago.traduzir_status(bruto)

    if novo == "paid":
        await _marcar_pago_e_creditar(db, pagamento, bruto)
        await db.commit()
    elif novo != pagamento.status:
        pagamento.status = novo
        pagamento.status_updated_at = _agora()
        pagamento.raw_gateway_payload = bruto
        await db.commit()

    await db.refresh(pagamento)
    return pagamento


async def sincronizar_por_gateway_id(
    db: AsyncSession, gateway_payment_id: str
) -> Payment | None:
    """O caminho do webhook: acha o pagamento pelo id do gateway e sincroniza."""
    pagamento = await db.scalar(
        select(Payment).where(Payment.gateway_payment_id == gateway_payment_id)
    )
    if pagamento is None:
        return None
    return await sincronizar(db, pagamento)
