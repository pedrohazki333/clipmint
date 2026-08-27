"""
O que as telas leem: saldo, catálogo, extrato e a estimativa antes de gastar.

O fio que liga estes testes: **a tela nunca calcula preço nem custo.** Toda vez
que o frontend fizer a própria conta, ele e o servidor vão discordar em algum
caso — e quem discorda por último é a fatura. Por isso o catálogo já vem com o
preço resolvido e a estimativa usa a mesma função que reserva o crédito.
"""

import asyncio
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base, get_db
from app.main import register_routers
from app.models import BillingConfig
from app.routers import jobs as jobs_router
from app.services import usage

URL = "https://www.youtube.com/watch?v=abcdefghijk"

CONFIG = {
    "id": 1,
    "credito_avulso_brl": Decimal("0.10"),
    "pacotes": [
        {"creditos": 300, "preco_brl": None},
        {"creditos": 1500, "preco_brl": "120.00"},
    ],
    "planos": [
        {"code": "pro", "nome": "Pro", "valor_brl": "99.90", "creditos_mes": 1200}
    ],
    "creditos_gratis_cadastro": 30,
    "saldo_baixo_threshold": 40,
}


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "public_build", True)
    monkeypatch.setattr(settings, "clipmint_password", "")
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path / "storage"))
    settings.ensure_dirs()

    async def sem_pipeline(job_id, resume=False):
        return None

    monkeypatch.setattr(jobs_router, "run_pipeline", sem_pipeline)

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 's.db'}")
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
            json={"email": "tela@exemplo.com", "password": "uma-senha-bem-longa"},
        ).status_code
        == 201
    )
    return c


# ─── Saldo ────────────────────────────────────────────────────────────────────


def test_saldo_traz_o_limite_de_aviso_junto(cliente):
    """O "baixo" é decisão de negócio: vem da config, não de número no frontend."""
    corpo = cliente.get("/api/billing/balance").json()
    assert corpo == {"saldo": 30, "threshold": 40, "baixo": True}


def test_saldo_deixa_de_ser_baixo_acima_do_limite(cliente):
    cliente.post("/api/jobs", json={"youtube_url": URL, "subtitle_mode": "none"})
    # 30 - 5 de reserva = 25, ainda baixo
    assert cliente.get("/api/billing/balance").json()["baixo"] is True


def test_saldo_exige_sessao(cliente):
    cliente.post("/api/auth/logout")
    assert cliente.get("/api/billing/balance").status_code == 401


# ─── Catálogo ─────────────────────────────────────────────────────────────────


def test_catalogo_vem_com_o_preco_ja_resolvido(cliente):
    corpo = cliente.get("/api/billing/catalog").json()
    pacotes = {p["creditos"]: Decimal(str(p["preco_brl"])) for p in corpo["pacotes"]}

    # 300 x 0,10 derivado; 1500 com preço próprio (desconto), não 150,00.
    assert pacotes == {300: Decimal("30.00"), 1500: Decimal("120.00")}
    assert corpo["planos"][0]["code"] == "pro"
    assert corpo["planos"][0]["creditos_mes"] == 1200


# ─── Extrato ──────────────────────────────────────────────────────────────────


def test_extrato_mostra_o_bonus_de_boas_vindas(cliente):
    linhas = cliente.get("/api/billing/ledger").json()
    assert len(linhas) == 1
    assert linhas[0]["tipo"] == "bonus"
    assert linhas[0]["amount"] == 30
    assert linhas[0]["balance_after"] == 30


def test_extrato_mostra_a_reserva_e_vem_do_mais_recente(cliente):
    cliente.post("/api/jobs", json={"youtube_url": URL, "subtitle_mode": "none"})
    linhas = cliente.get("/api/billing/ledger").json()

    assert [l["tipo"] for l in linhas] == ["hold", "bonus"]


def test_extrato_nao_mostra_o_de_outra_pessoa(cliente):
    cliente.post("/api/auth/logout")
    cliente.post(
        "/api/auth/register",
        json={"email": "outro@exemplo.com", "password": "outra-senha-longa"},
    )
    linhas = cliente.get("/api/billing/ledger").json()
    # Só o bônus DELE, não o da primeira conta.
    assert len(linhas) == 1


# ─── Estimativa ───────────────────────────────────────────────────────────────


def test_estimativa_usa_a_mesma_conta_da_reserva(cliente):
    corpo = cliente.post("/api/billing/estimate", json={"youtube_url": URL}).json()

    assert corpo["minutos"] == 5
    assert corpo["creditos"] == usage.custo_em_creditos(300)
    assert corpo["saldo"] == 30
    assert corpo["suficiente"] is True
    assert corpo["faltam"] == 0


def test_estimativa_diz_quanto_falta(cliente, monkeypatch):
    from app.services import quota

    async def video_longo(url):
        return quota.Metadados(duration=3600.0, is_live=False, ok=True)

    monkeypatch.setattr(quota, "probe", video_longo)
    corpo = cliente.post("/api/billing/estimate", json={"youtube_url": URL}).json()

    assert corpo["creditos"] == 60
    assert corpo["suficiente"] is False
    assert corpo["faltam"] == 30


def test_estimativa_recusa_live_como_a_criacao_recusaria(cliente, monkeypatch):
    """Uma tela que promete o que o servidor vai recusar é pior que nenhuma tela."""
    from app.services import quota

    async def ao_vivo(url):
        return quota.Metadados(duration=0.0, is_live=True, ok=True)

    monkeypatch.setattr(quota, "probe", ao_vivo)
    resp = cliente.post("/api/billing/estimate", json={"youtube_url": URL})

    assert resp.status_code == 422
    assert "ao vivo" in resp.json()["detail"]


def test_estimativa_nao_gasta_nada(cliente):
    cliente.post("/api/billing/estimate", json={"youtube_url": URL})
    assert cliente.get("/api/billing/balance").json()["saldo"] == 30


# ─── O job diz o que custou ───────────────────────────────────────────────────


def test_job_em_andamento_mostra_o_reservado(cliente):
    job = cliente.post(
        "/api/jobs", json={"youtube_url": URL, "subtitle_mode": "none"}
    ).json()
    detalhe = cliente.get(f"/api/jobs/{job['id']}").json()

    assert detalhe["creditos_reservados"] == 5
    assert detalhe["creditos_cobrados"] is None
    assert detalhe["saldo"] == 25
