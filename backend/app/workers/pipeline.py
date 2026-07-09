"""
Orquestrador do pipeline de processamento de vídeo.

Fluxo:
  queued → downloading → transcribing → analyzing → clipping → done
  (qualquer etapa pode ir para: error)

Cada etapa atualiza o status do job no banco de dados antes de executar.
O pipeline nunca crasha silenciosamente — erros são capturados e persistidos.
"""

import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import AsyncSessionLocal
from app.models import Job, Transcript, Clip
from app.services.downloader import download_video
from app.services.transcriber import transcribe_audio
from app.services.analyzer import analyze_virality
from app.services.clipper import cut_and_crop

logger = logging.getLogger(__name__)


async def _update_job_status(job_id: str, status: str, **kwargs) -> None:
    """Atualiza status e campos opcionais do job no banco."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Job).where(Job.id == job_id))
        job = result.scalar_one_or_none()
        if not job:
            logger.error(f"[{job_id}] Job not found when updating status to '{status}'")
            return
        job.status = status
        job.updated_at = datetime.now(timezone.utc)
        for key, value in kwargs.items():
            setattr(job, key, value)
        await db.commit()
        logger.info(f"[{job_id}] Status → {status}")


async def run_pipeline(job_id: str) -> None:
    """
    Executa o pipeline completo de processamento para um job.

    Etapas:
      1. Download do vídeo (yt-dlp)
      2. Transcrição (AssemblyAI)
      3. Análise de viralidade (Claude API)
      4. Corte e legendagem dos clips (FFmpeg)

    Atualiza o status do job a cada etapa. Em caso de erro,
    persiste a mensagem de erro e muda status para 'error'.
    """
    logger.info(f"[{job_id}] Pipeline started")

    try:
        # ── 1. Busca dados do job ─────────────────────────────────────────────
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Job).where(Job.id == job_id))
            job = result.scalar_one_or_none()
            if not job:
                logger.error(f"[{job_id}] Job not found at pipeline start")
                return
            youtube_url = job.youtube_url
            subtitle_mode = job.subtitle_mode

        # ── 2. Download ───────────────────────────────────────────────────────
        await _update_job_status(job_id, "downloading")
        metadata = await download_video(job_id, youtube_url)

        await _update_job_status(
            job_id,
            "transcribing",
            video_title=metadata.title,
            channel_name=metadata.channel,
            duration_seconds=metadata.duration,
            thumbnail_url=metadata.thumbnail_url,
            video_path=metadata.video_path,
            audio_path=metadata.audio_path,
        )

        # ── 3. Transcrição ────────────────────────────────────────────────────
        transcription = await transcribe_audio(job_id, metadata.audio_path)

        async with AsyncSessionLocal() as db:
            transcript_record = Transcript(
                job_id=job_id,
                full_text=transcription.full_text,
                words_json_path=transcription.words_json_path,
                language=transcription.language,
                confidence=transcription.confidence,
            )
            db.add(transcript_record)
            await db.commit()
            logger.info(f"[{job_id}] Transcript saved (id={transcript_record.id})")

        # ── 4. Análise de viralidade ──────────────────────────────────────────
        await _update_job_status(job_id, "analyzing")

        words = [asdict(w) for w in transcription.words]

        analysis = await analyze_virality(
            job_id=job_id,
            words=words,
            title=metadata.title,
            channel=metadata.channel,
            duration_seconds=metadata.duration,
        )

        logger.info(f"[{job_id}] Analysis complete: {len(analysis.clips)} clips to generate")

        if not analysis.clips:
            await _update_job_status(job_id, "done")
            logger.info(f"[{job_id}] No viral clips found. Pipeline complete.")
            return

        # ── 5. Corte dos clips ────────────────────────────────────────────────
        await _update_job_status(job_id, "clipping")

        # Cria registros de clip no banco com status 'processing'
        clip_records = []
        async with AsyncSessionLocal() as db:
            for vc in analysis.clips:
                # Extrai texto do trecho
                excerpt_words = [
                    w["text"] for w in words
                    if w["start"] >= vc.start and w["end"] <= vc.end
                ]
                excerpt = " ".join(excerpt_words[:50])  # max 50 palavras no excerpt

                clip = Clip(
                    job_id=job_id,
                    start_time=vc.start,
                    end_time=vc.end,
                    duration=vc.end - vc.start,
                    virality_score=vc.score,
                    hook=vc.hook,
                    reason=vc.reason,
                    tags_json=json.dumps(vc.tags),
                    suggested_title=vc.suggested_title,
                    transcript_excerpt=excerpt,
                    part_number=vc.part_number,
                    subtitle_mode=subtitle_mode,
                    status="processing",
                )
                db.add(clip)
                await db.flush()  # gera o ID
                clip_records.append((clip.id, vc))

            await db.commit()

        logger.info(f"[{job_id}] Created {len(clip_records)} clip records")

        # Processa cada clip
        for clip_id, vc in clip_records:
            try:
                file_path, file_size = await cut_and_crop(
                    job_id=job_id,
                    clip_id=clip_id,
                    video_path=metadata.video_path,
                    start_time=vc.start,
                    end_time=vc.end,
                    words=words,
                    subtitle_mode=subtitle_mode,
                )

                async with AsyncSessionLocal() as db:
                    result = await db.execute(select(Clip).where(Clip.id == clip_id))
                    clip = result.scalar_one()
                    clip.status = "ready"
                    clip.file_path = file_path
                    clip.file_size_bytes = file_size
                    await db.commit()

                logger.info(f"[{job_id}] Clip {clip_id} ready: {file_path}")

            except Exception as e:
                logger.error(f"[{job_id}] Failed to process clip {clip_id}: {e}", exc_info=True)
                async with AsyncSessionLocal() as db:
                    result = await db.execute(select(Clip).where(Clip.id == clip_id))
                    clip = result.scalar_one_or_none()
                    if clip:
                        clip.status = "error"
                        await db.commit()

        # ── 6. Finaliza ───────────────────────────────────────────────────────
        await _update_job_status(job_id, "done")
        logger.info(f"[{job_id}] Pipeline complete!")

    except Exception as e:
        logger.error(f"[{job_id}] Pipeline failed: {e}", exc_info=True)
        await _update_job_status(job_id, "error", error_message=str(e))
