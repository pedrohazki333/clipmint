"""
Testes da recuperação de jobs interrompidos.

Cobrem as duas peças que sustentam o restart do servidor no meio de um job:
  - reconcile_interrupted_jobs(): destrava jobs órfãos no startup;
  - as decisões de resume (o que já está pronto e pode ser reaproveitado).

Não há pytest-asyncio no projeto, então cada teste roda seu próprio loop com
asyncio.run — engine e sessões são criados dentro dele para não vazar conexão
entre loops.
"""

import asyncio
import json
import subprocess
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base
from app.models import Clip, Job, Transcript
from app.workers import joblock, pipeline


# ─── Infra ────────────────────────────────────────────────────────────────────

async def _make_db(tmp_path):
    """Banco limpo em disco temporário. Devolve (session_factory, engine)."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    return factory, engine


def _touch(path, content: str = "x") -> str:
    path.write_text(content, encoding="utf-8")
    return str(path)


# ─── reconcile_interrupted_jobs ───────────────────────────────────────────────

def test_reconcile_marks_running_jobs_as_error(tmp_path, monkeypatch):
    """Job preso em 'clipping' vira erro; o 'done' não é tocado."""

    async def scenario():
        factory, engine = await _make_db(tmp_path)
        monkeypatch.setattr(pipeline, "AsyncSessionLocal", factory)

        async with factory() as db:
            db.add(Job(id="stuck", youtube_url="u", status="clipping"))
            db.add(Job(id="finished", youtube_url="u", status="done"))
            db.add(
                Clip(
                    id="c1", job_id="stuck", start_time=0, end_time=10,
                    duration=10, virality_score=8, status="processing",
                )
            )
            db.add(
                Clip(
                    id="c2", job_id="stuck", start_time=10, end_time=20,
                    duration=10, virality_score=8, status="ready",
                    file_path="whatever.mp4",
                )
            )
            await db.commit()

        reconciled = await pipeline.reconcile_interrupted_jobs()
        assert reconciled == ["stuck"]

        async with factory() as db:
            stuck = (await db.execute(select(Job).where(Job.id == "stuck"))).scalar_one()
            finished = (
                await db.execute(select(Job).where(Job.id == "finished"))
            ).scalar_one()
            clips = {
                c.id: c.status
                for c in (await db.execute(select(Clip))).scalars().all()
            }

        assert stuck.status == "error"
        assert "interrompido" in (stuck.error_message or "").lower()
        assert finished.status == "done"          # terminal não é mexido
        assert clips["c1"] == "error"             # órfão em processing
        assert clips["c2"] == "ready"             # já pronto, preservado

        await engine.dispose()

    asyncio.run(scenario())


def test_reconcile_spares_job_with_live_owner(tmp_path, monkeypatch):
    """
    Job sendo renderizado por outro processo (ex.: app.scripts.resume_job) não
    pode ser marcado como interrompido quando o servidor reinicia.
    """

    async def scenario():
        factory, engine = await _make_db(tmp_path)
        monkeypatch.setattr(pipeline, "AsyncSessionLocal", factory)
        monkeypatch.setattr(settings, "storage_dir", str(tmp_path))

        async with factory() as db:
            db.add(Job(id="rodando", youtube_url="u", status="clipping"))
            await db.commit()

        with joblock.held("rodando"):
            assert await pipeline.reconcile_interrupted_jobs() == []

        # Sem dono, o mesmo job é reconciliado normalmente
        assert await pipeline.reconcile_interrupted_jobs() == ["rodando"]

        await engine.dispose()

    asyncio.run(scenario())


def test_owner_pid_ignores_dead_process(tmp_path, monkeypatch):
    """Lock deixado por um processo que morreu não segura o job."""
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path))

    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()  # PID liberado

    lock = settings.locks_dir / "morto.pid"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(str(proc.pid), encoding="utf-8")

    assert joblock.owner_pid("morto") is None


def test_owner_pid_handles_missing_and_garbage_locks(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path))

    assert joblock.owner_pid("nunca-existiu") is None

    lock = settings.locks_dir / "lixo.pid"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("não é um pid", encoding="utf-8")
    assert joblock.owner_pid("lixo") is None


def test_held_releases_lock_on_error(tmp_path, monkeypatch):
    """O lock some mesmo quando o pipeline levanta exceção."""
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path))

    try:
        with joblock.held("job"):
            assert joblock.owner_pid("job") is not None
            raise RuntimeError("boom")
    except RuntimeError:
        pass

    assert joblock.owner_pid("job") is None
    assert not (settings.locks_dir / "job.pid").exists()


def test_reconcile_noop_without_running_jobs(tmp_path, monkeypatch):
    async def scenario():
        factory, engine = await _make_db(tmp_path)
        monkeypatch.setattr(pipeline, "AsyncSessionLocal", factory)

        async with factory() as db:
            db.add(Job(id="finished", youtube_url="u", status="done"))
            await db.commit()

        assert await pipeline.reconcile_interrupted_jobs() == []
        await engine.dispose()

    asyncio.run(scenario())


# ─── Reaproveitamento do download ─────────────────────────────────────────────

def test_media_from_job_reuses_files_on_disk(tmp_path):
    saved = {
        "video_title": "Título",
        "channel_name": "Canal",
        "duration_seconds": 120.0,
        "thumbnail_url": "http://thumb",
        "video_path": _touch(tmp_path / "video.mp4"),
        "audio_path": _touch(tmp_path / "audio.wav"),
    }

    metadata = pipeline._media_from_job(saved)

    assert metadata is not None
    assert metadata.title == "Título"
    assert metadata.duration == 120.0
    assert metadata.video_path == saved["video_path"]


def test_media_from_job_none_when_file_missing(tmp_path):
    saved = {
        "video_title": None, "channel_name": None,
        "duration_seconds": None, "thumbnail_url": None,
        "video_path": _touch(tmp_path / "video.mp4"),
        "audio_path": str(tmp_path / "sumiu.wav"),  # não existe
    }

    assert pipeline._media_from_job(saved) is None


def test_media_from_job_none_when_never_downloaded():
    saved = {
        "video_title": None, "channel_name": None,
        "duration_seconds": None, "thumbnail_url": None,
        "video_path": None, "audio_path": None,
    }

    assert pipeline._media_from_job(saved) is None


# ─── Reaproveitamento da transcrição ──────────────────────────────────────────

def test_words_from_disk(tmp_path, monkeypatch):
    """Transcrição salva é reaproveitada; JSON sumido força refazer."""

    async def scenario():
        factory, engine = await _make_db(tmp_path)
        monkeypatch.setattr(pipeline, "AsyncSessionLocal", factory)

        words = [{"text": "oi", "start": 0.0, "end": 0.3, "confidence": 0.9}]
        json_path = _touch(tmp_path / "words.json", json.dumps(words))

        async with factory() as db:
            db.add(
                Transcript(
                    id="t1", job_id="job", full_text="oi",
                    words_json_path=json_path,
                )
            )
            db.add(
                Transcript(
                    id="t2", job_id="perdido", full_text="oi",
                    words_json_path=str(tmp_path / "sumiu.json"),
                )
            )
            await db.commit()

        assert await pipeline._words_from_disk("job") == words
        assert await pipeline._words_from_disk("perdido") is None   # JSON ausente
        assert await pipeline._words_from_disk("inexistente") is None  # sem registro

        await engine.dispose()

    asyncio.run(scenario())


# ─── Reaproveitamento dos clips ───────────────────────────────────────────────

def test_tasks_from_db_only_counts_clips_with_file(tmp_path, monkeypatch):
    """
    'ready' só conta como renderizado se o arquivo existir — o clip que morreu
    no meio do render deixa um .mp4 parcial e precisa ser refeito.
    """

    async def scenario():
        factory, engine = await _make_db(tmp_path)
        monkeypatch.setattr(pipeline, "AsyncSessionLocal", factory)

        async with factory() as db:
            db.add(
                Clip(
                    id="ok", job_id="job", start_time=30, end_time=40,
                    duration=10, virality_score=8, status="ready",
                    file_path=_touch(tmp_path / "ok.mp4"), hook="Gancho",
                )
            )
            db.add(
                Clip(
                    id="sumiu", job_id="job", start_time=10, end_time=20,
                    duration=10, virality_score=8, status="ready",
                    file_path=str(tmp_path / "sumiu.mp4"),
                )
            )
            db.add(
                Clip(
                    id="pendente", job_id="job", start_time=0, end_time=10,
                    duration=10, virality_score=8, status="error",
                    suggested_title="Título",
                )
            )
            await db.commit()

        tasks = await pipeline._tasks_from_db("job")

        # Ordenados por start_time
        assert [t.clip_id for t in tasks] == ["pendente", "sumiu", "ok"]
        assert [t.rendered for t in tasks] == [False, False, True]
        # Banner: hook tem prioridade, senão o título sugerido
        assert tasks[0].banner_text == "Título"
        assert tasks[2].banner_text == "Gancho"

        assert await pipeline._tasks_from_db("outro-job") == []

        await engine.dispose()

    asyncio.run(scenario())
