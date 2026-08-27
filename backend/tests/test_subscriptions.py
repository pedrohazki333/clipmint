"""
Assinatura mensal: autorização fora daqui, créditos por ciclo, cancelamento.

Três coisas sendo guardadas:

  1. **nunca tocamos em cartão** — a assinatura é criada sem `card_token_id` e a
     pessoa autoriza na página do Mercado Pago;
  2. **o ciclo credita uma vez**, pelo MESMO caminho da recarga avulsa (a
     idempotência da Fatia 2 vale igual, e não há um segundo mecanismo);
  3. **cancelar falha fechado** — se o gateway recusa, a assinatura NÃO é
     marcada como cancelada aqui. O contrário deixaria a pessoa achando que
     parou de pagar enquanto o cartão continua sendo debitado.

O gateway é falsificado. O que depende de credencial real está anotado como
pendência no resumo, não escondido atrás do mock.
"""

import asyncio
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base, get_db
from app.main import register_routers
from app.models import BillingConfig, CreditLedger, Payment, Subscription, User
from app.services import mercadopago

SEGREDO = "segredo-de-teste"
PREAPPROVAL = "MP-PREAPPROVAL-1"

CONFIG = {
    "id": 1,
    "credito_avulso_brl": Decimal("0.10"),
    "pacotes": [{"creditos": 300, "preco_brl": None}],
    "planos": [
        {"code": "essencial", "nome": "Essencial", "valor_brl": "49.90", "creditos_mes": 500},
        {"code": "pro", "nome": "Pro", "valor_brl": "99.90", "creditos_mes": 1200},
    ],
    "creditos_gratis_cadastro": 0,
    "saldo_baixo_threshold": 120,
}


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "public_build", True)
    monkeypatch.setattr(settings, "clipmint_password", "")
    monkeypatch.setattr(settings, "mercadopago_webhook_secret", SEGREDO)
    monkeypatch.setattr(settings, "mercadopago_access_token", "TEST-token")
    monkeypatch.setattr(settings, "public_base_url", "https://clipmint.exemplo")
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path / "storage"))
    settings.ensure_dirs()

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'a.db'}")
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async def montar():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with factory() as s:
            s.add(BillingConfig(**CONFIG))
            await s.commit()

    asyncio.run(montar())

    async def override_db():
        async with factory() as session:
            yield session

    app = FastAPI()
    register_routers(app)
    app.dependency_overrides[get_db] = override_db
    c = TestClient(app)
    assert (
        c.post(
            "/api/auth/register",
            json={"email": "assinante@exemplo.com", "password": "uma-senha-bem-longa"},
        ).status_code
        == 201
    )
    return c, factory


def _gateway(monkeypatch, *, status_assinatura="pending", cancelar_falha=False):
    chamadas = {"criar": [], "cancelar": []}

    async def criar_preapproval(**kwargs):
        chamadas["criar"].append(kwargs)
        return mercadopago.Preapproval(
            gateway_preapproval_id=PREAPPROVAL,
            init_point="https://mercadopago.exemplo/autorizar/abc",
            status="pending",
            raw={"id": PREAPPROVAL, "status": "pending"},
        )

    async def consultar_preapproval(pid):
        return {"id": pid, "status": status_assinatura}

    async def cancelar_preapproval(pid):
        chamadas["cancelar"].append(pid)
        if cancelar_falha:
            raise mercadopago.MercadoPagoIndisponivel("gateway fora do ar")
        return {"id": pid, "status": "cancelled"}

    monkeypatch.setattr(mercadopago, "criar_preapproval", criar_preapproval)
    monkeypatch.setattr(mercadopago, "consultar_preapproval", consultar_preapproval)
    monkeypatch.setattr(mercadopago, "cancelar_preapproval", cancelar_preapproval)
    return chamadas


def _ciclo(monkeypatch, *, status="processed", preapproval=PREAPPROVAL):
    async def consultar_authorized_payment(pid):
        return {"id": pid, "status": status, "preapproval_id": preapproval}

    monkeypatch.setattr(
        mercadopago, "consultar_authorized_payment", consultar_authorized_payment
    )


