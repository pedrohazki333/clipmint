"""
Análise reversa de clipe de referência via Claude API.

Recebe o trecho já localizado dentro do vídeo original (via aligner) mais o
contexto ao redor e pede ao Claude a explicação de por que aquele corte
viralizou — gerando hook/título/score/reason/tags no mesmo vocabulário usado
pelo analyzer, para que o resultado sirva de exemplo few-shot.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import List

import anthropic

from app.config import settings
from app.prompts.reference_analysis import build_reference_prompt

logger = logging.getLogger(__name__)

# Segundos de contexto ao redor do corte enviados ao modelo (o que foi deixado de fora).
_CONTEXT_WINDOW = 30.0


@dataclass
class ReferenceAnalysis:
    hook: str
    suggested_title: str
    virality_score: float
    reason: str
    tags: List[str] = field(default_factory=list)
    why_this_cut: str = ""


def _slice_words(words: List[dict], start: float, end: float) -> List[dict]:
    """Palavras cujo intervalo cai dentro de [start, end]."""
    return [w for w in words if w.get("start", 0) >= start and w.get("end", 0) <= end]


def _parse_response(raw: str) -> dict:
    """Extrai o JSON da resposta do Claude, tolerando cerca de código markdown."""
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    return json.loads(raw)


async def analyze_reference(
    reference_id: str,
    source_words: List[dict],
    source_start: float,
    source_end: float,
    title: str,
    channel: str,
    language: str,
) -> ReferenceAnalysis:
    """
    Faz a análise reversa do trecho localizado e retorna a estrutura de exemplo.

    Args:
        reference_id: ID da referência (para logging).
        source_words: palavras (text/start/end) do vídeo original.
        source_start / source_end: intervalo do corte no original.
        title / channel / language: metadados do vídeo original.
    """
    clip_words = _slice_words(source_words, source_start, source_end)
    before_words = _slice_words(source_words, source_start - _CONTEXT_WINDOW, source_start)
    after_words = _slice_words(source_words, source_end, source_end + _CONTEXT_WINDOW)

    system_prompt, user_prompt = build_reference_prompt(
        clip_words=clip_words,
        context_before_words=before_words,
        context_after_words=after_words,
        title=title,
        channel=channel,
        language=language,
        clip_duration=source_end - source_start,
    )

    logger.info(f"[{reference_id}] Requesting reverse analysis from Claude")

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    message = await client.messages.create(
        model=settings.claude_model,
        max_tokens=settings.claude_max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )

    text_blocks = [b.text for b in message.content if b.type == "text"]
    if not text_blocks:
        raise RuntimeError(
            f"Claude returned no text content (stop_reason={message.stop_reason})"
        )

    try:
        parsed = _parse_response(text_blocks[0])
    except json.JSONDecodeError as e:
        logger.error(f"[{reference_id}] Invalid JSON from Claude: {e}\nRaw: {text_blocks[0][:500]}")
        raise RuntimeError(f"Claude returned invalid JSON: {e}")

    return ReferenceAnalysis(
        hook=parsed.get("hook", ""),
        suggested_title=parsed.get("suggested_title", ""),
        virality_score=float(parsed.get("virality_score", 0) or 0),
        reason=parsed.get("reason", ""),
        tags=parsed.get("tags", []) or [],
        why_this_cut=parsed.get("why_this_cut", ""),
    )
