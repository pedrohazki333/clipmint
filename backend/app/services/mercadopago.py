"""
O gateway: tudo que fala HTTP com o Mercado Pago mora aqui.

Nenhum outro módulo conhece URL, formato de payload ou nome de campo do MP. Não
é organização por gosto: a Fatia 5 (assinatura) vai precisar trocar o caminho de
recorrência, e o Pix Automático — se e quando o MP publicar API para ele — entra
como outra implementação sem tocar no ledger nem nas telas.

## Contra qual API

Contra a **Orders API** (`POST /v1/orders`), que é o que a documentação atual do
Pix descreve. A API clássica (`/v1/payments`) continua existindo e é o que a
maioria das integrações antigas usa, mas as páginas de referência dela são
renderizadas por JS e não foi possível conferir o formato — e eu não escrevo
integração de pagamento de memória.

**O que ficou por confirmar contra o sandbox**, e está isolado de propósito em
`_STATUS_PAGOS` e `traduzir_status()`: o vocabulário completo de status. A
documentação enumera `action_required`, `processing` e o detalhe
`waiting_transfer`, mas não fecha a lista dos estados finais. Por isso o
mapeamento **falha fechado**: status desconhecido NÃO credita, fica registrado
no log e o pagamento continua pendente. Errar para o lado de não creditar é
recuperável; errar para o lado de creditar sem receber, não.

## A regra que não se negocia

O corpo da notificação do webhook **não é fonte de verdade**. Ele diz "olhe o
recurso X"; quem diz se foi pago é uma consulta autenticada ao gateway. Assim,
mesmo que a assinatura um dia seja contornada, ninguém credita saldo postando
JSON na nossa API.
"""

import hashlib
import hmac
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class MercadoPagoIndisponivel(Exception):
    """Falha ao falar com o gateway. Diferente de "o pagamento não foi aprovado"."""


class MercadoPagoNaoConfigurado(Exception):
    """Falta credencial. É erro de operação, não do usuário."""


#: Status do gateway que significam DINHEIRO RECEBIDO. Allowlist, nunca
#: denylist: um status novo que o MP inventar não pode virar crédito por
#: omissão. Confirmar contra o sandbox antes do primeiro pagamento real.
_STATUS_PAGOS = frozenset({"processed", "paid", "approved", "accredited"})

#: Status que significam que o dinheiro voltou.
_STATUS_DEVOLVIDOS = frozenset({"refunded", "cancelled", "canceled"})
_STATUS_CHARGEBACK = frozenset({"charged_back", "chargeback", "disputed"})
#: A cobrança morreu sem ser paga. Sem isto ela ficaria `pending` para sempre, e
#: a tela seguiria dizendo "aguardando pagamento" num QR que já não pode ser
#: pago. `failed` entra junto: causa diferente, resposta igual.
_STATUS_MORTOS = frozenset({"expired", "failed"})

#: Status que a Orders API pode devolver e que significam "ainda em andamento".
#: Lista confirmada na documentação em 27/08/2026 — os nove valores possíveis
#: são: created, processed, processing, action_required, canceled, charged_back,
#: expired, failed, refunded.
_STATUS_PENDENTES = frozenset({"pending", "processing", "action_required", "created"})


#: Status de assinatura do gateway -> o nosso. Allowlist, como em `_STATUS_PAGOS`
#: e pelo mesmo motivo: o que não estiver reconhecido NÃO vira assinatura ativa.
_ASSINATURA_ATIVA = frozenset({"authorized"})
_ASSINATURA_CANCELADA = frozenset({"cancelled", "canceled", "finished"})
_ASSINATURA_PAUSADA = frozenset({"paused"})


@dataclass
class Preapproval:
    """Uma assinatura criada no gateway, ainda sem cartão."""

    gateway_preapproval_id: str
    #: O link onde a pessoa autoriza. É para lá que ela é mandada — o cartão é
    #: digitado na página do Mercado Pago, nunca na nossa.
    init_point: str
    status: str
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class CobrancaPix:
    """O que a tela de recarga precisa para desenhar o Pix."""

    gateway_payment_id: str
    qr_code: str
    qr_code_base64: str
    expires_at: datetime | None
    status: str
    raw: dict[str, Any] = field(default_factory=dict)


def configurado() -> bool:
    return bool(settings.mercadopago_access_token)


def _headers(idempotency_key: str | None = None) -> dict[str, str]:
    if not configurado():
        raise MercadoPagoNaoConfigurado(
            "MERCADOPAGO_ACCESS_TOKEN está vazio. Sem ele não há como criar "
            "cobrança. Configure no .env (ver docs/DEPLOY.md)."
        )
    cabecalhos = {
        "Authorization": f"Bearer {settings.mercadopago_access_token}",
        "Content-Type": "application/json",
    }
    if idempotency_key:
        # Sem isto, um retry de rede vira duas cobranças para o mesmo usuário.
        cabecalhos["X-Idempotency-Key"] = idempotency_key
    return cabecalhos


