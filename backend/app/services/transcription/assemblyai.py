"""
Provedor AssemblyAI — o padrão do projeto.

Continua sendo o padrão porque é o que está medido contra material real em
português: ver `assemblyai_speech_model` em config.py para o histórico de qual
modelo alucina em grito e qual trava em loop.
"""

import asyncio
import logging

import assemblyai as aai

from app.config import settings
from app.services.transcription.base import (
    ProviderTranscript,
    TranscriptionProvider,
    WordTimestamp,
)

logger = logging.getLogger(__name__)


class AssemblyAIProvider(TranscriptionProvider):
    name = "assemblyai"

    def is_configured(self) -> bool:
        return bool(settings.assemblyai_api_key)

    async def transcribe(self, job_id: str, audio_path: str) -> ProviderTranscript:
        self.require_configured()
        aai.settings.api_key = settings.assemblyai_api_key

        logger.info(f"[{job_id}] AssemblyAI: transcrevendo {audio_path}")

        # `speech_model` (singular) foi descontinuado pela API — hoje é
        # `speech_models`, uma lista de strings.
        config = aai.TranscriptionConfig(
            speech_models=[settings.assemblyai_speech_model],
            punctuate=True,
            format_text=True,
            # Um canal só. O áudio já sai mono do FFmpeg (-ac 1 em
            # services/downloader.py), então na prática nunca houve cobrança em
            # dobro; explicitar aqui é para o dia em que a origem do áudio
            # mudar e a conta subir sem ninguém entender por quê.
            multichannel=False,
        )
        if settings.assemblyai_language:
            config.language_code = settings.assemblyai_language
        else:
            config.language_detection = True

        transcriber = aai.Transcriber(config=config)

        # O SDK é síncrono: roda em thread para não travar o event loop.
        transcript = await asyncio.to_thread(transcriber.transcribe, audio_path)

        if transcript.status == aai.TranscriptStatus.error:
            raise RuntimeError(f"AssemblyAI error: {transcript.error}")

        words = [
            WordTimestamp(
                text=w.text,
                start=w.start / 1000.0,  # a API devolve milissegundos
                end=w.end / 1000.0,
                confidence=w.confidence,
            )
            for w in (transcript.words or [])
        ]
        logger.info(f"[{job_id}] AssemblyAI: {len(words)} palavras")

        language = getattr(transcript, "language_code", None) or (
            transcript.json_response or {}
        ).get("language_code")

        return ProviderTranscript(
            full_text=transcript.text or "",
            words=words,
            language=language,
            model=settings.assemblyai_speech_model,
        )

    def estimate_cost_usd(self, duration_seconds: float) -> float:
        return (duration_seconds / 3600.0) * settings.assemblyai_cost_per_hour
