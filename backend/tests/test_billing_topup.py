"""
Recarga por Pix: assinatura do webhook, crédito idempotente, preço do servidor.

O que está sendo guardado aqui é dinheiro, e em três frentes:

  1. **ninguém credita saldo sem ser o Mercado Pago** — a assinatura HMAC é a
     única coisa entre o endpoint aberto e alguém postando "aprovado";
  2. **um pagamento credita uma vez só**, por mais vezes que a notificação
     chegue (e ela chega repetida: o MP reenvia);
  3. **o preço sai do servidor**, nunca do corpo da requisição.

O gateway é falsificado: estes testes não saem para a rede. O que depende de
credencial real (o formato exato da resposta do MP, o vocabulário de status)
está anotado como pendência no resumo da fatia, não escondido atrás de um mock
que finge tê-lo verificado.
"""

import asyncio
import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base, get_db
from app.main import register_routers
from app.models import BillingConfig, CreditLedger, Payment, User
from app.services import mercadopago

SEGREDO = "segredo-de-teste-do-webhook"

CONFIG_TESTE = {
    "id": 1,
    "credito_avulso_brl": Decimal("0.10"),
    "pacotes": [{"creditos": 300, "preco_brl": None}, {"creditos": 1500, "preco_brl": "120.00"}],
    "planos": [],
    "creditos_gratis_cadastro": 0,  # zero para o saldo do teste vir só da recarga
    "saldo_baixo_threshold": 120,
}


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "public_build", True)
    monkeypatch.setattr(settings, "clipmint_password", "")
    monkeypatch.setattr(settings, "mercadopago_webhook_secret", SEGREDO)
    monkeypatch.setattr(settings, "mercadopago_access_token", "TEST-token-falso")
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path / "storage"))
    settings.ensure_dirs()

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'b.db'}")
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async def montar():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with factory() as s:
            s.add(BillingConfig(**CONFIG_TESTE))
            await s.commit()

    asyncio.run(montar())

    async def override_db():
        async with factory() as session:
            yield session

    app = FastAPI()
    register_routers(app)
    app.dependency_overrides[get_db] = override_db
    cliente = TestClient(app)

    resp = cliente.post(
        "/api/auth/register",
        json={"email": "pagador@exemplo.com", "password": "uma-senha-bem-longa"},
    )
    assert resp.status_code == 201, resp.text
    return cliente, factory


def _gateway_falso(monkeypatch, *, status_consulta="processed"):
    """Substitui as duas chamadas de rede do gateway."""

    async def criar(**kwargs):
        return mercadopago.CobrancaPix(
            gateway_payment_id="MP-ORDER-1",
            qr_code="00020126...copia-e-cola",
            qr_code_base64="aGVsbG8=",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
            status="pending",
            raw={"id": "MP-ORDER-1", "status": "action_required"},
        )

    async def consultar(gateway_payment_id: str):
        return {"id": gateway_payment_id, "status": status_consulta}

    monkeypatch.setattr(mercadopago, "criar_cobranca_pix", criar)
    monkeypatch.setattr(mercadopago, "consultar", consultar)


def _assinar(data_id: str, request_id: str, ts: str, segredo: str = SEGREDO) -> str:
    manifest = f"id:{data_id};request-id:{request_id};ts:{ts};"
    return hmac.new(segredo.encode(), manifest.encode(), hashlib.sha256).hexdigest()


def _headers_webhook(data_id="MP-ORDER-1", request_id="req-1", ts="1742505638683", **kw):
    return {
        "x-signature": f"ts={ts},v1={_assinar(data_id, request_id, ts, **kw)}",
        "x-request-id": request_id,
    }


async def _saldo(factory, email="pagador@exemplo.com") -> int:
    async with factory() as db:
        return int(
            await db.scalar(select(User.credit_balance).where(User.email == email)) or 0
        )


# ─── A assinatura do webhook ──────────────────────────────────────────────────


def test_assinatura_valida_e_aceita(monkeypatch):
    monkeypatch.setattr(settings, "mercadopago_webhook_secret", SEGREDO)
    assert mercadopago.assinatura_valida(
        x_signature=f"ts=123,v1={_assinar('abc', 'req', '123')}",
        x_request_id="req",
        data_id="abc",
    )


def test_assinatura_de_outro_segredo_e_recusada(monkeypatch):
    monkeypatch.setattr(settings, "mercadopago_webhook_secret", SEGREDO)
    assert not mercadopago.assinatura_valida(
        x_signature=f"ts=123,v1={_assinar('abc', 'req', '123', segredo='outro')}",
        x_request_id="req",
        data_id="abc",
    )


def test_sem_segredo_configurado_recusa_tudo(monkeypatch):
    """Variável de ambiente esquecida não pode virar endpoint que credita saldo."""
    monkeypatch.setattr(settings, "mercadopago_webhook_secret", "")
    assert not mercadopago.assinatura_valida(
        x_signature=f"ts=123,v1={_assinar('abc', 'req', '123', segredo='')}",
        x_request_id="req",
        data_id="abc",
    )


