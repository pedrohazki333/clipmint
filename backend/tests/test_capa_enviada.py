"""
A capa enviada pela pessoa no layout "Capa + faixa".

A imagem chega antes do job, fica em 1080 × 800 (recortada pelo centro, nunca
esticada) e, quando o job nasce, muda para a pasta dele. O render usa a enviada
e só escolhe a capa do clipe quando ela não existe.
"""

import asyncio
import io
import os
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base, get_db
from app.main import register_routers
from app.models import Job
from app.routers import jobs as jobs_router
from app.services import custom_cover

URL = "https://youtu.be/dQw4w9WgXcQ"


def _png(w: int, h: int, cor=(200, 30, 60)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), cor).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "public_build", False)
    monkeypatch.setattr(settings, "clipmint_password", "")
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path / "storage"))
    settings.ensure_dirs()

    async def parado(*_args, **_kwargs):
        return None

    monkeypatch.setattr(jobs_router, "run_pipeline", parado)

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'c.db'}")
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


def _job(api, job_id) -> Job:
    async def ler():
        async with api.factory() as db:
            return (await db.execute(select(Job).where(Job.id == job_id))).scalar_one()

    return asyncio.run(ler())


def _enviar(api, dados: bytes):
    return api.post("/api/covers", files={"file": ("capa.png", dados, "image/png")})


def test_a_capa_fica_em_1080x800_mesmo_em_outra_proporcao(api, tmp_path):
    r = _enviar(api, _png(1920, 1080))
    assert r.status_code == 201
    corpo = r.json()
    assert (corpo["width"], corpo["height"]) == (1920, 1080)

    salvos = list((tmp_path / "storage" / "uploads" / "covers").glob("*/*.png"))
    assert len(salvos) == 1
    assert Image.open(salvos[0]).size == (custom_cover.COVER_W, custom_cover.COVER_H) == (1080, 800)


def test_arquivo_que_nao_e_imagem_e_recusado(api):
    r = _enviar(api, b"isto nao e uma imagem")
    assert r.status_code == 422
    assert "imagem" in r.json()["detail"]


def test_o_job_leva_a_capa_para_a_pasta_dele(api):
    envio = _enviar(api, _png(1080, 800)).json()["id"]
    r = api.post(
        "/api/jobs",
        json={"youtube_url": URL, "source_type": "podcast", "layout_mode": "cover", "cover_upload_id": envio},
    )
    assert r.status_code == 201, r.text
    job = _job(api, r.json()["id"])
    assert job.cover_path
    caminho = Path(job.cover_path)
    assert caminho.exists()
    assert caminho.parent == settings.clips_dir / job.id

    # Um envio serve a um job só.
    r2 = api.post(
        "/api/jobs",
        json={"youtube_url": "https://youtu.be/aaaaaaaaaaa", "source_type": "podcast", "layout_mode": "cover", "cover_upload_id": envio},
    )
    assert r2.status_code == 422


def test_capa_em_outro_layout_e_recusada(api):
    envio = _enviar(api, _png(1080, 800)).json()["id"]
    r = api.post(
        "/api/jobs",
        json={"youtube_url": URL, "source_type": "podcast", "layout_mode": "fullscreen", "cover_upload_id": envio},
    )
    assert r.status_code == 422
    assert "Capa + faixa" in r.json()["detail"]


def test_id_de_envio_inventado_e_recusado(api):
    r = api.post(
        "/api/jobs",
        json={"youtube_url": URL, "source_type": "podcast", "layout_mode": "cover", "cover_upload_id": "../../x"},
    )
    assert r.status_code == 422


def test_sem_capa_o_job_fica_como_sempre(api):
    r = api.post("/api/jobs", json={"youtube_url": URL, "source_type": "podcast", "layout_mode": "cover"})
    assert r.status_code == 201
    assert _job(api, r.json()["id"]).cover_path is None


def test_envio_esquecido_some_depois_de_um_dia(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path / "storage"))
    velho = custom_cover.salvar_envio("u1", _png(100, 100))["id"]
    novo = custom_cover.salvar_envio("u1", _png(100, 100))["id"]
    pasta = tmp_path / "storage" / "uploads" / "covers" / "u1"
    antes = time.time() - custom_cover.VALIDADE_SEGUNDOS - 60
    os.utime(pasta / f"{velho}.png", (antes, antes))

    assert custom_cover.apagar_envios_vencidos() == 1
    assert not (pasta / f"{velho}.png").exists()
    assert (pasta / f"{novo}.png").exists()
