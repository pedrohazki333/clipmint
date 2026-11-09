"""
A página de gerar sem perfil: o destaque da legenda escolhido por job, o vídeo
conferido antes de gerar e o rosa da marca que virou o coral do app.

Os três são o que a tela de gerar passou a pedir à API. O destaque mexe só na
CÓPIA do estilo que o job guarda — o perfil continua como estava, que é a mesma
regra de sempre: mudar uma coisa afeta o que vem depois, nunca reescreve o resto.
"""

import asyncio
import json
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.clip_style import DEFAULT_BRAND, PALETTE, ClipStyle, parse_style
from app.config import settings
from app.database import Base, get_db
from app.main import register_routers
from app.models import Job
from app.routers import jobs as jobs_router
from app.services import quota

URL = "https://youtu.be/dQw4w9WgXcQ"


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "public_build", False)
    monkeypatch.setattr(settings, "clipmint_password", "")
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path / "storage"))
    settings.ensure_dirs()

    # O pipeline não roda: o que se testa aqui é o que a criação grava.
    async def parado(*_args, **_kwargs):
        return None

    monkeypatch.setattr(jobs_router, "run_pipeline", parado)

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'g.db'}")
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
    cliente.factory = factory
    return cliente


def _estilo_do_job(api, job_id) -> ClipStyle:
    async def ler():
        async with api.factory() as db:
            job = (await db.execute(select(Job).where(Job.id == job_id))).scalar_one()
            return job.style_json

    return parse_style(asyncio.run(ler()))


# ─── O destaque da legenda, por job ──────────────────────────────────────────

def test_sem_escolha_o_job_sem_perfil_usa_a_caixa_padrao(api):
    job = api.post("/api/jobs", json={"youtube_url": URL, "source_type": "podcast"}).json()
    assert _estilo_do_job(api, job["id"]).legenda.estilo == "caixa"


def test_job_sem_perfil_pode_pedir_o_destaque_por_cor(api):
    resp = api.post(
        "/api/jobs",
        json={"youtube_url": URL, "source_type": "podcast", "caption_style": "cor"},
    )
    assert resp.status_code == 201, resp.text
    estilo = _estilo_do_job(api, resp.json()["id"])
    assert estilo.legenda.estilo == "cor"
    # Só o destaque muda: a cor e o tamanho continuam os do estilo de origem.
    assert estilo.legenda.cor == DEFAULT_BRAND
    assert estilo.legenda.tamanho == "M"


def test_destaque_do_job_nao_muda_o_perfil(api):
    perfil = api.post(
        "/api/profiles",
        json={"name": "P", "source_type": "podcast", "style": {"legenda": {"estilo": "caixa"}}},
    ).json()
    job = api.post(
        "/api/jobs",
        json={"youtube_url": URL, "profile_id": perfil["id"], "caption_style": "cor"},
    ).json()

    assert _estilo_do_job(api, job["id"]).legenda.estilo == "cor"
    relido = api.get(f"/api/profiles/{perfil['id']}").json()
    assert relido["style"]["legenda"]["estilo"] == "caixa"


def test_destaque_do_job_preserva_o_resto_do_estilo_do_perfil(api):
    perfil = api.post(
        "/api/profiles",
        json={
            "name": "P",
            "source_type": "podcast",
            "style": {"marca": "#3EC8FF", "legenda": {"cor": "#FFD23F", "estilo": "cor"}},
        },
    ).json()
    job = api.post(
        "/api/jobs",
        json={"youtube_url": URL, "profile_id": perfil["id"], "caption_style": "caixa"},
    ).json()

    estilo = _estilo_do_job(api, job["id"])
    assert estilo.legenda.estilo == "caixa"
    assert estilo.legenda.cor == "#FFD23F"
    assert estilo.marca == "#3EC8FF"


def test_destaque_desconhecido_e_recusado(api):
    resp = api.post(
        "/api/jobs",
        json={"youtube_url": URL, "source_type": "podcast", "caption_style": "neon"},
    )
    assert resp.status_code == 422