def _headers(data_id: str, tipo: str):
    import hashlib
    import hmac

    ts, rid = "1742505638683", "req-1"
    manifest = f"id:{data_id};request-id:{rid};ts:{ts};"
    v1 = hmac.new(SEGREDO.encode(), manifest.encode(), hashlib.sha256).hexdigest()
    return {"x-signature": f"ts={ts},v1={v1}", "x-request-id": rid}


async def _saldo(factory) -> int:
    async with factory() as db:
        return int(await db.scalar(select(User.credit_balance)) or 0)


# ─── Criar ────────────────────────────────────────────────────────────────────


def test_assinar_devolve_o_link_e_nao_pede_cartao(ambiente, monkeypatch):
    """O cartão é digitado na página do gateway — nunca chega até nós."""
    cliente, _ = ambiente
    chamadas = _gateway(monkeypatch)

    resp = cliente.post("/api/billing/subscribe", json={"plan_code": "pro"})
    assert resp.status_code == 201, resp.text
    corpo = resp.json()

    assert corpo["status"] == "pending"
    assert corpo["init_point"].startswith("https://")
    assert corpo["creditos_mes"] == 1200
    assert Decimal(str(corpo["valor_brl"])) == Decimal("99.90")

    # Nenhum dado de cartão foi enviado ao gateway.
    enviado = chamadas["criar"][0]
    assert "card_token_id" not in enviado
    assert enviado["valor"] == Decimal("99.90")


def test_assinar_congela_preco_e_creditos(ambiente, monkeypatch):
    """Subir o preço do Pro amanhã não pode reescrever o que já foi vendido."""
    cliente, factory = ambiente
    _gateway(monkeypatch)
    cliente.post("/api/billing/subscribe", json={"plan_code": "pro"})

    async def encarecer():
        async with factory() as db:
            config = await db.scalar(select(BillingConfig))
            config.planos = [
                {"code": "pro", "nome": "Pro", "valor_brl": "149.90", "creditos_mes": 900}
            ]
            await db.commit()

    asyncio.run(encarecer())

    corpo = cliente.get("/api/billing/subscription").json()
    assert Decimal(str(corpo["valor_brl"])) == Decimal("99.90")
    assert corpo["creditos_mes"] == 1200


def test_plano_inexistente_e_recusado(ambiente, monkeypatch):
    cliente, _ = ambiente
    _gateway(monkeypatch)
    resp = cliente.post("/api/billing/subscribe", json={"plan_code": "ouro"})
    assert resp.status_code == 422
    assert "não existe" in resp.json()["detail"]


def test_duas_assinaturas_ao_mesmo_tempo_sao_recusadas(ambiente, monkeypatch):
    cliente, _ = ambiente
    _gateway(monkeypatch)
    assert cliente.post("/api/billing/subscribe", json={"plan_code": "pro"}).status_code == 201
    segunda = cliente.post("/api/billing/subscribe", json={"plan_code": "essencial"})
    assert segunda.status_code == 409


def test_sem_endereco_publico_assinar_e_recusado(ambiente, monkeypatch):
    """Mandar alguém ao gateway sem caminho de volta o deixa preso lá."""
    cliente, _ = ambiente
    _gateway(monkeypatch)
    monkeypatch.setattr(settings, "public_base_url", "")

    resp = cliente.post("/api/billing/subscribe", json={"plan_code": "pro"})
    assert resp.status_code == 503


# ─── Acompanhar ───────────────────────────────────────────────────────────────


def test_sem_assinatura_devolve_nulo(ambiente):
    cliente, _ = ambiente
    assert cliente.get("/api/billing/subscription").json() is None


def test_consulta_descobre_a_autorizacao_sem_webhook(ambiente, monkeypatch):
    """Mesma razão do polling do Pix: a tela não pode depender da notificação."""
    cliente, _ = ambiente
    _gateway(monkeypatch, status_assinatura="authorized")
    cliente.post("/api/billing/subscribe", json={"plan_code": "pro"})

    corpo = cliente.get("/api/billing/subscription").json()
    assert corpo["status"] == "active"
    assert corpo["started_at"] is not None


