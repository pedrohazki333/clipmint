"""
Lançamento manual: o que entra fora do gateway, e o que sai por estorno.

O fio: **não existe uma segunda contabilidade.** O que o dono lança à mão vai
para as MESMAS tabelas do webhook, e o painel soma tudo junto. O que distingue é
a coluna `gateway`.

Três coisas guardadas:

  1. **registrar receita não é entregar crédito.** Confundir as duas daria
     crédito de graça toda vez que o dono só quisesse acertar o extrato;
  2. **o mesmo Pix não entra duas vezes** quando a referência é informada — o
     erro provável aqui é conferir o extrato e lançar de novo na semana seguinte;
  3. **estorno tira do mês sem mexer no saldo** de quem já processou vídeo.
"""

import asyncio
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base, get_db
from app.main import register_routers
from app.models import BillingConfig, CreditLedger, Payment, Subscription, User

MES = "2026-08"

CONFIG = {
    "id": 1,
    "credito_avulso_brl": Decimal("0.12"),
    "pacotes": [{"creditos": 300, "preco_brl": None}],
    "planos": [],
    "creditos_gratis_cadastro": 0,
    "saldo_baixo_threshold": 120,
}


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "public_build", True)
    monkeypatch.setattr(settings, "clipmint_password", "")
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path / "storage"))
    settings.ensure_dirs()

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'x.db'}")
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
    cliente = TestClient(app)

    # O dono, e um cliente que vai receber os lançamentos.
    for email in ("dono@exemplo.com", "cliente@exemplo.com"):
        assert (
            cliente.post(
                "/api/auth/register",
                json={"email": email, "password": "uma-senha-bem-longa"},
            ).status_code
            == 201
        )

    async def promover():
        async with factory() as db:
            await db.execute(
                update(User).where(User.email == "dono@exemplo.com").values(is_owner=True)
            )
            await db.commit()

    asyncio.run(promover())
    cliente.post("/api/auth/logout")
    assert (
        cliente.post(
            "/api/auth/login",
            json={"email": "dono@exemplo.com", "password": "uma-senha-bem-longa"},
        ).status_code
        == 200
    )
    return cliente, factory


def _lancar(cliente, **campos):
    corpo = {
        "email": "cliente@exemplo.com",
        "valor_brl": "180.00",
        "pago_em": "2026-08-10T15:00:00+00:00",
        **campos,
    }
    return cliente.post("/api/admin/payments", json=corpo)


async def _saldo(factory, email="cliente@exemplo.com") -> int:
    async with factory() as db:
        return int(
            await db.scalar(select(User.credit_balance).where(User.email == email)) or 0
        )


# ─── Receita ──────────────────────────────────────────────────────────────────


def test_lancamento_manual_vira_receita_do_mes(ambiente):
    cliente, _ = ambiente
    resp = _lancar(cliente, referencia="E2E-123")
    assert resp.status_code == 201, resp.text
    assert resp.json()["gateway"] == "manual"
    assert resp.json()["status"] == "paid"

    v = cliente.get(f"/api/admin/overview?mes={MES}").json()["atual"]
    assert Decimal(str(v["receita_bruta_brl"])) == Decimal("180.00")
    assert v["pagamentos"] == 1


def test_a_data_informada_decide_o_mes(ambiente):
    """Lançar em setembro um Pix recebido em agosto tem que cair em agosto."""
    cliente, _ = ambiente
    _lancar(cliente, referencia="E2E-jul", pago_em="2026-07-20T15:00:00+00:00")

    corpo = cliente.get(f"/api/admin/overview?mes={MES}").json()
    assert Decimal(str(corpo["atual"]["receita_bruta_brl"])) == Decimal("0.00")
    assert Decimal(str(corpo["anterior"]["receita_bruta_brl"])) == Decimal("180.00")


def test_email_desconhecido_e_recusado(ambiente):
    cliente, _ = ambiente
    resp = _lancar(cliente, email="ninguem@exemplo.com")
    assert resp.status_code == 404


def test_valor_negativo_e_recusado_com_o_caminho_certo(ambiente):
    """Reverter receita é mudança de status, não valor negativo."""
    cliente, _ = ambiente
    resp = _lancar(cliente, valor_brl="-10.00")
    assert resp.status_code == 422


# ─── Idempotência ─────────────────────────────────────────────────────────────


def test_mesma_referencia_nao_entra_duas_vezes(ambiente):
    """O erro provável: conferir o extrato e lançar de novo na semana seguinte."""
    cliente, _ = ambiente
    assert _lancar(cliente, referencia="E2E-777").status_code == 201
    repetido = _lancar(cliente, referencia="E2E-777")

    assert repetido.status_code == 409
    assert "já foi registrado" in repetido.json()["detail"]

    v = cliente.get(f"/api/admin/overview?mes={MES}").json()["atual"]
    assert Decimal(str(v["receita_bruta_brl"])) == Decimal("180.00")


def test_sem_referencia_nao_ha_protecao_e_isso_e_deliberado(ambiente):
    """Quem tem o comprovante ganha a garantia; quem não tem consegue lançar."""
    cliente, _ = ambiente
    assert _lancar(cliente).status_code == 201
    assert _lancar(cliente).status_code == 201

    v = cliente.get(f"/api/admin/overview?mes={MES}").json()["atual"]
    assert v["pagamentos"] == 2


# ─── Receita ≠ crédito ────────────────────────────────────────────────────────


