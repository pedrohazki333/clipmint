"""
Testes da seleção de clipes para o cronograma de postagem.

O cronograma posta 12 vezes por dia alternando as contas de podcast e gameplay,
e cada horário escolhe o clipe que lidera um eixo diferente da rubrica. Errar a
ordenação aqui posta o clipe errado — ou, pior, posta conteúdo de gameplay na
conta de podcast.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.main import app
from app.models import Clip, Job
from app.routers.schedule import POSTING_SLOTS


@pytest.fixture
def client(tmp_path):
    """App com um banco temporário povoado de clipes prontos."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'schedule.db'}")
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async def seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with factory() as db:
            db.add(Job(id="pod", youtube_url="u", source_type="podcast", status="done",
                       video_title="Podcast"))
            db.add(Job(id="game", youtube_url="u", source_type="gameplay", status="done",
                       video_title="Gameplay"))
            # Cada clipe lidera um eixo diferente, para flagrar ordenação trocada.
            db.add(Clip(
                id="pod-hook", job_id="pod", start_time=0, end_time=30, duration=30,
                virality_score=7.0, hook_score=10, retention_score=5,
                shareability_score=5, loopability_score=5, comment_bait_score=5,
                status="ready", file_path="a.mp4",
            ))
            db.add(Clip(
                id="pod-loop", job_id="pod", start_time=30, end_time=60, duration=30,
                virality_score=9.0, hook_score=4, retention_score=9,
                shareability_score=9, loopability_score=10, comment_bait_score=9,
                status="ready", file_path="b.mp4",
            ))
            # Não renderizado: nunca pode ser escolhido para postar.
            db.add(Clip(
                id="pod-processing", job_id="pod", start_time=60, end_time=90, duration=30,
                virality_score=10.0, hook_score=10, retention_score=10,
                shareability_score=10, loopability_score=10, comment_bait_score=10,
                status="processing",
            ))
            # Analisado antes da rubrica de 5 eixos: sem nota nos eixos.
            db.add(Clip(
                id="pod-legado", job_id="pod", start_time=90, end_time=120, duration=30,
                virality_score=9.9, status="ready", file_path="c.mp4",
            ))
            db.add(Clip(
                id="game-hook", job_id="game", start_time=0, end_time=30, duration=30,
                virality_score=8.0, hook_score=9, retention_score=8,
                shareability_score=8, loopability_score=8, comment_bait_score=8,
                status="ready", file_path="d.mp4",
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


def test_pick_orders_by_requested_axis(client):
    """07:00 pega o maior hook_score, 22:30 o maior loopability_score."""
    hook = client.get("/api/schedule/pick", params={"axis": "hook", "source": "podcast"})
    loop = client.get("/api/schedule/pick", params={"axis": "loopability", "source": "podcast"})

    assert hook.status_code == 200
    assert hook.json()[0]["clip_id"] == "pod-hook"
    assert hook.json()[0]["axis_score"] == 10
    # O mesmo conjunto de clipes, eixo diferente, vencedor diferente.
    assert loop.json()[0]["clip_id"] == "pod-loop"


def test_pick_never_crosses_accounts(client):
    """Clipe de gameplay não pode aparecer na fila da conta de podcast."""
    resp = client.get(
        "/api/schedule/pick", params={"axis": "hook", "source": "podcast", "limit": 50}
    )
    assert {c["clip_id"] for c in resp.json()} <= {"pod-hook", "pod-loop"}
    assert all(c["source_type"] == "podcast" for c in resp.json())

    game = client.get("/api/schedule/pick", params={"axis": "hook", "source": "gameplay"})
    assert game.json()[0]["clip_id"] == "game-hook"


def test_pick_skips_unrendered_and_unscored(client):
    """
    Só entra clipe pronto e pontuado naquele eixo.

    'pod-processing' tem nota 10 em tudo mas não tem arquivo; 'pod-legado' foi
    analisado antes da rubrica e ficaria no topo por falta de nota.
    """
    resp = client.get(
        "/api/schedule/pick", params={"axis": "hook", "source": "podcast", "limit": 50}
    )
    ids = {c["clip_id"] for c in resp.json()}
    assert "pod-processing" not in ids
    assert "pod-legado" not in ids


def test_pick_respects_exclude(client):
    """Clipe já postado sai da fila do dia seguinte."""
    resp = client.get(
        "/api/schedule/pick",
        params={"axis": "hook", "source": "podcast", "exclude": "pod-hook"},
    )
    assert resp.json()[0]["clip_id"] == "pod-loop"


def test_pick_overall_uses_final_score(client):
    """'Mais equilibrado' ordena pela nota final, não por um eixo."""
    resp = client.get("/api/schedule/pick", params={"axis": "overall", "source": "podcast"})
    assert resp.json()[0]["clip_id"] == "pod-loop"  # virality_score 9.0


def test_pick_rejects_unknown_axis(client):
    resp = client.get("/api/schedule/pick", params={"axis": "vibes", "source": "podcast"})
    assert resp.status_code == 422


def test_slots_cover_the_full_grid(client):
    """A grade tem 18 slots/dia, 6 para cada uma das três contas."""
    resp = client.get("/api/schedule/slots")
    slots = resp.json()

    assert len(slots) == 18
    assert len(POSTING_SLOTS) == 18
    for conta in ("podcast", "gameplay", "siege"):
        assert sum(1 for s in slots if s["source_type"] == conta) == 6, conta
    # Todo eixo da grade tem que ser um eixo que o /pick aceita
    for slot in slots:
        picked = client.get(
            "/api/schedule/pick", params={"axis": slot["axis"], "source": slot["source_type"]}
        )
        assert picked.status_code == 200, slot


def test_migration_backfills_source_type_from_layout(tmp_path):
    """
    Job de gameplay que existia antes da coluna não pode virar 'podcast'.

    O DEFAULT do ALTER TABLE preencheria tudo com 'podcast' e o cronograma
    passaria a postar corte de gameplay na conta de podcast.
    """
    import sqlite3

    from app.database import _add_missing_columns
    from sqlalchemy import create_engine

    db_file = tmp_path / "legado.db"
    raw = sqlite3.connect(db_file)
    raw.execute(
        "CREATE TABLE jobs (id VARCHAR PRIMARY KEY, youtube_url VARCHAR, "
        "layout_mode VARCHAR)"
    )
    raw.executemany(
        "INSERT INTO jobs (id, youtube_url, layout_mode) VALUES (?, ?, ?)",
        [("a", "u", "streamer"), ("b", "u", "cover"), ("c", "u", "streamer")],
    )
    raw.commit()
    raw.close()

    engine = create_engine(f"sqlite:///{db_file}")
    with engine.begin() as conn:
        _add_missing_columns(conn)
    engine.dispose()

    raw = sqlite3.connect(db_file)
    got = dict(raw.execute("SELECT id, source_type FROM jobs").fetchall())
    raw.close()

    assert got == {"a": "gameplay", "b": "podcast", "c": "gameplay"}
