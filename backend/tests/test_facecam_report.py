"""
O relato de enquadramento e a porta que ele destrava.

O corretor de facecam custa CPU: servir quadros de um vídeo de gigabytes e
re-renderizar o job inteiro. Sem porta, pedir correção em todo job sairia de
graça para quem pede e caro para quem hospeda.

O que estes testes guardam:

1. **A porta fecha.** Sem relato aprovado, nem o quadro sai nem o re-render
   começa — 403 nos dois.
2. **A triagem decide, e falha para o lado do cliente.** Visão dizendo "está
   bom" recusa; visão quebrada APROVA, porque derrubar o pedido de quem pagou
   por causa de um erro nosso é a troca errada.
3. **A caixa corrigida sobrevive ao retry.** Ela é gravada como `manual`, que é
   o que impede o `_was_auto_detected` de descartá-la e detectar de novo —
   voltando exatamente ao erro que o cliente relatou.
"""

import asyncio
import io

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base, get_db
from app.main import register_routers
from app.models import Clip, FacecamReport, Job, User
from app.services import facecam_review

PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)
CAIXA = {"x": 0.01, "y": 0.062, "w": 0.2156, "h": 0.2493}


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "public_build", True)
    monkeypatch.setattr(settings, "clipmint_password", "")
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path / "storage"))
    settings.ensure_dirs()

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'f.db'}")
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
    cliente.post(
        "/api/auth/register",
        json={"email": "cliente@exemplo.com", "password": "uma-frase-que-eu-lembro"},
    )
    return cliente, factory


@pytest.fixture
def visao(monkeypatch):
    """Controla o veredito da triagem. Padrão: confirma que está ruim."""
    estado = {"ruim": True, "motivo": "Aparece gameplay no painel de cima."}

    async def falsa(screenshot, media_type, descricao):
        return estado["ruim"], estado["motivo"]

    monkeypatch.setattr(facecam_review, "avaliar", falsa)
    return estado


def _job(factory, *, layout="streamer", clips=2) -> tuple[str, str]:
    """Um job pronto, com clipes. Devolve (job_id, primeiro_clip_id)."""

    async def montar():
        async with factory() as db:
            user = (await db.execute(select(User))).scalars().first()
            job = Job(
                id="j1",
                user_id=user.id,
                youtube_url="https://www.youtube.com/watch?v=abcdefghijk",
                status="done",
                layout_mode=layout,
                duration_seconds=600,
                video_path="storage/downloads/j1/video.mp4",
            )
            db.add(job)
            await db.flush()
            ids = []
            for i in range(clips):
                c = Clip(
                    job_id="j1",
                    start_time=100.0 + i * 60,
                    end_time=130.0 + i * 60,
                    duration=30.0,
                    virality_score=8.0,
                    status="ready",
                )
                db.add(c)
                await db.flush()
                ids.append(c.id)
            await db.commit()
            return "j1", ids[0]

    return asyncio.run(montar())


def _relatar(cliente, job_id, clip_id, texto="a cam está cortando a cabeça"):
    return cliente.post(
        f"/api/jobs/{job_id}/facecam-report",
        files={"file": ("print.png", io.BytesIO(PNG), "image/png")},
        data={"clip_id": clip_id, "description": texto},
    )


# ─── A porta ───────────────────────────────────────────────────────────────────

def test_sem_relato_o_corretor_esta_trancado(ambiente, visao):
    cliente, factory = ambiente
    job_id, _ = _job(factory)

    assert cliente.get(f"/api/jobs/{job_id}/frame?t=110").status_code == 403
    assert cliente.post(
        f"/api/jobs/{job_id}/facecam-fix", json={"facecam_rect": CAIXA}
    ).status_code == 403


def test_relato_recusado_nao_destrava(ambiente, visao):
    """A visão olhou e disse que está bom: a porta continua fechada."""
    cliente, factory = ambiente
    job_id, clip_id = _job(factory)
    visao["ruim"] = False
    visao["motivo"] = "O painel de cima mostra só a webcam, bem enquadrada."

    resp = _relatar(cliente, job_id, clip_id)
    assert resp.status_code == 201
    corpo = resp.json()
    assert corpo["status"] == "recusado"
    # O veredito volta para a tela: "recusado" sem explicação é uma parede.
    assert "webcam" in corpo["veredito"]

    assert cliente.post(
        f"/api/jobs/{job_id}/facecam-fix", json={"facecam_rect": CAIXA}
    ).status_code == 403


def test_relato_aprovado_destrava_e_traz_o_intervalo_do_clipe(ambiente, visao):
    cliente, factory = ambiente
    job_id, clip_id = _job(factory)

    corpo = _relatar(cliente, job_id, clip_id).json()
    assert corpo["status"] == "aprovado"
    # A linha do tempo do corretor varre o clipe, não o vídeo inteiro.
    assert corpo["clip_start"] == 100.0
    assert corpo["clip_end"] == 130.0

    resp = cliente.post(f"/api/jobs/{job_id}/facecam-fix", json={"facecam_rect": CAIXA})
    assert resp.status_code == 202, resp.text


