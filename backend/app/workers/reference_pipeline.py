"""
Orquestrador do pipeline de aprendizado por referência.

Fluxo:
  queued → downloading_source → transcribing → aligning → analyzing → done
  (qualquer etapa pode ir para: error)

Dado a URL do vídeo original + o arquivo do clipe viral, este worker:
  1. Baixa o vídeo original (yt-dlp) e extrai seu áudio.
  2. Extrai o áudio do clipe enviado.
  3. Transcreve os dois (AssemblyAI, word-level).
  4. Alinha o clipe dentro do original → intervalo [source_start, source_end].
  5. Pede ao Claude a análise reversa de por que aquele corte viralizou.

O resultado NÃO é publicado como exemplo few-shot automaticamente — fica
aguardando confirmação do usuário (que pode ajustar o intervalo e informar a
performance real) via PATCH no router de referências.
"""

import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone

from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import ReferenceExample
from app.services.aligner import align_clip_to_source
from app.services.downloader import download_video
from app.services.reference_analyzer import analyze_reference
from app.services.transcriber import transcribe_audio
from app.utils.ffmpeg import run_ffmpeg

logger = logging.getLogger(__name__)


async def _update(reference_id: str, status: str, **kwargs) -> None:
    """Atualiza status e campos opcionais da referência no banco."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ReferenceExample).where(ReferenceExample.id == reference_id)
        )
        ref = result.scalar_one_or_none()
        if not ref:
            logger.error(f"[{reference_id}] Reference not found updating status '{status}'")
            return
        ref.status = status
        ref.updated_at = datetime.now(timezone.utc)
        for key, value in kwargs.items():
            setattr(ref, key, value)
        await db.commit()
        logger.info(f"[{reference_id}] Status → {status}")


async def _extract_clip_audio(reference_id: str, clip_path: str) -> str:
    """Extrai o áudio do clipe enviado para WAV mono 16kHz (para transcrição)."""
    audio_path = str(settings.references_dir / f"{reference_id}_clip.wav")
    await run_ffmpeg(
        "-i", clip_path,
        "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
        audio_path,
        description=f"Extract clip audio for reference {reference_id}",
    )
    return audio_path


def _opening_phrase(words: list[dict], start: float, max_words: int = 12) -> str:
    """Primeiras palavras a partir de `start`, parando no fim da primeira frase."""
    selected: list[str] = []
    for w in (x for x in words if x.get("start", 0) >= start):
        text = w.get("text", "")
        selected.append(text)
        if text.rstrip().endswith((".", "!", "?", "...")):
            break
        if len(selected) >= max_words:
            break
    return " ".join(selected).strip()


async def run_reference_pipeline(reference_id: str) -> None:
    """Executa o pipeline completo de ingestão de um exemplo de referência."""
    logger.info(f"[{reference_id}] Reference pipeline started")

    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(ReferenceExample).where(ReferenceExample.id == reference_id)
            )
            ref = result.scalar_one_or_none()
            if not ref:
                logger.error(f"[{reference_id}] Reference not found at pipeline start")
                return
            source_url = ref.source_url
            clip_path = ref.clip_path

        # ── 1. Download do vídeo original ──────────────────────────────────────
        await _update(reference_id, "downloading_source")
        metadata = await download_video(reference_id, source_url)

        # ── 2. Transcrições (original e clipe) ─────────────────────────────────
        await _update(
            reference_id,
            "transcribing",
            source_title=metadata.title,
            source_channel=metadata.channel,
            source_duration=metadata.duration,
        )

        clip_audio = await _extract_clip_audio(reference_id, clip_path)

        source_tr = await transcribe_audio(f"{reference_id}_src", metadata.audio_path)
        clip_tr = await transcribe_audio(f"{reference_id}_clip", clip_audio)

        source_words = [asdict(w) for w in source_tr.words]
        clip_words = [asdict(w) for w in clip_tr.words]

        # ── 3. Alinhamento clipe ↔ original ────────────────────────────────────
        await _update(reference_id, "aligning", language=source_tr.language)

        alignment = align_clip_to_source(clip_words, source_words)
        if alignment is None:
            raise RuntimeError(
                "Não foi possível localizar o clipe dentro do vídeo original. "
                "Verifique se o vídeo original está correto."
            )

        clip_duration = clip_tr.words[-1].end if clip_tr.words else (
            alignment.source_end - alignment.source_start
        )

        # ── 4. Análise reversa (Claude) ────────────────────────────────────────
        await _update(
            reference_id,
            "analyzing",
            source_start=alignment.source_start,
            source_end=alignment.source_end,
            alignment_confidence=alignment.confidence,
            clip_duration=clip_duration,
        )

        analysis = await analyze_reference(
            reference_id=reference_id,
            source_words=source_words,
            source_start=alignment.source_start,
            source_end=alignment.source_end,
            title=metadata.title,
            channel=metadata.channel,
            language=source_tr.language or "",
        )

        opening = _opening_phrase(source_words, alignment.source_start)
        excerpt_words = [
            w["text"] for w in source_words
            if w["start"] >= alignment.source_start and w["end"] <= alignment.source_end
        ]
        excerpt = " ".join(excerpt_words[:60])

        # ── 5. Finaliza ────────────────────────────────────────────────────────
        await _update(
            reference_id,
            "done",
            analysis_json=json.dumps(asdict(analysis), ensure_ascii=False),
            opening_phrase=opening,
            transcript_excerpt=excerpt,
        )
        logger.info(f"[{reference_id}] Reference pipeline complete!")

    except Exception as e:
        logger.error(f"[{reference_id}] Reference pipeline failed: {e}", exc_info=True)
        await _update(reference_id, "error", error_message=str(e))
