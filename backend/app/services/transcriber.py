import asyncio
import json
import logging
from dataclasses import dataclass
from typing import List, Optional

import assemblyai as aai

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class WordTimestamp:
    text: str
    start: float  # seconds
    end: float    # seconds
    confidence: float


@dataclass
class TranscriptionResult:
    full_text: str
    words: List[WordTimestamp]
    words_json_path: str
    language: Optional[str]
    confidence: float


async def transcribe_audio(job_id: str, audio_path: str) -> TranscriptionResult:
    """
    Transcreve o áudio usando AssemblyAI com word-level timestamps.

    Salva o JSON de palavras com timestamps em disco para uso posterior
    na geração de legendas e análise de viralidade.
    """
    aai.settings.api_key = settings.assemblyai_api_key

    logger.info(f"[{job_id}] Starting transcription for: {audio_path}")

    config = aai.TranscriptionConfig(
        speech_model=aai.SpeechModel.best,
        language_detection=True,
        punctuate=True,
        format_text=True,
    )

    transcriber = aai.Transcriber(config=config)

    # AssemblyAI SDK é síncrono — executar em thread separada para não bloquear o event loop
    transcript = await asyncio.to_thread(transcriber.transcribe, audio_path)

    if transcript.status == aai.TranscriptStatus.error:
        raise RuntimeError(f"AssemblyAI error: {transcript.error}")

    logger.info(f"[{job_id}] Transcription complete. Words: {len(transcript.words or [])}")

    words: List[WordTimestamp] = []
    for w in (transcript.words or []):
        words.append(WordTimestamp(
            text=w.text,
            start=w.start / 1000.0,  # AssemblyAI retorna milissegundos
            end=w.end / 1000.0,
            confidence=w.confidence,
        ))

    # Persiste JSON de palavras para uso posterior
    words_json_path = str(settings.transcripts_dir / f"{job_id}_words.json")
    with open(words_json_path, "w", encoding="utf-8") as f:
        json.dump(
            [{"text": w.text, "start": w.start, "end": w.end, "confidence": w.confidence} for w in words],
            f,
            ensure_ascii=False,
            indent=2,
        )

    avg_confidence = (
        sum(w.confidence for w in words) / len(words) if words else 0.0
    )

    return TranscriptionResult(
        full_text=transcript.text or "",
        words=words,
        words_json_path=words_json_path,
        language=getattr(transcript, "language_code", None) or (transcript.json_response or {}).get("language_code"),
        confidence=avg_confidence,
    )