# ─── O vídeo, antes de gerar ─────────────────────────────────────────────────

def test_metadados_do_video(api, monkeypatch):
    async def consulta(url: str) -> quota.Metadados:
        assert url == URL
        return quota.Metadados(
            duration=1834.0,
            ok=True,
            title="Episódio 42",
            channel="Canal",
            thumbnail_url="https://i.ytimg.com/vi/x/hq.jpg",
        )

    monkeypatch.setattr(quota, "probe", consulta)
    resp = api.get("/api/videos/metadata", params={"url": f"  {URL} "})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "ok": True,
        "title": "Episódio 42",
        "channel": "Canal",
        "duration_seconds": 1834.0,
        "thumbnail_url": "https://i.ytimg.com/vi/x/hq.jpg",
        "is_live": False,
    }


def test_metadados_quando_a_consulta_nao_responde(api, monkeypatch):
    """Falha de rede não é erro do vídeo: a tela avisa e gerar continua possível."""

    async def sem_resposta(url: str) -> quota.Metadados:
        return quota.Metadados()

    monkeypatch.setattr(quota, "probe", sem_resposta)
    corpo = api.get("/api/videos/metadata", params={"url": URL}).json()
    assert corpo["ok"] is False
    assert corpo["title"] is None
    assert corpo["duration_seconds"] is None


def test_metadados_recusam_link_que_nao_e_do_youtube(api, monkeypatch):
    async def nao_deveria(url: str):
        raise AssertionError("não devia consultar")

    monkeypatch.setattr(quota, "probe", nao_deveria)
    resp = api.get("/api/videos/metadata", params={"url": "https://vimeo.com/123"})
    assert resp.status_code == 422


# ─── O coral da marca ────────────────────────────────────────────────────────

def test_o_rosa_da_marca_e_o_coral_do_app():
    assert DEFAULT_BRAND == "#FF395E"
    assert PALETTE["rosa"] == "#FF395E"
    # E continua legível onde é usado: sobre o fundo do título e dentro da caixa.
    ClipStyle()


def test_migracao_leva_o_rosa_antigo_para_o_coral_e_so_ele(tmp_path, monkeypatch):
    from alembic import command

    from app import db_migrations

    caminho = tmp_path / "m.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{caminho}")

    async def ate(revisao):
        async with engine.begin() as conn:
            await conn.run_sync(
                lambda c: command.upgrade(db_migrations.alembic_config(c), revisao)
            )

    asyncio.run(ate("0016_estilo_do_clipe"))

    padrao_antigo = json.dumps({"marca": "#FD375C", "legenda": {"cor": "#FD375C"}})
    amarelo = json.dumps({"marca": "#FFD23F", "legenda": {"cor": "#FFD23F"}})
    raw = sqlite3.connect(caminho)
    colunas = raw.execute("PRAGMA table_info(profiles)").fetchall()
    # Preenche só o que o schema exige, para o teste não quebrar a cada coluna nova.
    obrigatorias = [c[1] for c in colunas if c[3] and c[4] is None and c[1] not in ("id", "style_json")]
    for pid, estilo in (("rosa", padrao_antigo), ("amarelo", amarelo), ("antigo", None)):
        nomes = ["id", "style_json", *obrigatorias]
        valores = [pid, estilo, *["x"] * len(obrigatorias)]
        raw.execute(
            f"INSERT INTO profiles ({', '.join(nomes)}) VALUES ({', '.join('?' * len(nomes))})",
            valores,
        )
    raw.commit()
    raw.close()

    asyncio.run(ate("0017_coral_da_marca"))
    asyncio.run(engine.dispose())

    raw = sqlite3.connect(caminho)
    estilos = dict(raw.execute("SELECT id, style_json FROM profiles").fetchall())
    raw.close()
    assert json.loads(estilos["rosa"]) == {"marca": "#FF395E", "legenda": {"cor": "#FF395E"}}
    assert estilos["amarelo"] == amarelo
    assert estilos["antigo"] is None
