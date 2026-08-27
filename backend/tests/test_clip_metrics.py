"""
Testes do registro de desempenho real dos clipes.

A nota de viralidade é uma previsão feita antes de o clipe existir. Estes
campos são o que aconteceu depois de postar — e são a única forma de o sistema
descobrir que um clipe de nota 8.4 rendeu mal. Nenhuma análise de texto, áudio
ou imagem consegue saber isso sozinha, porque viralidade não está no vídeo.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.main import app
from app.models import Clip, Job


@pytest.fixture
def client(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'metrics.db'}")
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async def seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with factory() as db:
            db.add(Job(id="j", youtube_url="u", source_type="gameplay", status="done"))
            db.add(Clip(
                id="c1", job_id="j", start_time=3028.1, end_time=3083.3, duration=55.2,
                virality_score=8.4, status="ready", file_path="fall.mp4",
            ))
            await db.commit()

    asyncio.run(seed())

    async def override_get_db():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    asyncio.run(engine.dispose())


def test_registra_desempenho(client):
    r = client.put("/api/clips/c1/metrics", json={"views": 14200, "completion_rate": 0.62})
    assert r.status_code == 200

    body = r.json()
    assert body["views"] == 14200
    assert body["completion_rate"] == pytest.approx(0.62)
    # Views sem data de coleta não são comparáveis entre clipes de idades
    # diferentes, então o carimbo não é opcional.
    assert body["metrics_at"] is not None


def test_atualizacao_e_parcial(client):
    """Lançar as views hoje e a retenção amanhã não pode apagar as views."""
    client.put("/api/clips/c1/metrics", json={"views": 14200})
    r = client.put("/api/clips/c1/metrics", json={"completion_rate": 0.62})

    body = r.json()
    assert body["views"] == 14200
    assert body["completion_rate"] == pytest.approx(0.62)


def test_recusa_corpo_vazio(client):
    assert client.put("/api/clips/c1/metrics", json={}).status_code == 400


def test_recusa_retencao_fora_da_faixa(client):
    """completion_rate é fração, não porcentagem — 62 seria 6200%."""
    assert client.put("/api/clips/c1/metrics", json={"completion_rate": 62}).status_code == 422


def test_recusa_numero_negativo(client):
    assert client.put("/api/clips/c1/metrics", json={"views": -5}).status_code == 422


def test_clip_inexistente(client):
    assert client.put("/api/clips/nao-existe/metrics", json={"views": 1}).status_code == 404


def test_clip_novo_nasce_sem_metricas(client):
    """Nulo significa 'ainda não medido', que não é a mesma coisa que zero."""
    body = client.get("/api/clips/c1").json()
    assert body["views"] is None
    assert body["completion_rate"] is None
    assert body["metrics_at"] is None
