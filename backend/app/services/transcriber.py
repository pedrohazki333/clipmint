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


#: Duração máxima de uma palavra para ela ser considerada "sem tempo próprio".
#: Fala real, mesmo rápida, não cabe em 20ms.
_DEGENERATE_MAX_DURATION = 0.02

#: Teto de repetições consecutivas da mesma palavra. Alguém grita "não, não,
#: não" — não 121 vezes seguidas. Acima disso a legenda fica ilegível e o
#: analisador lê a repetição como bordão, então o excedente cai mesmo que
#: cada cópia tenha duração própria.
_MAX_CONSECUTIVE_REPEATS = 6


def _drop_degenerate_repeats(words: List[WordTimestamp]) -> tuple[List[WordTimestamp], int]:
    """
    Remove repetições que o decodificador cospe em loop num trecho difícil.

    Em grito distorcido com vozes sobrepostas o modelo às vezes trava numa
    palavra e emite dezenas de cópias empilhadas no mesmo instante — 121x
    "não" em 20s, todas com confiança ~1.0. Vira legenda ilegível e engana o
    analisador, que lê a repetição como bordão.

    Dois sinais denunciam a cópia. O primeiro é não ocupar tempo nenhum —
    fala real tem duração própria. O segundo é o tamanho da sequência: parte
    das cópias vem com alguns centésimos de duração e escapa do primeiro
    filtro, então a repetição consecutiva também tem teto.

    Do excedente, ficam as cópias mais longas: são as que têm mais chance de
    corresponder a uma palavra realmente pronunciada.
    """
    kept: List[WordTimestamp] = []
    dropped = 0

    def flush(run: List[WordTimestamp]) -> None:
        nonlocal dropped
        if len(run) <= _MAX_CONSECUTIVE_REPEATS:
            kept.extend(run)
            return
        longest = sorted(run, key=lambda w: w.end - w.start, reverse=True)
        survivors = set(id(w) for w in longest[:_MAX_CONSECUTIVE_REPEATS])
        dropped += len(run) - _MAX_CONSECUTIVE_REPEATS
        kept.extend(w for w in run if id(w) in survivors)  # mantém a ordem

    run: List[WordTimestamp] = []
    for w in words:
        same = run and run[-1].text.strip().lower() == w.text.strip().lower()
        if same and (w.end - w.start) <= _DEGENERATE_MAX_DURATION:
            dropped += 1  # cópia empilhada no mesmo instante
            continue
        if same:
            run.append(w)
            continue
        flush(run)
        run = [w]
    flush(run)
    return kept, dropped


async def transcribe_audio(job_id: str, audio_path: str) -> TranscriptionResult:
    """
    Transcreve o áudio usando AssemblyAI com word-level timestamps.

    Salva o JSON de palavras com timestamps em disco para uso posterior
    na geração de legendas e análise de viralidade.
    """
    aai.settings.api_key = settings.assemblyai_api_key

    logger.info(f"[{job_id}] Starting transcription for: {audio_path}")

    # `speech_model` (singular) foi descontinuado pela API — hoje é `speech_models`,
    # uma lista de strings. Ver `assemblyai_speech_model` em config.py para o
    # porquê da escolha do modelo.
    config = aai.TranscriptionConfig(
        speech_models=[settings.assemblyai_speech_model],
        punctuate=True,
        format_text=True,
    )
    if settings.assemblyai_language:
        config.language_code = settings.assemblyai_language
    else:
        config.language_detection = True

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

    words, dropped = _drop_degenerate_repeats(words)
    if dropped:
        logger.warning(
            f"[{job_id}] {dropped} repetição(ões) degenerada(s) descartada(s) "
            f"— o modelo travou em loop em algum trecho difícil"
        )

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