def _percorrer(dados: Any, chave: str) -> Any:
    """Primeira ocorrência de `chave` em qualquer profundidade do JSON.

    O QR vem aninhado (`transactions.payments[].payment_method.qr_code`), e o
    caminho exato mudou entre versões da API do MP. Procurar pela chave, em vez
    de caminhar por um caminho fixo, faz a integração sobreviver a um
    reaninhamento — e o que se perde em precisão não existe na prática: não há
    duas chaves `qr_code` diferentes na mesma resposta.
    """
    if isinstance(dados, dict):
        if chave in dados and dados[chave] is not None:
            return dados[chave]
        for valor in dados.values():
            achado = _percorrer(valor, chave)
            if achado is not None:
                return achado
    elif isinstance(dados, list):
        for item in dados:
            achado = _percorrer(item, chave)
            if achado is not None:
                return achado
    return None


def traduzir_status(payload: dict[str, Any]) -> str:
    """Status do gateway -> o nosso (`pending`/`paid`/`refunded`/`chargeback`).

    Falha fechado: o que não estiver reconhecido continua `pending`, e vai para
    o log com o valor original para ser conferido.
    """
    bruto = str(
        payload.get("status") or _percorrer(payload, "status") or ""
    ).lower()

    if bruto in _STATUS_PAGOS:
        return "paid"
    if bruto in _STATUS_CHARGEBACK:
        return "chargeback"
    if bruto in _STATUS_DEVOLVIDOS:
        return "refunded"
    if bruto in _STATUS_MORTOS:
        return "expired"

    if bruto and bruto not in _STATUS_PENDENTES:
        logger.warning(
            "Status desconhecido do Mercado Pago: %r — tratado como pendente, "
            "nada foi creditado. Confira _STATUS_PAGOS em services/mercadopago.py",
            bruto,
        )
    return "pending"


async def criar_cobranca_pix(
    *,
    valor: Decimal,
    descricao: str,
    email: str,
    referencia: str,
    idempotency_key: str,
) -> CobrancaPix:
    """Cria a cobrança Pix e devolve o QR e o copia-e-cola."""
    expira_em = datetime.now(timezone.utc) + timedelta(
        minutes=settings.pix_expiration_minutes
    )
    corpo = {
        "type": "online",
        "processing_mode": "automatic",
        "total_amount": f"{valor:.2f}",
        "external_reference": referencia,
        "description": descricao,
        "payer": {"email": email},
        "transactions": {
            "payments": [
                {
                    "amount": f"{valor:.2f}",
                    "payment_method": {"id": "pix", "type": "bank_transfer"},
                    "expiration_time": f"PT{settings.pix_expiration_minutes}M",
                }
            ]
        },
    }

    url = f"{settings.mercadopago_api_base}/v1/orders"
    try:
        async with httpx.AsyncClient(timeout=settings.mercadopago_timeout) as cliente:
            resposta = await cliente.post(
                url, json=corpo, headers=_headers(idempotency_key)
            )
    except httpx.HTTPError as exc:
        raise MercadoPagoIndisponivel(f"falha de rede ao criar cobrança: {exc}") from exc

    if resposta.status_code >= 400:
        # O corpo do erro do MP diz o que faltou; sem ele o diagnóstico vira
        # adivinhação. Não vaza para o usuário — vai para o log.
        logger.error(
            "Mercado Pago recusou a cobrança (HTTP %s): %s",
            resposta.status_code,
            resposta.text[:500],
        )
        raise MercadoPagoIndisponivel(
            f"gateway respondeu {resposta.status_code} ao criar a cobrança"
        )

    dados = resposta.json()
    gateway_id = str(dados.get("id") or "")
    qr = _percorrer(dados, "qr_code")
    qr_base64 = _percorrer(dados, "qr_code_base64")

    if not gateway_id or not qr:
        logger.error("Resposta do Mercado Pago sem id ou QR: %s", str(dados)[:500])
        raise MercadoPagoIndisponivel(
            "o gateway aceitou a cobrança mas não devolveu QR — nada foi cobrado"
        )

    return CobrancaPix(
        gateway_payment_id=gateway_id,
        qr_code=str(qr),
        qr_code_base64=str(qr_base64 or ""),
        expires_at=expira_em,
        status=traduzir_status(dados),
        raw=dados,
    )