# ─── A triagem falha para o lado do cliente ────────────────────────────────────

def test_visao_quebrada_aprova(ambiente, monkeypatch):
    """Erro nosso não pode virar 'não vou corrigir seu clipe'."""
    cliente, factory = ambiente
    job_id, clip_id = _job(factory)
    monkeypatch.setattr(settings, "anthropic_api_key", "")

    corpo = _relatar(cliente, job_id, clip_id).json()
    assert corpo["status"] == "aprovado"


# ─── A correção sobrevive ao retry ─────────────────────────────────────────────

def test_a_caixa_corrigida_e_manual_e_o_retry_nao_a_descarta(ambiente, visao):
    """Se não fosse `manual`, o retry detectaria de novo e voltaria ao erro."""
    from app.routers.jobs import _was_auto_detected

    cliente, factory = ambiente
    job_id, clip_id = _job(factory)
    _relatar(cliente, job_id, clip_id)
    cliente.post(f"/api/jobs/{job_id}/facecam-fix", json={"facecam_rect": CAIXA})

    async def guardado():
        async with factory() as db:
            job = await db.scalar(select(Job).where(Job.id == job_id))
            clips = (await db.execute(select(Clip))).scalars().all()
            return job.facecam_rect, job.status, [c.status for c in clips]

    bruto, status, status_clipes = asyncio.run(guardado())
    assert '"method": "manual"' in bruto
    assert not _was_auto_detected(bruto)
    assert status == "queued"
    # Todos voltam: a caixa vale para o job inteiro, e re-renderizar só o
    # relatado deixaria os outros com o enquadramento velho.
    assert status_clipes == ["processing", "processing"]


# ─── Bordas do relato ──────────────────────────────────────────────────────────

def test_layout_sem_facecam_recusa_o_relato(ambiente, visao):
    cliente, factory = ambiente
    job_id, clip_id = _job(factory, layout="cover")
    assert _relatar(cliente, job_id, clip_id).status_code == 422


def test_arquivo_que_nao_e_imagem_e_recusado(ambiente, visao):
    cliente, factory = ambiente
    job_id, clip_id = _job(factory)
    resp = cliente.post(
        f"/api/jobs/{job_id}/facecam-report",
        files={"file": ("nota.txt", io.BytesIO(b"oi"), "text/plain")},
        data={"clip_id": clip_id, "description": "está torto"},
    )
    assert resp.status_code == 422


def test_descricao_vazia_e_recusada(ambiente, visao):
    """Sem descrição a triagem não tem o que comparar com o print."""
    cliente, factory = ambiente
    job_id, clip_id = _job(factory)
    assert _relatar(cliente, job_id, clip_id, texto="ruim").status_code == 422


def test_job_de_outra_pessoa_nao_existe(ambiente, visao):
    cliente, factory = ambiente
    _job(factory)
    outro = TestClient(cliente.app)
    outro.post(
        "/api/auth/register",
        json={"email": "estranho@exemplo.com", "password": "outra-frase-comprida"},
    )
    resp = outro.post(
        "/api/jobs/j1/facecam-report",
        files={"file": ("print.png", io.BytesIO(PNG), "image/png")},
        data={"clip_id": "x", "description": "quero mexer no job alheio"},
    )
    assert resp.status_code == 404


def test_relato_fica_gravado_para_a_tela_reler(ambiente, visao):
    cliente, factory = ambiente
    job_id, clip_id = _job(factory)
    assert cliente.get(f"/api/jobs/{job_id}/facecam-report").json() is None

    _relatar(cliente, job_id, clip_id)
    lido = cliente.get(f"/api/jobs/{job_id}/facecam-report").json()
    assert lido["status"] == "aprovado"
    assert lido["description"] == "a cam está cortando a cabeça"

    async def salvo_em_disco() -> bool:
        from pathlib import Path

        async with factory() as db:
            r = (await db.execute(select(FacecamReport))).scalars().first()
            return Path(r.screenshot_path).exists()

    assert asyncio.run(salvo_em_disco())


def test_arquivo_que_mente_o_tipo_e_recusado(ambiente, visao):
    """`content_type` é escolhido por quem envia — quem prova são os bytes."""
    cliente, factory = ambiente
    job_id, clip_id = _job(factory)
    resp = cliente.post(
        f"/api/jobs/{job_id}/facecam-report",
        files={"file": ("print.png", io.BytesIO(b"<html>nao sou imagem</html>"), "image/png")},
        data={"clip_id": clip_id, "description": "olha o enquadramento"},
    )
    assert resp.status_code == 422
    assert "não é a imagem que diz ser" in resp.json()["detail"]
