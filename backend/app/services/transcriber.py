"""
Fachada da transcrição.

O pipeline chama `transcribe_audio(job_id, audio_path)` e não sabe — nem
precisa saber — qual serviço respondeu. Quem responde é o provedor escolhido em
`TRANSCRIPTION_PROVIDER` (ver services/transcription/).

O que a fachada faz por cima do provedor, e por que fica aqui e não lá:

  - **limpa repetições degeneradas**: é defeito de decodificador, aparece em
    qualquer fornecedor, e deixá-lo em um provedor só faria a comparação entre
    eles medir o pós-processamento em vez do modelo;
  - **grava o JSON de palavras**: é artefato do pipeline (legenda e análise leem
    dele), não do fornecedor.
"""

import json
import logging
from typing import Optional

from app.config import settings
from app.services.transcription import get_provider
from app.services.transcription.base import (  # noqa: F401 - reexport
    ProviderTranscript,
    TranscriptionResult,
    WordTimestamp,
)
from app.services.transcription.postprocess import drop_degenerate_repeats

logger = logging.getLogger(__name__)


async def transcribe_audio(
    job_id: str,
    audio_path: str,
    provider_name: Optional[str] = None,
    words_json_path: Optional[str] = None,
) -> TranscriptionResult:
    """
    Transcreve o áudio com timestamps por palavra.

    Args:
        job_id: identifica o trabalho nos logs e nomeia o JSON de palavras.
        audio_path: WAV mono 16 kHz extraído pelo downloader.
        provider_name: força um provedor específico. Usado pelo modo de
            comparação; no pipeline normal vem None e vale o do .env.
        words_json_path: destino do JSON. Omitido, usa o nome padrão do job —
            a comparação precisa disso para os dois provedores não escreverem
            no mesmo arquivo.
    """
    provider = get_provider(provider_name)
    logger.info(f"[{job_id}] Transcrição via '{provider.name}'")

    resultado = await provider.transcribe(job_id, audio_path)

    words, dropped = drop_degenerate_repeats(resultado.words)
    if dropped:
        logger.warning(
            f"[{job_id}] {dropped} repetição(ões) degenerada(s) descartada(s) "
            f"— o modelo travou em loop em algum trecho difícil"
        )

    destino = words_json_path or str(settings.transcripts_dir / f"{job_id}_words.json")
    with open(destino, "w", encoding="utf-8") as f:
        json.dump(
            [
                {"text": w.text, "start": w.start, "end": w.end, "confidence": w.confidence}
                for w in words
            ],
            f,
            ensure_ascii=False,
            indent=2,
        )

    avg_confidence = (
        sum(w.confidence for w in words) / len(words) if words else 0.0
    )

    return TranscriptionResult(
        full_text=resultado.full_text,
        words=words,
        words_json_path=destino,
        language=resultado.language,
        confidence=avg_confidence,
        provider=provider.name,
        model=resultado.model,
    )
