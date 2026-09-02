"""
Provedor Deepgram (Nova-3) — a alternativa em avaliação.

Falado direto na API REST com httpx, sem o SDK oficial. São três motivos:

  1. httpx já é dependência do projeto; o SDK traria uma árvore nova só para
     chamar UM endpoint;
  2. o pré-gravado do Deepgram é um único POST — o SDK não esconde
     complexidade nenhuma aqui;
  3. os parâmetros ficam explícitos no código, inclusive o `multichannel=false`
     que existe para não pagar por dois canais.

O áudio é enviado em fluxo, lido do disco em pedaços. Um WAV mono 16 kHz de duas
horas tem ~230 MB: carregá-lo inteiro na memória para mandar seria o mesmo erro
que o upload de referência cometia (ver docs/DECISOES.md, D14).
"""

import logging
from pathlib import Path
from typing import AsyncIterator

import httpx

from app.config import settings
from app.services.transcription.base import (
    ProviderTranscript,
    TranscriptionProvider,
    WordTimestamp,
)

logger = logging.getLogger(__name__)

_ENDPOINT = "https://api.deepgram.com/v1/listen"

#: Pedaço lido do disco por vez ao enviar o áudio.
#:
#: Enviar em fluxo evita carregar centenas de MB na RAM, mas tem um custo que
#: vale saber: sem tamanho conhecido, o httpx manda `Transfer-Encoding: chunked`
#: e SEM `Content-Length`.
#:
#: A AssemblyAI RECUSA envio grande assim — 502 em 249 MB, medido em
#: 02/09/2026, e foi o que derrubou um job duas vezes (ver `_enviar_audio` em
#: assemblyai.py). A API do Deepgram é feita para receber fluxo, então aqui
#: deve estar certo — mas isto NUNCA foi testado com arquivo grande contra a
#: API real, porque o provedor ativo é o outro.
#:
#: Se um dia o Deepgram virar o padrão: teste com um áudio de 2h+ ANTES de
#: confiar. Se recusar, a saída é a mesma — enviar com `requests`, que deriva o
#: tamanho do arquivo e ainda assim lê em pedaços.
_CHUNK = 1024 * 1024


async def _stream_file(path: str) -> AsyncIterator[bytes]:
    with open(path, "rb") as handle:
        while pedaco := handle.read(_CHUNK):
            yield pedaco


class DeepgramProvider(TranscriptionProvider):
    name = "deepgram"

    def is_configured(self) -> bool:
        return bool(settings.deepgram_api_key)

    async def transcribe(self, job_id: str, audio_path: str) -> ProviderTranscript:
        self.require_configured()

        if not Path(audio_path).is_file():
            raise RuntimeError(f"Áudio não encontrado: {audio_path}")

        params = {
            "model": settings.deepgram_model,
            # Pontuação e formatação de números/datas — o equivalente ao
            # punctuate+format_text do AssemblyAI, para a comparação ser justa.
            "punctuate": "true",
            "smart_format": "true",
            # Um canal só: o áudio já é mono, e pedir multicanal cobraria por
            # canal. É a mesma precaução do outro provedor.
            "multichannel": "false",
        }
        if settings.deepgram_language:
            params["language"] = settings.deepgram_language
        else:
            params["detect_language"] = "true"

        headers = {
            "Authorization": f"Token {settings.deepgram_api_key}",
            "Content-Type": "audio/wav",
        }

        logger.info(
            f"[{job_id}] Deepgram: transcrevendo {audio_path} "
            f"(modelo {settings.deepgram_model})"
        )

        # Timeout generoso na leitura: transcrever uma hora de áudio leva
        # minutos, e o teto existe para a chamada pendurada, não para a lenta.
        timeout = httpx.Timeout(
            connect=30.0, read=settings.deepgram_timeout, write=None, pool=30.0
        )
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                _ENDPOINT,
                params=params,
                headers=headers,
                content=_stream_file(audio_path),
            )

        if response.status_code != 200:
            raise RuntimeError(
                f"Deepgram error (HTTP {response.status_code}): "
                f"{response.text[:500]}"
            )

        return self._parse(job_id, response.json())

    def _parse(self, job_id: str, payload: dict) -> ProviderTranscript:
        """Extrai texto e palavras da resposta.

        A resposta é aninhada em canais e alternativas; com `multichannel=false`
        e sem `alternatives>1` há exatamente um de cada, mas o acesso é
        defensivo porque um áudio sem fala nenhuma volta com a lista vazia — e
        isso é um caso real (vídeo só com música), não uma hipótese.
        """
        canais = payload.get("results", {}).get("channels", [])
        alternativas = canais[0].get("alternatives", []) if canais else []
        if not alternativas:
            logger.warning(f"[{job_id}] Deepgram não devolveu nenhuma alternativa")
            return ProviderTranscript(
                full_text="", words=[], language=None, model=settings.deepgram_model
            )

        melhor = alternativas[0]
        words = [
            WordTimestamp(
                # `punctuated_word` traz a palavra como ela aparece no texto
                # (maiúscula, vírgula); é ela que vai para a legenda. O `word`
                # cru viria sem pontuação e a legenda sairia sem respiro.
                text=w.get("punctuated_word") or w.get("word", ""),
                start=float(w.get("start", 0.0)),
                end=float(w.get("end", 0.0)),
                confidence=float(w.get("confidence", 0.0)),
            )
            for w in melhor.get("words", [])
        ]
        logger.info(f"[{job_id}] Deepgram: {len(words)} palavras")

        metadata = payload.get("metadata", {})
        return ProviderTranscript(
            full_text=melhor.get("transcript", ""),
            words=words,
            language=(
                canais[0].get("detected_language") or settings.deepgram_language or None
            ),
            model=settings.deepgram_model,
            extra={"billed_duration": metadata.get("duration")},
        )

    def estimate_cost_usd(self, duration_seconds: float) -> float:
        return (duration_seconds / 3600.0) * settings.deepgram_cost_per_hour