def test_componente_ausente_sai_do_manifest(monkeypatch):
    """A documentação é explícita: valor que não veio sai, em vez de entrar vazio."""
    monkeypatch.setattr(settings, "mercadopago_webhook_secret", SEGREDO)
    manifest = "id:abc;ts:123;"
    assinatura = hmac.new(SEGREDO.encode(), manifest.encode(), hashlib.sha256).hexdigest()
    assert mercadopago.assinatura_valida(
        x_signature=f"ts=123,v1={assinatura}", x_request_id=None, data_id="abc"
    )


def test_id_em_maiusculas_tambem_valida(monkeypatch):
    """O MP normaliza id alfanumérico em parte da documentação e não em outra."""
    monkeypatch.setattr(settings, "mercadopago_webhook_secret", SEGREDO)
    assert mercadopago.assinatura_valida(
        x_signature=f"ts=1,v1={_assinar('mp-order-1', 'req', '1')}",
        x_request_id="req",
        data_id="MP-ORDER-1",
    )


# ─── Criar a cobrança ─────────────────────────────────────────────────────────


def test_topup_usa_o_preco_do_servidor(ambiente, monkeypatch):
    cliente, factory = ambiente
    _gateway_falso(monkeypatch)

    resp = cliente.post("/api/billing/topup", json={"creditos": 300})
    assert resp.status_code == 201, resp.text
    corpo = resp.json()

    # 300 x R$ 0,10 = R$ 30,00, calculado no servidor.
    assert Decimal(str(corpo["valor_brl"])) == Decimal("30.00")
    assert corpo["creditos"] == 300
    assert corpo["status"] == "pending"
    assert corpo["qr_code"].startswith("00020126")
    # Cobrança criada não credita nada.
    assert asyncio.run(_saldo(factory)) == 0


def test_pacote_com_desconto_respeita_a_configuracao(ambiente, monkeypatch):
    cliente, _ = ambiente
    _gateway_falso(monkeypatch)

    resp = cliente.post("/api/billing/topup", json={"creditos": 1500})
    # 1500 x 0,10 seriam R$ 150,00; a configuração diz 120,00.
    assert Decimal(str(resp.json()["valor_brl"])) == Decimal("120.00")


def test_pacote_inexistente_e_recusado(ambiente, monkeypatch):
    cliente, _ = ambiente
    _gateway_falso(monkeypatch)

    resp = cliente.post("/api/billing/topup", json={"creditos": 7})
    assert resp.status_code == 422
    assert "não existe" in resp.json()["detail"]


# ─── O webhook credita — uma vez ──────────────────────────────────────────────


def test_webhook_aprovado_credita_o_saldo(ambiente, monkeypatch):
    cliente, factory = ambiente
    _gateway_falso(monkeypatch, status_consulta="processed")
    cliente.post("/api/billing/topup", json={"creditos": 300})

    resp = cliente.post(
        "/api/billing/webhook?data.id=MP-ORDER-1", headers=_headers_webhook(), json={}
    )
    assert resp.status_code == 200
    assert asyncio.run(_saldo(factory)) == 300


def test_webhook_repetido_nao_credita_duas_vezes(ambiente, monkeypatch):
    """O Mercado Pago reenvia notificação. Reenviar não pode dobrar o saldo."""
    cliente, factory = ambiente
    _gateway_falso(monkeypatch, status_consulta="processed")
    cliente.post("/api/billing/topup", json={"creditos": 300})

    for _ in range(3):
        resp = cliente.post(
            "/api/billing/webhook?data.id=MP-ORDER-1", headers=_headers_webhook(), json={}
        )
        assert resp.status_code == 200

    assert asyncio.run(_saldo(factory)) == 300

    async def lancamentos():
        async with factory() as db:
            linhas = (
                await db.execute(select(CreditLedger).where(CreditLedger.tipo == "topup"))
            ).scalars().all()
            return len(linhas)

    assert asyncio.run(lancamentos()) == 1


def test_webhook_sem_assinatura_valida_nao_credita(ambiente, monkeypatch):
    cliente, factory = ambiente
    _gateway_falso(monkeypatch, status_consulta="processed")
    cliente.post("/api/billing/topup", json={"creditos": 300})

    resp = cliente.post(
        "/api/billing/webhook?data.id=MP-ORDER-1",
        headers={"x-signature": "ts=1,v1=deadbeef", "x-request-id": "req-1"},
        json={},
    )
    assert resp.status_code == 401
    assert asyncio.run(_saldo(factory)) == 0


def test_status_desconhecido_nao_credita(ambiente, monkeypatch):
    """Falha fechado: o que não está na allowlist continua pendente."""
    cliente, factory = ambiente
    _gateway_falso(monkeypatch, status_consulta="alguma_coisa_nova")
    cliente.post("/api/billing/topup", json={"creditos": 300})

    resp = cliente.post(
        "/api/billing/webhook?data.id=MP-ORDER-1", headers=_headers_webhook(), json={}
    )
    assert resp.status_code == 200
    assert asyncio.run(_saldo(factory)) == 0


