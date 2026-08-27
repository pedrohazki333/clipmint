"""
Um usuário não pode alcançar nada de outro.

Este é o teste que decide se o produto pode ser multiusuário. O que está em
jogo não é abstrato: o `/clips/{id}/download` entrega o arquivo de vídeo, que é
o produto inteiro. Um id vazando ali é o trabalho de alguém na mão de outro.

A regra escolhida é **404, nunca 403**, para recurso de outra pessoa: um 403
confirmaria que aquele id existe, e daria para varrer ids descobrindo o que os
outros estão processando. Para quem não é dono, o recurso simplesmente não
existe.
"""

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base, get_db
from app.main import register_routers
from app.models import Clip, Job


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    """App em modo público, com banco próprio."""
    monkeypatch.setattr(settings, "public_build", True)
    monkeypatch.setattr(settings, "clipmint_password", "")
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path / "storage"))
    settings.ensure_dirs()

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'iso.db'}")
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
    return app, factory


def _cliente(app, email: str) -> TestClient:
    """Um navegador com sessão própria — cookies não são compartilhados."""
    c = TestClient(app)
    resp = c.post(
        "/api/auth/register",
        json={"email": email, "password": "uma-senha-bem-longa-aqui"},
    )
    assert resp.status_code == 201, resp.text
    return c


