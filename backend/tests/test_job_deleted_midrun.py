"""
Apagar um job em andamento tem que PARAR o pipeline.

Excluir job em execução é permitido de propósito — é a saída para um job
travado. O problema era o pipeline não perceber: ele seguia até o fim,
recriava no disco os diretórios que o DELETE tinha acabado de apagar e inseria
linhas de Clip apontando para um job inexistente (o SQLite não aplica as FKs,
então nada recusava). Sobravam linhas órfãs e GB de vídeo sem dono.

Auditoria de 25/08/2026: 9 transcrições órfãs e 0,32 GB de clips sem job no
banco de desenvolvimento, exatamente o rastro que este caminho deixa.
"""

import asyncio

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base
from app.models import Clip, Job, Transcript
from app.workers import pipeline


@pytest.fixture
def db_temporario(tmp_path, monkeypatch):
    """Banco e storage isolados, com o pipeline apontado para eles."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'mid.db'}")
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async def criar():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(criar())
    monkeypatch.setattr(pipeline, "AsyncSessionLocal", factory)
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path / "storage"))
    settings.ensure_dirs()
    return factory


def test_status_avisa_quando_o_job_sumiu(db_temporario):
    """_update_job_status levanta em vez de logar e seguir em frente."""

    async def cenario():
        with pytest.raises(pipeline.JobDeleted):
            await pipeline._update_job_status("nao-existe", "clipping")

    asyncio.run(cenario())


def test_abort_if_deleted_passa_com_job_vivo(db_temporario):
    async def cenario():
        async with db_temporario() as db:
            db.add(Job(id="vivo", youtube_url="u", status="clipping"))
            await db.commit()
        await pipeline._abort_if_deleted("vivo")  # não levanta

    asyncio.run(cenario())


def test_laco_de_render_para_no_primeiro_clip_apos_o_delete(db_temporario, monkeypatch):
    """
    O caso real: o job é apagado enquanto o clip 1 de 3 renderiza.

    Sem a checagem, os três eram renderizados e o job "concluía" — recriando o
    diretório de clips que o DELETE tinha apagado.
    """
    renderizados: list[str] = []

    async def falso_render(**kwargs):
        renderizados.append(kwargs["clip_id"])
        # Simula o usuário apagando o job no meio do primeiro render.
        async with db_temporario() as db:
            await db.execute(Job.__table__.delete().where(Job.id == "job-x"))
            await db.commit()
        return "/tmp/fake.mp4", 123

    monkeypatch.setattr(pipeline, "cut_and_crop", falso_render)

    async def cenario():
        async with db_temporario() as db:
            db.add(Job(id="job-x", youtube_url="u", status="queued",
                       video_title="t", channel_name="c", duration_seconds=600,
                       video_path=str(tmp_video()), audio_path=str(tmp_audio())))
            db.add(Transcript(job_id="job-x", full_text="oi",
                              words_json_path=str(tmp_words())))
            for i in range(3):
                db.add(Clip(id=f"c{i}", job_id="job-x", start_time=i * 30,
                            end_time=i * 30 + 20, duration=20, virality_score=8.0,
                            status="error"))
            await db.commit()

        # resume=True: reaproveita mídia e transcrição, vai direto ao render.
        await pipeline._execute_pipeline("job-x", resume=True)

        async with db_temporario() as db:
            sobrou = (await db.execute(select(Clip).where(Clip.job_id == "job-x"))).scalars().all()
        return sobrou

    # Arquivos mínimos para o resume aceitar a mídia em disco
    import pathlib
    base = pathlib.Path(settings.storage_dir)

    def tmp_video():
        p = base / "downloads" / "job-x" / "video.mp4"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
        return p

    def tmp_audio():
        p = base / "downloads" / "job-x" / "audio.wav"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
        return p

    def tmp_words():
        p = base / "transcripts" / "job-x_words.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('[{"text":"oi","start":0,"end":1,"confidence":0.9}]', encoding="utf-8")
        return p

    # A mídia falsa não passa pela conferência de integridade, então o resume
    # tentaria baixar de novo. Aqui o que interessa é o laço de render.
    async def media_ok(job_id, saved):
        from app.services.downloader import VideoMetadata
        return VideoMetadata(
            title="t", channel="c", duration=600.0, thumbnail_url=None,
            video_path=saved["video_path"], audio_path=saved["audio_path"],
        )

    monkeypatch.setattr(pipeline, "_media_from_job", media_ok)

    asyncio.run(cenario())

    assert len(renderizados) == 1, (
        f"o laço renderizou {len(renderizados)} clips depois do DELETE — "
        f"deveria ter parado no primeiro"
    )


def test_storage_do_job_excluido_e_limpo(db_temporario):
    """O que o pipeline recriou depois do DELETE tem que sair do disco."""
    import pathlib

    base = pathlib.Path(settings.storage_dir)
    downloads = base / "downloads" / "orfao"
    clips = base / "clips" / "orfao"
    words = base / "transcripts" / "orfao_words.json"
    for d in (downloads, clips):
        d.mkdir(parents=True, exist_ok=True)
        (d / "arquivo.mp4").write_bytes(b"conteudo")
    words.parent.mkdir(parents=True, exist_ok=True)
    words.write_text("[]", encoding="utf-8")

    pipeline._discard_storage("orfao")

    assert not downloads.exists()
    assert not clips.exists()
    assert not words.exists()