def test_webhook_de_pagamento_desconhecido_responde_ok(ambiente, monkeypatch):
    """Notificação de algo que este build ainda não trata não pode virar retry eterno."""
    cliente, _ = ambiente
    _gateway_falso(monkeypatch)

    resp = cliente.post(
        "/api/billing/webhook?data.id=NAO-EXISTE",
        headers=_headers_webhook(data_id="NAO-EXISTE"),
        json={},
    )
    assert resp.status_code == 200


# ─── O polling da tela ────────────────────────────────────────────────────────


def test_consulta_confirma_o_pagamento_sem_webhook(ambiente, monkeypatch):
    """Em desenvolvimento o webhook nunca chega: o MP não alcança um localhost."""
    cliente, factory = ambiente
    _gateway_falso(monkeypatch, status_consulta="processed")
    payment_id = cliente.post("/api/billing/topup", json={"creditos": 300}).json()[
        "payment_id"
    ]

    resp = cliente.get(f"/api/billing/payments/{payment_id}")
    assert resp.status_code == 200
    corpo = resp.json()
    assert corpo["status"] == "paid"
    assert corpo["saldo"] == 300
    assert asyncio.run(_saldo(factory)) == 300


def test_consulta_repetida_nao_credita_de_novo(ambiente, monkeypatch):
    cliente, factory = ambiente
    _gateway_falso(monkeypatch, status_consulta="processed")
    payment_id = cliente.post("/api/billing/topup", json={"creditos": 300}).json()[
        "payment_id"
    ]

    for _ in range(3):
        cliente.get(f"/api/billing/payments/{payment_id}")

    assert asyncio.run(_saldo(factory)) == 300


def test_pagamento_de_outro_usuario_da_404(ambiente, monkeypatch):
    """Quem não é dono não precisa nem saber que o pagamento existe."""
    cliente, factory = ambiente
    _gateway_falso(monkeypatch)
    payment_id = cliente.post("/api/billing/topup", json={"creditos": 300}).json()[
        "payment_id"
    ]

    cliente.post("/api/auth/logout")
    outro = cliente.post(
        "/api/auth/register",
        json={"email": "bisbilhoteiro@exemplo.com", "password": "outra-senha-longa"},
    )
    assert outro.status_code == 201

    resp = cliente.get(f"/api/billing/payments/{payment_id}")
    assert resp.status_code == 404


# ─── A cobrança fica registrada ───────────────────────────────────────────────


def test_pagamento_guarda_o_id_do_gateway_e_o_payload(ambiente, monkeypatch):
    cliente, factory = ambiente
    _gateway_falso(monkeypatch)
    cliente.post("/api/billing/topup", json={"creditos": 300})

    async def ler():
        async with factory() as db:
            return (await db.execute(select(Payment))).scalars().one()

    pag = asyncio.run(ler())
    assert pag.gateway_payment_id == "MP-ORDER-1"
    assert pag.tipo == "topup"
    assert pag.credits_granted == 300
    # O payload do gateway é o que resolve conciliação divergente meses depois.
    assert pag.raw_gateway_payload["id"] == "MP-ORDER-1"


# ─── O vocabulário de status do gateway ───────────────────────────────────────


@pytest.mark.parametrize(
    "do_gateway,nosso",
    [
        # Os nove valores que a Orders API pode devolver, conferidos na
        # documentação em 27/08/2026. Nenhum pode cair em "desconhecido".
        ("created", "pending"),
        ("processing", "pending"),
        ("action_required", "pending"),
        ("processed", "paid"),
        ("canceled", "refunded"),
        ("refunded", "refunded"),
        ("charged_back", "chargeback"),
        ("expired", "expired"),
        ("failed", "expired"),
    ],
)
def test_todos_os_status_da_orders_api_sao_reconhecidos(do_gateway, nosso):
    assert mercadopago.traduzir_status({"status": do_gateway}) == nosso


def test_status_fora_da_lista_continua_falhando_fechado(caplog):
    """Um valor novo que o MP invente não pode virar crédito por omissão."""
    assert mercadopago.traduzir_status({"status": "invencao_futura"}) == "pending"


def test_cobranca_expirada_para_de_ser_consultada(ambiente, monkeypatch):
    """Sem isso a tela fica em 'aguardando pagamento' num QR que já morreu."""
    cliente, factory = ambiente
    _gateway_falso(monkeypatch, status_consulta="expired")
    payment_id = cliente.post("/api/billing/topup", json={"creditos": 300}).json()[
        "payment_id"
    ]

    corpo = cliente.get(f"/api/billing/payments/{payment_id}").json()
    assert corpo["status"] == "expired"
    assert corpo["saldo"] == 0