def _criar_job(cliente: TestClient, url: str = "https://youtu.be/dQw4w9WgXcQ") -> str:
    resp = cliente.post(
        "/api/jobs", json={"youtube_url": url, "source_type": "podcast"}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# ─── Jobs ──────────────────────────────────────────────────────────────────────

def test_lista_de_jobs_so_traz_os_proprios(ambiente):
    app, _ = ambiente
    alice = _cliente(app, "alice@exemplo.com")
    bruno = _cliente(app, "bruno@exemplo.com")

    job_alice = _criar_job(alice)
    job_bruno = _criar_job(bruno)

    da_alice = [j["id"] for j in alice.get("/api/jobs").json()]
    do_bruno = [j["id"] for j in bruno.get("/api/jobs").json()]

    assert da_alice == [job_alice]
    assert do_bruno == [job_bruno]


@pytest.mark.parametrize(
    "metodo,sufixo",
    [
        ("get", ""),
        ("delete", ""),
        ("post", "/retry"),
    ],
)
def test_job_de_outro_responde_404(ambiente, metodo, sufixo):
    app, _ = ambiente
    alice = _cliente(app, "alice@exemplo.com")
    bruno = _cliente(app, "bruno@exemplo.com")

    job_alice = _criar_job(alice)

    resp = getattr(bruno, metodo)(f"/api/jobs/{job_alice}{sufixo}")
    assert resp.status_code == 404, (
        f"{metodo.upper()} respondeu {resp.status_code} — qualquer coisa que não "
        f"seja 404 confirma que o job existe"
    )


def test_delete_de_outro_nao_apaga_nada(ambiente):
    """O 404 tem que ser recusa de verdade, não recusa depois de apagar."""
    app, _ = ambiente
    alice = _cliente(app, "alice@exemplo.com")
    bruno = _cliente(app, "bruno@exemplo.com")

    job_alice = _criar_job(alice)
    assert bruno.delete(f"/api/jobs/{job_alice}").status_code == 404

    # A Alice continua enxergando o job dela.
    assert alice.get(f"/api/jobs/{job_alice}").status_code == 200


# ─── Clips ─────────────────────────────────────────────────────────────────────

def _semear_clip(factory, job_id: str, clip_id: str, arquivo) -> None:
    async def executar():
        async with factory() as db:
            db.add(
                Clip(
                    id=clip_id,
                    job_id=job_id,
                    start_time=0,
                    end_time=30,
                    duration=30,
                    virality_score=9.0,
                    status="ready",
                    file_path=str(arquivo),
                    file_size_bytes=arquivo.stat().st_size,
                )
            )
            await db.commit()

    asyncio.run(executar())


@pytest.mark.parametrize(
    "metodo,sufixo,corpo",
    [
        ("get", "", None),
        ("get", "/download", None),
        ("put", "/metrics", {"views": 10}),
        ("post", "/validate", {"performance": "bom", "aprendizado": "x", "views": 1}),
    ],
)
def test_clip_de_outro_responde_404(ambiente, tmp_path, metodo, sufixo, corpo):
    """
    O clip não guarda dono — quem guarda é o job.

    Sem a junção com `jobs`, um id de clip adivinhado daria o vídeo de outra
    pessoa. O `/download` é o caso grave: ele entrega o arquivo.
    """
    app, factory = ambiente
    alice = _cliente(app, "alice@exemplo.com")
    bruno = _cliente(app, "bruno@exemplo.com")

    job_alice = _criar_job(alice)
    arquivo = tmp_path / "clip.mp4"
    arquivo.write_bytes(b"conteudo do video da alice")
    _semear_clip(factory, job_alice, "clip-da-alice", arquivo)

    kwargs = {"json": corpo} if corpo else {}
    resp = getattr(bruno, metodo)(f"/api/clips/clip-da-alice{sufixo}", **kwargs)
    assert resp.status_code == 404

    # E a dona continua alcançando o próprio clip.
    assert alice.get("/api/clips/clip-da-alice").status_code == 200


def test_download_do_proprio_clip_funciona(ambiente, tmp_path):
    """A trava não pode ter fechado a porta para o dono."""
    app, factory = ambiente
    alice = _cliente(app, "alice@exemplo.com")
    job = _criar_job(alice)
    arquivo = tmp_path / "clip.mp4"
    arquivo.write_bytes(b"conteudo")
    _semear_clip(factory, job, "meu-clip", arquivo)

    resp = alice.get("/api/clips/meu-clip/download")
    assert resp.status_code == 200
    assert resp.content == b"conteudo"


# ─── Sessão ────────────────────────────────────────────────────────────────────

def test_sem_sessao_nada_e_acessivel(ambiente):
    app, _ = ambiente
    anonimo = TestClient(app)
    for caminho in ("/api/jobs", "/api/clips/qualquer", "/api/clips/qualquer/download"):
        assert anonimo.get(caminho).status_code == 401, caminho


def test_logout_encerra_o_acesso(ambiente):
    app, _ = ambiente
    alice = _cliente(app, "alice@exemplo.com")
    assert alice.get("/api/jobs").status_code == 200

    assert alice.post("/api/auth/logout").status_code == 204
    assert alice.get("/api/jobs").status_code == 401


def test_logout_de_todos_derruba_as_outras_sessoes(ambiente):
    """
    É o que a sessão em banco permite e o token assinado não permitiria.

    Com JWT, a sessão do outro aparelho continuaria valendo até expirar.
    """
    app, _ = ambiente
    celular = _cliente(app, "alice@exemplo.com")
    # Segundo aparelho: mesma conta, sessão nova.
    notebook = TestClient(app)
    assert notebook.post(
        "/api/auth/login",
        json={"email": "alice@exemplo.com", "password": "uma-senha-bem-longa-aqui"},
    ).status_code == 200
    assert notebook.get("/api/jobs").status_code == 200

    assert celular.post("/api/auth/logout-all").status_code == 200
    assert notebook.get("/api/jobs").status_code == 401


def test_conta_desativada_perde_acesso_na_hora(ambiente):
    """Sem esperar a sessão expirar."""
    app, factory = ambiente
    alice = _cliente(app, "alice@exemplo.com")
    assert alice.get("/api/jobs").status_code == 200

    async def desativar():
        from app.models import User

        async with factory() as db:
            await db.execute(User.__table__.update().values(is_active=False))
            await db.commit()

    asyncio.run(desativar())
    assert alice.get("/api/jobs").status_code == 401


# ─── Cadastro e login ──────────────────────────────────────────────────────────

def test_email_duplicado_e_recusado(ambiente):
    app, _ = ambiente
    _cliente(app, "alice@exemplo.com")
    outro = TestClient(app)
    resp = outro.post(
        "/api/auth/register",
        json={"email": "ALICE@Exemplo.com", "password": "outra-senha-bem-longa"},
    )
    assert resp.status_code == 409, "o e-mail foi normalizado antes de comparar?"


def test_senha_curta_e_recusada_com_orientacao(ambiente):
    app, _ = ambiente
    c = TestClient(app)
    resp = c.post(
        "/api/auth/register", json={"email": "x@exemplo.com", "password": "curta"}
    )
    assert resp.status_code == 422
    assert "caracteres" in resp.text


def test_login_errado_nao_revela_se_a_conta_existe(ambiente):
    """A mesma resposta para conta inexistente e senha errada."""
    app, _ = ambiente
    _cliente(app, "alice@exemplo.com")
    c = TestClient(app)

    inexistente = c.post(
        "/api/auth/login",
        json={"email": "ninguem@exemplo.com", "password": "uma-senha-bem-longa-aqui"},
    )
    senha_errada = c.post(
        "/api/auth/login",
        json={"email": "alice@exemplo.com", "password": "senha-errada-mas-longa"},
    )
    assert inexistente.status_code == senha_errada.status_code == 401
    assert inexistente.json() == senha_errada.json()


def test_cookie_de_sessao_nao_e_legivel_por_javascript(ambiente):
    app, _ = ambiente
    c = TestClient(app)
    resp = c.post(
        "/api/auth/register",
        json={"email": "x@exemplo.com", "password": "uma-senha-bem-longa-aqui"},
    )
    cookie = resp.headers.get("set-cookie", "")
    assert "httponly" in cookie.lower()
    assert "samesite=lax" in cookie.lower()


def test_token_da_sessao_nao_e_guardado_em_claro(ambiente):
    """Um dump da tabela não pode permitir se passar por ninguém."""
    app, factory = ambiente
    c = _cliente(app, "alice@exemplo.com")
    token = c.cookies.get("clipmint_session")
    assert token

    async def ler():
        from app.models import Session
        from sqlalchemy import select

        async with factory() as db:
            return (await db.execute(select(Session.token_hash))).scalars().all()

    guardados = asyncio.run(ler())
    assert guardados and token not in guardados


def test_cadastro_fechado_recusa_conta_nova(ambiente, monkeypatch):
    """O modo para abrir o produto a um grupo fechado antes de abrir a todos."""
    app, _ = ambiente
    monkeypatch.setattr(settings, "registration_open", False)
    c = TestClient(app)
    resp = c.post(
        "/api/auth/register",
        json={"email": "x@exemplo.com", "password": "uma-senha-bem-longa-aqui"},
    )
    assert resp.status_code == 403


# ─── Versão pessoal ────────────────────────────────────────────────────────────

def test_versao_pessoal_nao_expoe_cadastro(tmp_path, monkeypatch):
    """Lá não há contas — a porta é a senha única de sempre."""
    monkeypatch.setattr(settings, "public_build", False)
    app = FastAPI()
    register_routers(app)
    caminhos = {r.path for r in app.routes}
    assert not any("/auth/" in c for c in caminhos)


def test_versao_pessoal_atribui_os_jobs_ao_dono(tmp_path, monkeypatch):
    """
    Lá não há login, mas os jobs precisam ter dono.

    É o que permite à cota (Fatia 7) e ao TTL falarem em usuário sem que o
    pipeline precise saber em qual das duas versões está rodando.
    """
    monkeypatch.setattr(settings, "public_build", False)
    monkeypatch.setattr(settings, "clipmint_password", "")
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path / "storage"))
    settings.ensure_dirs()

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'pes.db'}")
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
    cliente = TestClient(app)

    # Sem cadastro nenhum, criar job funciona.
    resp = cliente.post(
        "/api/jobs",
        json={"youtube_url": "https://youtu.be/dQw4w9WgXcQ", "source_type": "podcast"},
    )
    assert resp.status_code == 201, resp.text
    job_id = resp.json()["id"]

    async def dono_do_job():
        from sqlalchemy import select

        from app.models import User

        async with factory() as db:
            job = (await db.execute(select(Job).where(Job.id == job_id))).scalar_one()
            dono = (await db.execute(select(User))).scalars().all()
            return job.user_id, dono

    user_id, donos = asyncio.run(dono_do_job())
    assert len(donos) == 1, "a versão pessoal tem que ter exatamente um usuário"
    assert donos[0].is_owner is True
    assert user_id == donos[0].id, "o job nasceu sem dono"

    # E o job continua visível para quem o criou.
    assert cliente.get(f"/api/jobs/{job_id}").status_code == 200