# ─── Ciclo ────────────────────────────────────────────────────────────────────


def test_ciclo_aprovado_concede_os_creditos_do_mes(ambiente, monkeypatch):
    cliente, factory = ambiente
    _gateway(monkeypatch)
    _ciclo(monkeypatch)
    cliente.post("/api/billing/subscribe", json={"plan_code": "pro"})

    resp = cliente.post(
        "/api/billing/webhook?data.id=CICLO-1&type=subscription_authorized_payment",
        headers=_headers("CICLO-1", "subscription_authorized_payment"),
        json={},
    )
    assert resp.status_code == 200
    assert asyncio.run(_saldo(factory)) == 1200


def test_ciclo_repetido_nao_credita_duas_vezes(ambiente, monkeypatch):
    cliente, factory = ambiente
    _gateway(monkeypatch)
    _ciclo(monkeypatch)
    cliente.post("/api/billing/subscribe", json={"plan_code": "pro"})

    for _ in range(3):
        cliente.post(
            "/api/billing/webhook?data.id=CICLO-1&type=subscription_authorized_payment",
            headers=_headers("CICLO-1", "subscription_authorized_payment"),
            json={},
        )

    assert asyncio.run(_saldo(factory)) == 1200

    async def lancamentos():
        async with factory() as db:
            return len(
                (await db.execute(select(CreditLedger).where(CreditLedger.tipo == "topup")))
                .scalars()
                .all()
            )

    assert asyncio.run(lancamentos()) == 1


def test_dois_meses_creditam_duas_vezes(ambiente, monkeypatch):
    """Idempotência é por cobrança, não por assinatura."""
    cliente, factory = ambiente
    _gateway(monkeypatch)
    _ciclo(monkeypatch)
    cliente.post("/api/billing/subscribe", json={"plan_code": "pro"})

    for ciclo in ("CICLO-1", "CICLO-2"):
        cliente.post(
            f"/api/billing/webhook?data.id={ciclo}&type=subscription_authorized_payment",
            headers=_headers(ciclo, "subscription_authorized_payment"),
            json={},
        )

    assert asyncio.run(_saldo(factory)) == 2400


def test_ciclo_nao_pago_nao_credita(ambiente, monkeypatch):
    cliente, factory = ambiente
    _gateway(monkeypatch)
    _ciclo(monkeypatch, status="pending")
    cliente.post("/api/billing/subscribe", json={"plan_code": "pro"})

    cliente.post(
        "/api/billing/webhook?data.id=CICLO-1&type=subscription_authorized_payment",
        headers=_headers("CICLO-1", "subscription_authorized_payment"),
        json={},
    )
    assert asyncio.run(_saldo(factory)) == 0


def test_ciclo_de_assinatura_desconhecida_nao_credita(ambiente, monkeypatch):
    cliente, factory = ambiente
    _gateway(monkeypatch)
    _ciclo(monkeypatch, preapproval="OUTRO-PREAPPROVAL")
    cliente.post("/api/billing/subscribe", json={"plan_code": "pro"})

    resp = cliente.post(
        "/api/billing/webhook?data.id=CICLO-1&type=subscription_authorized_payment",
        headers=_headers("CICLO-1", "subscription_authorized_payment"),
        json={},
    )
    assert resp.status_code == 200
    assert asyncio.run(_saldo(factory)) == 0


def test_ciclo_pago_prova_que_a_assinatura_esta_ativa(ambiente, monkeypatch):
    """A notificação do ciclo pode chegar antes da autorização."""
    cliente, factory = ambiente
    _gateway(monkeypatch)
    _ciclo(monkeypatch)
    cliente.post("/api/billing/subscribe", json={"plan_code": "pro"})

    cliente.post(
        "/api/billing/webhook?data.id=CICLO-1&type=subscription_authorized_payment",
        headers=_headers("CICLO-1", "subscription_authorized_payment"),
        json={},
    )

    async def ler():
        async with factory() as db:
            return await db.scalar(select(Subscription))

    assinatura = asyncio.run(ler())
    assert assinatura.status == "active"
    assert assinatura.current_period_end is not None