def test_por_padrao_nao_concede_credito(ambiente):
    """Acertar o extrato não pode entregar crédito de graça."""
    cliente, factory = ambiente
    _lancar(cliente, referencia="E2E-a", creditos=1500)
    assert asyncio.run(_saldo(factory)) == 0


def test_concedendo_o_credito_entra_pelo_ledger(ambiente):
    cliente, factory = ambiente
    resp = _lancar(
        cliente, referencia="E2E-b", conceder_creditos=True, creditos=1500
    )
    assert resp.status_code == 201
    assert asyncio.run(_saldo(factory)) == 1500

    async def lancamentos():
        async with factory() as db:
            return (
                (await db.execute(select(CreditLedger).where(CreditLedger.tipo == "topup")))
                .scalars()
                .all()
            )

    linhas = asyncio.run(lancamentos())
    assert len(linhas) == 1
    assert linhas[0].amount == 1500


def test_conceder_sem_dizer_quantos_e_recusado(ambiente):
    cliente, _ = ambiente
    resp = _lancar(cliente, referencia="E2E-c", conceder_creditos=True, creditos=0)
    assert resp.status_code == 422


# ─── Estorno e chargeback ─────────────────────────────────────────────────────


def test_estorno_tira_a_receita_do_mes(ambiente):
    cliente, _ = ambiente
    pid = _lancar(cliente, referencia="E2E-d").json()["id"]
    assert (
        Decimal(
            str(cliente.get(f"/api/admin/overview?mes={MES}").json()["atual"]["receita_bruta_brl"])
        )
        == Decimal("180.00")
    )

    resp = cliente.patch(f"/api/admin/payments/{pid}", json={"status": "refunded"})
    assert resp.status_code == 200

    v = cliente.get(f"/api/admin/overview?mes={MES}").json()["atual"]
    assert Decimal(str(v["receita_bruta_brl"])) == Decimal("0.00")


def test_chargeback_nao_mexe_no_saldo_de_quem_ja_usou(ambiente):
    """Tirar crédito de quem já processou vídeo deixaria a conta negativa."""
    cliente, factory = ambiente
    pid = _lancar(
        cliente, referencia="E2E-e", conceder_creditos=True, creditos=1500
    ).json()["id"]
    assert asyncio.run(_saldo(factory)) == 1500

    cliente.patch(f"/api/admin/payments/{pid}", json={"status": "chargeback"})
    assert asyncio.run(_saldo(factory)) == 1500


def test_status_invalido_e_recusado(ambiente):
    cliente, _ = ambiente
    pid = _lancar(cliente, referencia="E2E-f").json()["id"]
    assert cliente.patch(f"/api/admin/payments/{pid}", json={"status": "sumiu"}).status_code == 422


# ─── Assinatura manual ────────────────────────────────────────────────────────


def _assinar(cliente, **campos):
    corpo = {
        "email": "cliente@exemplo.com",
        "plan_code": "acordo",
        "valor_brl": "80.00",
        "creditos_mes": 1000,
        **campos,
    }
    return cliente.post("/api/admin/subscriptions", json=corpo)


def test_assinatura_manual_conta_no_mrr(ambiente):
    """Assinante de acordo de boca sumia de um dos números principais do painel."""
    cliente, _ = ambiente
    assert _assinar(cliente).status_code == 201

    v = cliente.get(f"/api/admin/overview?mes={MES}").json()["atual"]
    assert Decimal(str(v["mrr_brl"])) == Decimal("80.00")
    assert v["assinantes_ativos"] == 1


def test_duas_assinaturas_para_a_mesma_conta_sao_recusadas(ambiente):
    cliente, _ = ambiente
    assert _assinar(cliente).status_code == 201
    assert _assinar(cliente).status_code == 409


def test_encerrar_assinatura_manual(ambiente):
    cliente, _ = ambiente
    sid = _assinar(cliente).json()["id"]
    resp = cliente.delete(f"/api/admin/subscriptions/{sid}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "canceled"

    v = cliente.get(f"/api/admin/overview?mes={MES}").json()["atual"]
    assert v["assinantes_ativos"] == 0


def test_assinatura_do_gateway_nao_e_encerrada_por_aqui(ambiente):
    """Encerrar aqui deixaria o cartão sendo debitado (D118)."""
    cliente, factory = ambiente

    async def criar_do_gateway():
        async with factory() as db:
            user = await db.scalar(
                select(User).where(User.email == "cliente@exemplo.com")
            )
            sub = Subscription(
                user_id=user.id,
                plan_code="pro",
                valor_brl=Decimal("99.90"),
                creditos_mes=1200,
                status="active",
                gateway="mercadopago",
                gateway_preapproval_id="pre-1",
                started_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            )
            db.add(sub)
            await db.commit()
            return sub.id

    sid = asyncio.run(criar_do_gateway())
    resp = cliente.delete(f"/api/admin/subscriptions/{sid}")
    assert resp.status_code == 409
    assert "Mercado Pago" in resp.json()["detail"]


# ─── A fechadura ──────────────────────────────────────────────────────────────


def test_usuario_comum_nao_lanca_nada(ambiente):
    cliente, _ = ambiente
    cliente.post("/api/auth/logout")
    assert (
        cliente.post(
            "/api/auth/login",
            json={"email": "cliente@exemplo.com", "password": "uma-senha-bem-longa"},
        ).status_code
        == 200
    )

    assert _lancar(cliente, referencia="invasao").status_code == 403
    assert _assinar(cliente).status_code == 403
    assert cliente.get("/api/admin/payments").status_code == 403
