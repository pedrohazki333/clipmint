"""
Recuperação de senha: a única porta de volta para uma conta com créditos dentro.

Bug aqui não é tela quebrada — é conta invadida ou cliente trancado para fora.
Os quatro riscos que estes testes guardam:

1. **Vazar quem tem conta.** A rota responde igual para e-mail com e sem conta.
2. **Token reutilizável.** Quem ler o e-mail depois (caixa compartilhada,
   encaminhamento) não pode trocar a senha de novo semanas depois.
3. **Sessão sobrevivente.** Quem pede redefinição costuma estar com medo de que
   alguém tenha entrado; a troca precisa derrubar as sessões antigas.
4. **Aceitar sem poder entregar.** Sem SMTP a rota recusa na porta, em vez de
   responder 204 e deixar a pessoa esperando um e-mail que não vem.
"""

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base, get_db
from app.main import register_routers
from app.models import PasswordReset, Session, User
from app.services import mailer

SENHA = "uma-frase-que-eu-lembro"
NOVA = "outra-frase-bem-diferente"


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "public_build", True)
    monkeypatch.setattr(settings, "clipmint_password", "")
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path / "storage"))
    monkeypatch.setattr(settings, "smtp_host", "smtp.exemplo.com")
    monkeypatch.setattr(settings, "smtp_from", "nao-responda@clipmint.com.br")
    monkeypatch.setattr(settings, "public_base_url", "https://app.clipmint.com.br")
    settings.ensure_dirs()

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'r.db'}")
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async def criar():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(criar())

    async def override_db():
        async with factory() as session:
            yield session

    app = FastAPI()
    register_routers(app)
    app.dependency_overrides[get_db] = override_db
    return TestClient(app), factory


@pytest.fixture
def enviados(monkeypatch):
    """Captura os e-mails em vez de mandar. Devolve a lista."""
    caixa = []

    async def falso(to, subject, body):
        caixa.append({"to": to, "subject": subject, "body": body})

    monkeypatch.setattr(mailer, "send", falso)
    return caixa


def _criar_conta(cliente, email="cliente@exemplo.com"):
    resp = cliente.post(
        "/api/auth/register", json={"email": email, "password": SENHA}
    )
    assert resp.status_code == 201, resp.text
    return resp


def _link(caixa) -> str:
    """O token, extraído do corpo do e-mail como o usuário o extrairia."""
    corpo = caixa[-1]["body"]
    trecho = [l for l in corpo.split("\n") if "redefinir-senha?token=" in l][0]
    return trecho.split("token=", 1)[1].strip()


# ─── O caminho feliz ───────────────────────────────────────────────────────────

def test_pedir_e_trocar_a_senha(ambiente, enviados):
    cliente, _ = ambiente
    _criar_conta(cliente)
    cliente.post("/api/auth/logout")

    assert cliente.post(
        "/api/auth/forgot-password", json={"email": "cliente@exemplo.com"}
    ).status_code == 204
    assert len(enviados) == 1
    assert enviados[0]["to"] == "cliente@exemplo.com"

    token = _link(enviados)
    resp = cliente.post(
        "/api/auth/reset-password", json={"token": token, "password": NOVA}
    )
    assert resp.status_code == 200, resp.text

    # A senha velha morreu; a nova entra.
    cliente.post("/api/auth/logout")
    assert cliente.post(
        "/api/auth/login", json={"email": "cliente@exemplo.com", "password": SENHA}
    ).status_code == 401
    assert cliente.post(
        "/api/auth/login", json={"email": "cliente@exemplo.com", "password": NOVA}
    ).status_code == 200


# ─── Os quatro riscos ──────────────────────────────────────────────────────────

def test_email_sem_conta_responde_igual_e_nao_manda_nada(ambiente, enviados):
    """204 nos dois casos: distinguir entregaria a lista de quem tem conta."""
    cliente, _ = ambiente
    resp = cliente.post(
        "/api/auth/forgot-password", json={"email": "ninguem@exemplo.com"}
    )
    assert resp.status_code == 204
    assert enviados == []


