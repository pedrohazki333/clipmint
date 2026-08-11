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
import os
import subprocess
import sys
from pathlib import Path

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


def _live_owner(job_id):
    """Processo vivo de verdade segurando o lock do job. Devolve (proc, lock)."""
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    lock = settings.locks_dir / f"{job_id}.pid"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(str(proc.pid), encoding="utf-8")
    return proc, lock


def test_held_refuses_second_process_on_same_job(tmp_path, monkeypatch):
    """
    Dois pipelines no mesmo job escrevem nos mesmos arquivos e corrompem o
    vídeo mesclado — o segundo tem que ser recusado.
    """
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path))

    proc, lock = _live_owner("job")
    try:
        with joblock.held("job"):
            raise AssertionError("não deveria ter assumido o lock")
    except joblock.JobAlreadyRunning as exc:
        assert exc.pid == proc.pid
    finally:
        proc.kill()
        proc.wait()

    # O lock do dono original continua de pé.
    assert lock.read_text(encoding="utf-8") == str(proc.pid)


def test_held_takes_over_stale_lock(tmp_path, monkeypatch):
    """Lock de processo morto não pode barrar um resume legítimo."""
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path))

    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()  # PID liberado

    lock = settings.locks_dir / "job.pid"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(str(proc.pid), encoding="utf-8")

    with joblock.held("job"):
        assert joblock.owner_pid("job") == os.getpid()

    assert not lock.exists()


def test_run_pipeline_gives_up_when_job_has_owner(tmp_path, monkeypatch):
    """run_pipeline não duplica trabalho nem toca no job de outro processo."""
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path))

    executed = []

    async def fake_execute(job_id, resume):
        executed.append(job_id)

    monkeypatch.setattr(pipeline, "_execute_pipeline", fake_execute)

    proc, _ = _live_owner("job")
    try:
        asyncio.run(pipeline.run_pipeline("job", resume=True))  # não levanta
    finally:
        proc.kill()
        proc.wait()

    assert executed == []


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

def _accept_media(monkeypatch, trustworthy=True):
    """Neutraliza a conferência de mídia — os arquivos do teste são vazios."""

    async def fake_ensure(job_id, video_path, audio_path, expected_duration=0.0):
        return trustworthy

    monkeypatch.setattr(pipeline, "ensure_media", fake_ensure)


def test_media_from_job_reuses_files_on_disk(tmp_path, monkeypatch):
    _accept_media(monkeypatch)
    saved = {
        "video_title": "Título",
        "channel_name": "Canal",
        "duration_seconds": 120.0,
        "thumbnail_url": "http://thumb",
        "video_path": _touch(tmp_path / "video.mp4"),
        "audio_path": _touch(tmp_path / "audio.wav"),
    }

    metadata = asyncio.run(pipeline._media_from_job("job", saved))

    assert metadata is not None
    assert metadata.title == "Título"
    assert metadata.duration == 120.0
    assert metadata.video_path == saved["video_path"]


def test_media_from_job_none_when_file_missing(tmp_path, monkeypatch):
    _accept_media(monkeypatch)
    saved = {
        "video_title": None, "channel_name": None,
        "duration_seconds": None, "thumbnail_url": None,
        "video_path": _touch(tmp_path / "video.mp4"),
        "audio_path": str(tmp_path / "sumiu.wav"),  # não existe
    }

    assert asyncio.run(pipeline._media_from_job("job", saved)) is None


def test_media_from_job_none_when_never_downloaded(monkeypatch):
    _accept_media(monkeypatch)
    saved = {
        "video_title": None, "channel_name": None,
        "duration_seconds": None, "thumbnail_url": None,
        "video_path": None, "audio_path": None,
    }

    assert asyncio.run(pipeline._media_from_job("job", saved)) is None


def test_media_from_job_rejects_corrupted_media(tmp_path, monkeypatch):
    """Arquivo em disco com áudio fora do vídeo não é reaproveitado."""
    _accept_media(monkeypatch, trustworthy=False)
    saved = {
        "video_title": "Título", "channel_name": "Canal",
        "duration_seconds": 9556.0, "thumbnail_url": None,
        "video_path": _touch(tmp_path / "video.mp4"),
        "audio_path": _touch(tmp_path / "audio.wav"),
    }

    assert asyncio.run(pipeline._media_from_job("job", saved)) is None


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


# ─── Descarte do que veio do vídeo antigo ─────────────────────────────────────

def test_discard_derived_work_clears_transcript_and_clips(tmp_path, monkeypatch):
    """
    Baixar o vídeo de novo invalida transcrição, análise e clips: os timestamps
    antigos apontam para outro momento do arquivo novo.
    """

    async def scenario():
        factory, engine = await _make_db(tmp_path)
        monkeypatch.setattr(pipeline, "AsyncSessionLocal", factory)
        monkeypatch.setattr(settings, "storage_dir", str(tmp_path))

        words_json = _touch(tmp_path / "words.json", "[]")
        clips_dir = settings.clips_dir / "job"
        clips_dir.mkdir(parents=True, exist_ok=True)
        (clips_dir / "clip.mp4").write_text("x", encoding="utf-8")

        async with factory() as db:
            db.add(
                Transcript(
                    id="t1", job_id="job", full_text="oi",
                    words_json_path=words_json,
                )
            )
            db.add(
                Clip(
                    id="c1", job_id="job", start_time=0, end_time=10,
                    duration=10, virality_score=8, status="ready",
                )
            )
            # Job vizinho não pode ser afetado
            db.add(
                Clip(
                    id="c2", job_id="outro", start_time=0, end_time=10,
                    duration=10, virality_score=8, status="ready",
                )
            )
            await db.commit()

        await pipeline._discard_derived_work("job")

        async with factory() as db:
            transcripts = (await db.execute(select(Transcript))).scalars().all()
            clips = (await db.execute(select(Clip))).scalars().all()

        assert transcripts == []
        assert [c.id for c in clips] == ["c2"]
        assert not Path(words_json).exists()
        assert not clips_dir.exists()

        await engine.dispose()

    asyncio.run(scenario())


def test_status_update_clears_stale_error(tmp_path, monkeypatch):
    """Resume que deu certo não pode deixar o job 'done' exibindo erro antigo."""

    async def scenario():
        factory, engine = await _make_db(tmp_path)
        monkeypatch.setattr(pipeline, "AsyncSessionLocal", factory)

        async with factory() as db:
            db.add(
                Job(
                    id="job", youtube_url="u", status="error",
                    error_message="Processamento interrompido",
                )
            )
            await db.commit()

        await pipeline._update_job_status("job", "done")

        async with factory() as db:
            job = (await db.execute(select(Job).where(Job.id == "job"))).scalar_one()
        assert job.status == "done"
        assert job.error_message is None

        # Ir para 'error' continua guardando a mensagem
        await pipeline._update_job_status("job", "error", error_message="boom")
        async with factory() as db:
            job = (await db.execute(select(Job).where(Job.id == "job"))).scalar_one()
        assert job.error_message == "boom"

        await engine.dispose()

    asyncio.run(scenario())