async def consultar(gateway_payment_id: str) -> dict[str, Any]:
    """O estado ATUAL da cobrança, direto do gateway.

    É esta consulta — autenticada, contra o MP — que decide se houve pagamento.
    Nunca o corpo da notificação.
    """
    url = f"{settings.mercadopago_api_base}/v1/orders/{gateway_payment_id}"
    try:
        async with httpx.AsyncClient(timeout=settings.mercadopago_timeout) as cliente:
            resposta = await cliente.get(url, headers=_headers())
    except httpx.HTTPError as exc:
        raise MercadoPagoIndisponivel(f"falha de rede ao consultar: {exc}") from exc

    if resposta.status_code >= 400:
        logger.error(
            "Mercado Pago recusou a consulta de %s (HTTP %s): %s",
            gateway_payment_id,
            resposta.status_code,
            resposta.text[:300],
        )
        raise MercadoPagoIndisponivel(
            f"gateway respondeu {resposta.status_code} ao consultar a cobrança"
        )
    return resposta.json()


# ─── Assinatura do webhook ────────────────────────────────────────────────────


def _manifest(*, data_id: str, request_id: str, ts: str) -> str:
    """O texto que o MP assina.

    Formato: `id:<data.id>;request-id:<x-request-id>;ts:<ts>;` — e a
    documentação é explícita: componente cujo valor não veio na notificação sai
    do manifest, em vez de entrar vazio.
    """
    partes = []
    if data_id:
        partes.append(f"id:{data_id};")
    if request_id:
        partes.append(f"request-id:{request_id};")
    if ts:
        partes.append(f"ts:{ts};")
    return "".join(partes)