def test_o_link_so_funciona_uma_vez(ambiente, enviados):
    """Quem ler o e-mail depois não troca a senha de novo."""
    cliente, _ = ambiente
    _criar_conta(cliente)
    cliente.post("/api/auth/forgot-password", json={"email": "cliente@exemplo.com"})
    token = _link(enviados)

    assert cliente.post(
        "/api/auth/reset-password", json={"token": token, "password": NOVA}
    ).status_code == 200
    segunda = cliente.post(
        "/api/auth/reset-password", json={"token": token, "password": "mais-outra-senha"}
    )
    assert segunda.status_code == 400
    assert "não vale mais" in segunda.json()["detail"]


def test_trocar_a_senha_derruba_as_outras_sessoes(ambiente, enviados):
    """Quem pede redefinição pode estar sendo invadido agora."""
    cliente, factory = ambiente
    _criar_conta(cliente)

    async def sessoes() -> int:
        async with factory() as db:
            return len((await db.execute(select(Session))).scalars().all())

    # Um segundo aparelho, com sessão própria.
    outro = TestClient(cliente.app)
    outro.post(
        "/api/auth/login", json={"email": "cliente@exemplo.com", "password": SENHA}
    )
    assert asyncio.run(sessoes()) == 2

    cliente.post("/api/auth/forgot-password", json={"email": "cliente@exemplo.com"})
    cliente.post(
        "/api/auth/reset-password", json={"token": _link(enviados), "password": NOVA}
    )

    # Sobra só a sessão recém-aberta pela própria redefinição.
    assert asyncio.run(sessoes()) == 1
    assert outro.get("/api/auth/me").json() is None


def test_sem_smtp_a_rota_recusa_em_vez_de_prometer(ambiente, monkeypatch):
    """503 é melhor que 204: aceitar sem poder entregar deixa a pessoa esperando."""
    cliente, _ = ambiente
    monkeypatch.setattr(settings, "smtp_host", "")
    _criar_conta(cliente)

    resp = cliente.post(
        "/api/auth/forgot-password", json={"email": "cliente@exemplo.com"}
    )
    assert resp.status_code == 503
    assert "não envia e-mail" in resp.json()["detail"]


# ─── Bordas ────────────────────────────────────────────────────────────────────

def test_token_vencido_nao_troca_nada(ambiente, enviados):
    cliente, factory = ambiente
    _criar_conta(cliente)
    cliente.post("/api/auth/forgot-password", json={"email": "cliente@exemplo.com"})
    token = _link(enviados)

    async def envelhecer():
        from datetime import datetime, timedelta, timezone

        async with factory() as db:
            pedido = (await db.execute(select(PasswordReset))).scalars().first()
            pedido.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
            await db.commit()

    asyncio.run(envelhecer())

    assert cliente.post(
        "/api/auth/reset-password", json={"token": token, "password": NOVA}
    ).status_code == 400


def test_senha_curta_e_recusada_antes_de_gastar_o_token(ambiente, enviados):
    """Errar o tamanho não pode custar o link — a pessoa tentaria de novo e falharia."""
    cliente, _ = ambiente
    _criar_conta(cliente)
    cliente.post("/api/auth/forgot-password", json={"email": "cliente@exemplo.com"})
    token = _link(enviados)

    assert cliente.post(
        "/api/auth/reset-password", json={"token": token, "password": "curta"}
    ).status_code == 422
    # O token sobreviveu: agora vale com uma senha boa.
    assert cliente.post(
        "/api/auth/reset-password", json={"token": token, "password": NOVA}
    ).status_code == 200


def test_token_inventado_nao_entra(ambiente):
    cliente, _ = ambiente
    _criar_conta(cliente)
    assert cliente.post(
        "/api/auth/reset-password",
        json={"token": "x" * 40, "password": NOVA},
    ).status_code == 400


def test_conta_desativada_nao_recebe_link(ambiente, enviados):
    cliente, factory = ambiente
    _criar_conta(cliente)

    async def desativar():
        async with factory() as db:
            user = (await db.execute(select(User))).scalars().first()
            user.is_active = False
            await db.commit()

    asyncio.run(desativar())

    assert cliente.post(
        "/api/auth/forgot-password", json={"email": "cliente@exemplo.com"}
    ).status_code == 204
    assert enviados == []
