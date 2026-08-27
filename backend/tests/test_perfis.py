"""
Perfis: a nova organização, sem mexer no que o pipeline lê.

O risco desta mudança não é a tabela nova — é a tentação de fazer o perfil
SUBSTITUIR o nicho. Se o pipeline passasse a ler `profile_id`, todo job antigo
perderia a rubrica, e editar um perfil reescreveria o passado.

Por isso o que estes testes guardam é a fronteira: o perfil FORNECE
`source_type` na criação e some do caminho; daí para baixo nada mudou.
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
from app.models import Clip, Job, Profile, User
from app.services.profiles import adopt_orphan_jobs, seed_profiles


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "public_build", False)
    monkeypatch.setattr(settings, "clipmint_password", "")
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path / "storage"))
    settings.ensure_dirs()

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'p.db'}")
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


def _criar_perfil(cliente, nome="HZ Pod Clips", source="podcast", **extra):
    corpo = {"name": nome, "source_type": source, **extra}
    resp = cliente.post("/api/profiles", json=corpo)
    assert resp.status_code == 201, resp.text
    return resp.json()


# ─── O contrato com o pipeline ────────────────────────────────────────────────

def test_job_criado_por_perfil_grava_o_source_type(ambiente):
    """
    O perfil FORNECE o nicho; o job GRAVA. É essa a fronteira.

    Se o job dependesse do perfil para saber sua rubrica, editar o perfil
    reescreveria a análise de vídeos já feitos.
    """
    cliente, factory = ambiente
    perfil = _criar_perfil(cliente, source="gameplay")

    resp = cliente.post(
        "/api/jobs",
        json={
            "profile_id": perfil["id"],
            "youtube_url": "https://youtu.be/dQw4w9WgXcQ",
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["source_type"] == "gameplay"
    assert resp.json()["profile_id"] == perfil["id"]


def test_editar_o_perfil_nao_muda_job_antigo(ambiente):
    """O passado não se reescreve — é o motivo de o job guardar o próprio nicho."""
    cliente, _ = ambiente
    perfil = _criar_perfil(cliente, source="podcast")
    job = cliente.post(
        "/api/jobs",
        json={"profile_id": perfil["id"], "youtube_url": "https://youtu.be/aaaaaaaaaaa"},
    ).json()
    assert job["source_type"] == "podcast"

    cliente.put(
        f"/api/profiles/{perfil['id']}",
        json={"name": "Agora é gameplay", "source_type": "gameplay"},
    )

    depois = cliente.get(f"/api/jobs/{job['id']}").json()
    assert depois["source_type"] == "podcast", "o perfil reescreveu a rubrica do job"


def test_payload_antigo_continua_funcionando(ambiente):
    """
    Sem `profile_id`, exatamente como antes.

    A API não pode ter passado a exigir perfil: quebraria qualquer cliente e o
    próprio retry.
    """
    cliente, _ = ambiente
    resp = cliente.post(
        "/api/jobs",
        json={
            "youtube_url": "https://youtu.be/dQw4w9WgXcQ",
            "source_type": "gameplay",
            "layout_mode": "streamer",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["source_type"] == "gameplay"
    assert resp.json()["profile_id"] is None


def test_source_type_explicito_vence_o_do_perfil(ambiente):
    """Quem manda o valor manda; o perfil é só o padrão."""
    cliente, _ = ambiente
    perfil = _criar_perfil(cliente, source="podcast")
    resp = cliente.post(
        "/api/jobs",
        json={
            "profile_id": perfil["id"],
            "youtube_url": "https://youtu.be/dQw4w9WgXcQ",
            "source_type": "gameplay",
        },
    )
    assert resp.json()["source_type"] == "gameplay"


def test_perfil_de_outro_usuario_e_recusado(ambiente):
    cliente, factory = ambiente
    perfil = _criar_perfil(cliente)

    async def outro_dono():
        async with factory() as db:
            outro = User(email="outro@x.com", password_hash="", is_active=True)
            db.add(outro)
            await db.commit()
            await db.refresh(outro)
            p = (await db.execute(select(Profile))).scalars().first()
            p.user_id = outro.id
            await db.commit()

    asyncio.run(outro_dono())

    resp = cliente.post(
        "/api/jobs",
        json={"profile_id": perfil["id"], "youtube_url": "https://youtu.be/dQw4w9WgXcQ"},
    )
    assert resp.status_code == 404


# ─── Excluir perfil não destrói trabalho ──────────────────────────────────────

def test_excluir_perfil_preserva_jobs_e_clipes(ambiente):
    """
    O perfil é a configuração; o job é o trabalho.

    Apagar os vídeos junto seria destruir trabalho para remover uma preferência.
    """
    cliente, factory = ambiente
    perfil = _criar_perfil(cliente)
    job = cliente.post(
        "/api/jobs",
        json={"profile_id": perfil["id"], "youtube_url": "https://youtu.be/dQw4w9WgXcQ"},
    ).json()

    async def semear_clip():
        async with factory() as db:
            db.add(
                Clip(
                    id="c1", job_id=job["id"], start_time=0, end_time=30, duration=30,
                    virality_score=9.0, status="ready",
                )
            )
            await db.commit()

    asyncio.run(semear_clip())

    assert cliente.delete(f"/api/profiles/{perfil['id']}").status_code == 204

    # O job continua existindo, visível, e com o nicho intacto.
    depois = cliente.get(f"/api/jobs/{job['id']}")
    assert depois.status_code == 200
    assert depois.json()["profile_id"] is None
    assert depois.json()["source_type"] == "podcast"
    assert len(depois.json()["clips"]) == 1


def test_job_sem_perfil_continua_na_listagem(ambiente):
    """Sumir com job antigo seria perder trabalho de vista."""
    cliente, factory = ambiente

    async def semear_antigo():
        async with factory() as db:
            db.add(
                Job(id="antigo", youtube_url="u", status="done", source_type="podcast")
            )
            await db.commit()

    asyncio.run(semear_antigo())
    ids = [j["id"] for j in cliente.get("/api/jobs").json()]
    assert "antigo" in ids


# ─── Filtros ──────────────────────────────────────────────────────────────────

def test_listagem_filtra_por_perfil(ambiente):
    cliente, _ = ambiente
    a = _criar_perfil(cliente, "Perfil A", "podcast")
    b = _criar_perfil(cliente, "Perfil B", "gameplay")

    ja = cliente.post("/api/jobs", json={"profile_id": a["id"], "youtube_url": "https://youtu.be/aaaaaaaaaaa"}).json()
    jb = cliente.post("/api/jobs", json={"profile_id": b["id"], "youtube_url": "https://youtu.be/bbbbbbbbbbb"}).json()

    da = [j["id"] for j in cliente.get("/api/jobs", params={"profile_id": a["id"]}).json()]
    assert da == [ja["id"]]
    db_ = [j["id"] for j in cliente.get("/api/jobs", params={"profile_id": b["id"]}).json()]
    assert db_ == [jb["id"]]


def test_filtro_por_nicho_continua_existindo(ambiente):
    """É como os jobs anteriores aos perfis continuam alcançáveis."""
    cliente, _ = ambiente
    cliente.post("/api/jobs", json={"youtube_url": "https://youtu.be/aaaaaaaaaaa", "source_type": "gameplay"})
    r = cliente.get("/api/jobs", params={"source": "gameplay"}).json()
    assert len(r) == 1


# ─── Contagens ────────────────────────────────────────────────────────────────

def test_contagens_vem_dos_jobs_e_clipes(ambiente):
    """Nenhum contador em coluna: dois números que possam discordar é pior."""
    cliente, factory = ambiente
    perfil = _criar_perfil(cliente)
    job = cliente.post(
        "/api/jobs",
        json={"profile_id": perfil["id"], "youtube_url": "https://youtu.be/dQw4w9WgXcQ"},
    ).json()

    async def semear():
        async with factory() as db:
            for i in range(3):
                db.add(Clip(id=f"c{i}", job_id=job["id"], start_time=0, end_time=30,
                            duration=30, virality_score=8.0,
                            status="ready" if i < 2 else "error"))
            await db.commit()

    asyncio.run(semear())

    p = cliente.get(f"/api/profiles/{perfil['id']}").json()
    assert p["job_count"] == 1
    assert p["clip_count"] == 2, "só clipe pronto conta"
    assert p["last_generated_at"] is not None


# ─── Semeadura ────────────────────────────────────────────────────────────────

def test_semeadura_so_cria_nicho_que_a_pessoa_usou(ambiente):
    """Quem nunca fez gameplay não ganha um perfil de gameplay vazio."""
    cliente, factory = ambiente

    async def cenario():
        async with factory() as db:
            dono = User(email="dono@x.com", password_hash="", is_owner=True, is_active=True)
            db.add(dono)
            await db.commit()
            await db.refresh(dono)
            db.add(Job(id="j1", user_id=dono.id, youtube_url="u", source_type="podcast", status="done"))
            await db.commit()

            criados = await seed_profiles(db, dono)
            ligados = await adopt_orphan_jobs(db, dono)
            perfis = (await db.execute(select(Profile))).scalars().all()
            job = (await db.execute(select(Job))).scalars().first()
            return criados, ligados, [p.source_type for p in perfis], job.profile_id

    criados, ligados, nichos, profile_id = asyncio.run(cenario())
    assert criados == 1 and nichos == ["podcast"]
    assert ligados == 1 and profile_id is not None


def test_semeadura_e_idempotente(ambiente):
    cliente, factory = ambiente

    async def cenario():
        async with factory() as db:
            dono = User(email="dono@x.com", password_hash="", is_owner=True, is_active=True)
            db.add(dono)
            await db.commit()
            await db.refresh(dono)
            db.add(Job(id="j1", user_id=dono.id, youtube_url="u", source_type="podcast", status="done"))
            await db.commit()
            await seed_profiles(db, dono)
            segunda = await seed_profiles(db, dono)
            perfis = (await db.execute(select(Profile))).scalars().all()
            return segunda, len(perfis)

    segunda, total = asyncio.run(cenario())
    assert segunda == 0 and total == 1


# ─── Validação ────────────────────────────────────────────────────────────────

def test_nicho_invalido_e_recusado(ambiente):
    cliente, _ = ambiente
    assert cliente.post(
        "/api/profiles", json={"name": "X", "source_type": "entrevistas"}
    ).status_code == 422


def test_nome_vazio_e_recusado(ambiente):
    cliente, _ = ambiente
    assert cliente.post(
        "/api/profiles", json={"name": "   ", "source_type": "podcast"}
    ).status_code == 422


def test_avatar_desconhecido_cai_no_padrao(ambiente):
    """Chave de ícone, não arquivo — o front só sabe desenhar as que conhece."""
    cliente, _ = ambiente
    p = _criar_perfil(cliente, avatar="dragao-roxo")
    assert p["avatar"] == "person"