def test_job_orfao_e_visivel_na_versao_pessoal(tmp_path, monkeypatch):
    """
    Job anterior às contas pertence ao dono — não há de quem mais pudesse ser.

    Sem isto, quem já usava a ferramenta perderia de vista os próprios jobs se a
    adoção do startup não tivesse rodado.
    """
    monkeypatch.setattr(settings, "public_build", False)
    monkeypatch.setattr(settings, "clipmint_password", "")
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path / "storage"))
    settings.ensure_dirs()

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'orf.db'}")
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async def preparar():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with factory() as db:
            db.add(Job(id="antigo", youtube_url="u", status="done", user_id=None))
            await db.commit()

    asyncio.run(preparar())

    async def override_db():
        async with factory() as session:
            yield session

    app = FastAPI()
    register_routers(app)
    app.dependency_overrides[get_db] = override_db
    cliente = TestClient(app)

    assert [j["id"] for j in cliente.get("/api/jobs").json()] == ["antigo"]
    assert cliente.get("/api/jobs/antigo").status_code == 200


def test_job_orfao_e_invisivel_no_publico(ambiente):
    """No público, job sem dono não é de ninguém — atribuí-lo seria inventar."""
    app, factory = ambiente

    async def semear():
        async with factory() as db:
            db.add(Job(id="sem-dono", youtube_url="u", status="done", user_id=None))
            await db.commit()

    asyncio.run(semear())

    alice = _cliente(app, "alice@exemplo.com")
    assert alice.get("/api/jobs").json() == []
    assert alice.get("/api/jobs/sem-dono").status_code == 404