def test_webhook_de_preapproval_sincroniza_o_status(ambiente, monkeypatch):
    cliente, factory = ambiente
    _gateway(monkeypatch, status_assinatura="cancelled")
    cliente.post("/api/billing/subscribe", json={"plan_code": "pro"})

    cliente.post(
        f"/api/billing/webhook?data.id={PREAPPROVAL}&type=subscription_preapproval",
        headers=_headers(PREAPPROVAL, "subscription_preapproval"),
        json={},
    )

    async def ler():
        async with factory() as db:
            return await db.scalar(select(Subscription))

    assert asyncio.run(ler()).status == "canceled"


# ─── Cancelar ─────────────────────────────────────────────────────────────────


def test_cancelar_avisa_o_gateway_e_marca_aqui(ambiente, monkeypatch):
    cliente, _ = ambiente
    chamadas = _gateway(monkeypatch)
    cliente.post("/api/billing/subscribe", json={"plan_code": "pro"})

    resp = cliente.post("/api/billing/subscription/cancel")
    assert resp.status_code == 200
    assert resp.json()["status"] == "canceled"
    assert chamadas["cancelar"] == [PREAPPROVAL]


def test_cancelamento_que_falha_no_gateway_nao_marca_aqui(ambiente, monkeypatch):
    """O contrário deixaria a pessoa achando que parou de pagar."""
    cliente, factory = ambiente
    _gateway(monkeypatch, cancelar_falha=True)
    cliente.post("/api/billing/subscribe", json={"plan_code": "pro"})

    resp = cliente.post("/api/billing/subscription/cancel")
    assert resp.status_code == 502
    assert "NÃO foi cancelada" in resp.json()["detail"]

    async def ler():
        async with factory() as db:
            return await db.scalar(select(Subscription))

    assert asyncio.run(ler()).status == "pending"


def test_cancelar_sem_assinatura_da_404(ambiente):
    cliente, _ = ambiente
    assert cliente.post("/api/billing/subscription/cancel").status_code == 404


def test_creditos_ja_concedidos_ficam_apos_cancelar(ambiente, monkeypatch):
    """O mês foi pago: o crédito é dela."""
    cliente, factory = ambiente
    _gateway(monkeypatch)
    _ciclo(monkeypatch)
    cliente.post("/api/billing/subscribe", json={"plan_code": "pro"})
    cliente.post(
        "/api/billing/webhook?data.id=CICLO-1&type=subscription_authorized_payment",
        headers=_headers("CICLO-1", "subscription_authorized_payment"),
        json={},
    )
    cliente.post("/api/billing/subscription/cancel")

    assert asyncio.run(_saldo(factory)) == 1200


def test_ciclo_vira_linha_de_pagamento_ligada_a_assinatura(ambiente, monkeypatch):
    """Conciliação financeira precisa saber qual assinatura gerou a cobrança."""
    cliente, factory = ambiente
    _gateway(monkeypatch)
    _ciclo(monkeypatch)
    cliente.post("/api/billing/subscribe", json={"plan_code": "pro"})
    cliente.post(
        "/api/billing/webhook?data.id=CICLO-1&type=subscription_authorized_payment",
        headers=_headers("CICLO-1", "subscription_authorized_payment"),
        json={},
    )

    async def ler():
        async with factory() as db:
            pag = (await db.execute(select(Payment))).scalars().one()
            sub = await db.scalar(select(Subscription))
            return pag, sub

    pagamento, assinatura = asyncio.run(ler())
    assert pagamento.tipo == "assinatura"
    assert pagamento.subscription_id == assinatura.id
    assert pagamento.status == "paid"
    assert pagamento.credits_granted == 1200