def assinatura_valida(
    *, x_signature: str | None, x_request_id: str | None, data_id: str | None
) -> bool:
    """A notificação veio mesmo do Mercado Pago?

    HMAC-SHA256 do manifest com o segredo do painel, comparado com o `v1` do
    header `x-signature` (formato `ts=...,v1=...`).

    Sem segredo configurado a resposta é **False**, sempre. A alternativa —
    aceitar tudo quando não há segredo — transformaria uma variável de ambiente
    esquecida num endpoint público que credita saldo.

    **Não há checagem de validade do `ts`.** Seria proteção contra replay, mas:
    o MP usa o campo em segundos numa página da documentação e em
    milissegundos em outra, e uma notificação repetida aqui é inofensiva —
    creditar é idempotente por `gateway_payment_id`, e o status verdadeiro vem
    de uma consulta ao gateway, não da notificação. Rejeitar por relógio
    desalinhado custaria mais do que o replay que se evitaria.
    """
    segredo = settings.mercadopago_webhook_secret
    if not segredo:
        logger.error(
            "Webhook recusado: MERCADOPAGO_WEBHOOK_SECRET está vazio. Sem o "
            "segredo não há como distinguir o gateway de qualquer um."
        )
        return False
    if not x_signature:
        return False

    ts = ""
    recebida = ""
    for pedaco in x_signature.split(","):
        chave, _, valor = pedaco.strip().partition("=")
        if chave == "ts":
            ts = valor.strip()
        elif chave == "v1":
            recebida = valor.strip()
    if not recebida:
        return False

    # O MP normaliza id alfanumérico para minúsculas em parte da documentação e
    # não em outra. Aceitar as duas formas não afrouxa nada: as duas exigem o
    # segredo, e o que se evita é uma recusa por diferença de caixa.
    candidatos = {data_id or ""}
    if data_id:
        candidatos.add(data_id.lower())

    for candidato in candidatos:
        manifest = _manifest(
            data_id=candidato, request_id=x_request_id or "", ts=ts
        )
        esperada = hmac.new(
            segredo.encode("utf-8"), manifest.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        if hmac.compare_digest(esperada, recebida):
            return True

    logger.warning("Webhook com assinatura inválida (data.id=%r)", data_id)
    return False


# ─── Assinatura (preapproval) ─────────────────────────────────────────────────


def traduzir_status_assinatura(payload: dict[str, Any]) -> str:
    """Status da assinatura no gateway -> o nosso.

    Falha fechado igual ao do pagamento: o que não estiver reconhecido continua
    `pending`. Uma assinatura que não sabemos se está ativa não concede crédito.
    """
    bruto = str(payload.get("status") or "").lower()
    if bruto in _ASSINATURA_ATIVA:
        return "active"
    if bruto in _ASSINATURA_CANCELADA:
        return "canceled"
    if bruto in _ASSINATURA_PAUSADA:
        return "paused"
    if bruto and bruto != "pending":
        logger.warning(
            "Status de assinatura desconhecido: %r — tratado como pendente. "
            "Confira _ASSINATURA_ATIVA em services/mercadopago.py",
            bruto,
        )
    return "pending"


async def criar_preapproval(
    *,
    titulo: str,
    valor: Decimal,
    email: str,
    referencia: str,
    back_url: str,
) -> Preapproval:
    """Cria a assinatura no gateway SEM cartão, e devolve o link de autorização.

    O `card_token_id` é omitido de propósito, e é a decisão mais importante
    daqui: com ele, o cartão teria que ser digitado na NOSSA página e tokenizado
    por nós — escopo de PCI que um produto recém-lançado, com recebedor em CPF,
    não tem por que assumir. Sem ele, a assinatura nasce `pending`, o Mercado
    Pago devolve um `init_point`, e o cartão é digitado na página dele.

    O preço vai em `auto_recurring.transaction_amount`, resolvido pelo servidor
    a partir do plano — nunca vindo do cliente.
    """
    corpo = {
        "reason": titulo,
        "external_reference": referencia,
        "payer_email": email,
        "back_url": back_url,
        "status": "pending",
        "auto_recurring": {
            "frequency": 1,
            "frequency_type": "months",
            "transaction_amount": float(valor),
            "currency_id": "BRL",
        },
    }

    url = f"{settings.mercadopago_api_base}/preapproval"
    try:
        async with httpx.AsyncClient(timeout=settings.mercadopago_timeout) as cliente:
            resposta = await cliente.post(
                url, json=corpo, headers=_headers(referencia)
            )
    except httpx.HTTPError as exc:
        raise MercadoPagoIndisponivel(f"falha de rede ao criar assinatura: {exc}") from exc

    if resposta.status_code >= 400:
        logger.error(
            "Mercado Pago recusou a assinatura (HTTP %s): %s",
            resposta.status_code,
            resposta.text[:500],
        )
        raise MercadoPagoIndisponivel(
            f"gateway respondeu {resposta.status_code} ao criar a assinatura"
        )

    dados = resposta.json()
    gateway_id = str(dados.get("id") or "")
    link = dados.get("init_point") or dados.get("sandbox_init_point") or ""

    if not gateway_id or not link:
        logger.error("Resposta de preapproval sem id ou init_point: %s", str(dados)[:500])
        raise MercadoPagoIndisponivel(
            "o gateway aceitou a assinatura mas não devolveu link de autorização"
        )

    return Preapproval(
        gateway_preapproval_id=gateway_id,
        init_point=str(link),
        status=traduzir_status_assinatura(dados),
        raw=dados,
    )


async def consultar_preapproval(gateway_preapproval_id: str) -> dict[str, Any]:
    """O estado atual da assinatura, direto do gateway."""
    return await _get(f"/preapproval/{gateway_preapproval_id}")


async def consultar_authorized_payment(authorized_payment_id: str) -> dict[str, Any]:
    """A cobrança de UM ciclo da assinatura.

    É o recurso que a notificação `subscription_authorized_payment` aponta, e é
    ele que diz se o mês foi efetivamente pago.
    """
    return await _get(f"/authorized_payments/{authorized_payment_id}")


async def cancelar_preapproval(gateway_preapproval_id: str) -> dict[str, Any]:
    """Cancela a assinatura no gateway. Idempotente do lado deles."""
    url = f"{settings.mercadopago_api_base}/preapproval/{gateway_preapproval_id}"
    try:
        async with httpx.AsyncClient(timeout=settings.mercadopago_timeout) as cliente:
            resposta = await cliente.put(
                url, json={"status": "cancelled"}, headers=_headers()
            )
    except httpx.HTTPError as exc:
        raise MercadoPagoIndisponivel(f"falha de rede ao cancelar: {exc}") from exc

    if resposta.status_code >= 400:
        logger.error(
            "Mercado Pago recusou o cancelamento de %s (HTTP %s): %s",
            gateway_preapproval_id,
            resposta.status_code,
            resposta.text[:300],
        )
        raise MercadoPagoIndisponivel(
            f"gateway respondeu {resposta.status_code} ao cancelar a assinatura"
        )
    return resposta.json()


async def _get(caminho: str) -> dict[str, Any]:
    """GET autenticado no gateway, com o mesmo tratamento de erro dos demais."""
    url = f"{settings.mercadopago_api_base}{caminho}"
    try:
        async with httpx.AsyncClient(timeout=settings.mercadopago_timeout) as cliente:
            resposta = await cliente.get(url, headers=_headers())
    except httpx.HTTPError as exc:
        raise MercadoPagoIndisponivel(f"falha de rede em {caminho}: {exc}") from exc

    if resposta.status_code >= 400:
        logger.error(
            "Mercado Pago recusou %s (HTTP %s): %s",
            caminho,
            resposta.status_code,
            resposta.text[:300],
        )
        raise MercadoPagoIndisponivel(f"gateway respondeu {resposta.status_code} em {caminho}")
    return resposta.json()
