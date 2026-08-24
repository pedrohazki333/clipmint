"""
Orquestradores do aprendizado por referência — os dois modos.

MODO ALINHADO (`run_reference_pipeline`), quando se tem a URL do original:
  queued → downloading_source → transcribing → aligning → analyzing → done

  1. Baixa o vídeo original (yt-dlp) e extrai seu áudio.
  2. Extrai o áudio do clipe enviado.
  3. Transcreve os dois (AssemblyAI, word-level).
  4. Alinha o clipe dentro do original → intervalo [source_start, source_end].
  5. Pede ao Claude a análise reversa de por que aquele corte viralizou.

MODO SOLTO (`run_standalone_pipeline`), quando só existe o arquivo do clipe:
  queued → extracting → transcribing → watching → analyzing → done

  1. Mede a duração e extrai o áudio do clipe.
  2. Transcreve (AssemblyAI, word-level).
  3. Pericia o clipe: quadros lidos pela visão, curva de loudness e cortes de
     cena (services/clip_forensics.py).
  4. Pede ao Claude a síntese das quatro evidências.

  Sem o original não há o que alinhar, então `source_start`/`source_end` são
  preenchidos com 0 e a duração do clipe: o corte É o clipe inteiro. Isso não é
  um remendo para o schema — é o fato do modo — e faz o confirm() publicar o
  exemplo sem precisar saber de qual pipeline ele veio.

Em nenhum dos dois o resultado vira exemplo few-shot sozinho: fica aguardando
confirmação do usuário (que informa a performance real) via PATCH e POST
/confirm no router de referências.

Qualquer etapa dos dois pode ir para: error.
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
from app.services.clip_forensics import gather_evidence
from app.services.reference_analyzer import analyze_reference, analyze_standalone_clip
from app.services.transcriber import transcribe_audio
from app.utils.ffmpeg import get_duration, run_ffmpeg

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


async def run_standalone_pipeline(reference_id: str) -> None:
    """Executa a perícia de um clipe viral que chegou sem o vídeo de origem."""
    logger.info(f"[{reference_id}] Standalone reference pipeline started")

    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(ReferenceExample).where(ReferenceExample.id == reference_id)
            )
            ref = result.scalar_one_or_none()
            if not ref:
                logger.error(f"[{reference_id}] Reference not found at pipeline start")
                return
            clip_path = ref.clip_path
            title = ref.source_title or ""
            channel = ref.source_channel or ""
            source_type = ref.source_type or "podcast"
            notas = ref.notas or ""

        # ── 1. Duração e áudio ─────────────────────────────────────────────────
        await _update(reference_id, "extracting")
        duration = await get_duration(clip_path)
        clip_audio = await _extract_clip_audio(reference_id, clip_path)

        # ── 2. Transcrição ─────────────────────────────────────────────────────
        await _update(reference_id, "transcribing", clip_duration=duration)
        transcription = await transcribe_audio(f"{reference_id}_clip", clip_audio)
        words = [asdict(w) for w in transcription.words]

        # ── 3. Perícia: imagem, som e cortes ───────────────────────────────────
        await _update(reference_id, "watching", language=transcription.language)
        evidence = await gather_evidence(
            reference_id=reference_id,
            clip_path=clip_path,
            audio_path=clip_audio,
            words=words,
            duration=duration,
        )

        # ── 4. Síntese ─────────────────────────────────────────────────────────
        await _update(reference_id, "analyzing")
        analysis, forensics = await analyze_standalone_clip(
            reference_id=reference_id,
            evidence=evidence,
            title=title,
            channel=channel,
            source_type=source_type,
            language=transcription.language or "",
            notas=notas,
        )

        # ── 5. Finaliza ────────────────────────────────────────────────────────
        # O corte é o clipe inteiro: não há original de onde ele tenha sido
        # recortado, então o intervalo vai de 0 à duração.
        await _update(
            reference_id,
            "done",
            source_start=0.0,
            source_end=duration,
            analysis_json=json.dumps(asdict(analysis), ensure_ascii=False),
            forensics_json=json.dumps(forensics, ensure_ascii=False),
            opening_phrase=_opening_phrase(words, 0.0),
            transcript_excerpt=" ".join(w["text"] for w in words[:60]),
        )
        logger.info(f"[{reference_id}] Standalone reference pipeline complete!")

    except Exception as e:
        logger.error(
            f"[{reference_id}] Standalone reference pipeline failed: {e}", exc_info=True
        )
        await _update(reference_id, "error", error_message=str(e))
