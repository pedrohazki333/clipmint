"""
Provedor AssemblyAI — o padrão do projeto.

Continua sendo o padrão porque é o que está medido contra material real em
português: ver `assemblyai_speech_model` em config.py para o histórico de qual
modelo alucina em grito e qual trava em loop.
"""

import asyncio
import logging
import os

import assemblyai as aai
import requests

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

    @staticmethod
    def _enviar_audio(job_id: str, audio_path: str) -> str:
        """Envia o áudio e devolve a URL. Substitui o envio do próprio SDK.

        **Por que não deixar o SDK enviar.** Ele usa `httpx` passando o arquivo
        ABERTO como `content` (ver `api.upload_file`). O httpx não sabe o
        tamanho de um fluxo, então manda `Transfer-Encoding: chunked` e sem
        `Content-Length` — e a AssemblyAI recusa envio grande assim.

        Medido em 02/09/2026 com o mesmo arquivo de 249 MB:
          - httpx/SDK, chunked ......... 502 Bad Gateway (duas vezes, 15,5 min
            cada, gastando o retry interno do SDK antes de desistir)
          - urllib, chunked ............ 501 Not Implemented
          - requests, Content-Length ... 200 em 21 s

        O `requests` mede o arquivo com `os.fstat` e manda o tamanho, que é o
        que a API espera. Ele já é dependência do próprio SDK, então isto não
        acrescenta nada ao projeto.

        Sem streaming manual: o arquivo é lido em pedaços pelo `requests`, não
        carregado inteiro na memória — 345 MB de um vídeo de 3 h na RAM, vezes
        MAX_CONCURRENT_JOBS, derrubaria a máquina.
        """
        tamanho = os.path.getsize(audio_path)
        logger.info(
            f"[{job_id}] AssemblyAI: enviando {tamanho / 1e6:.0f} MB de áudio"
        )
        with open(audio_path, "rb") as f:
            resposta = requests.post(
                "https://api.assemblyai.com/v2/upload",
                headers={"authorization": settings.assemblyai_api_key},
                data=f,
                timeout=(30, settings.assemblyai_http_timeout),
            )
        if resposta.status_code != 200:
            # Mensagem com "assemblyai" e "upload" para `errors.py` traduzir —
            # a falha anterior chegou ao usuário como "erro inesperado".
            raise RuntimeError(
                f"AssemblyAI upload error: HTTP {resposta.status_code} "
                f"{resposta.text[:200]}"
            )
        return resposta.json()["upload_url"]

    async def transcribe(self, job_id: str, audio_path: str) -> ProviderTranscript:
        self.require_configured()
        aai.settings.api_key = settings.assemblyai_api_key
        # O padrão do SDK são 30 s, e valem para TODA requisição — inclusive
        # cada consulta do polling, que num vídeo longo dura minutos. Medido:
        # 249 MB levaram 21 s, nove segundos do teto. Não foi a causa da falha
        # de 02/09 (ver `_enviar_audio`), mas nove segundos de margem não é
        # margem, e com 3 h de áudio a folga desaparece.
        aai.settings.http_timeout = settings.assemblyai_http_timeout

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

        # Enviamos o áudio NÓS, e passamos a URL pronta ao SDK. O porquê está
        # em `_enviar_audio`.
        audio_url = await asyncio.to_thread(self._enviar_audio, job_id, audio_path)

        # O SDK é síncrono: roda em thread para não travar o event loop.
        transcript = await asyncio.to_thread(transcriber.transcribe, audio_url)

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
