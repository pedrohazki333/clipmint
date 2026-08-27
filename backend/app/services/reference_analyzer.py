"""
Por que um clipe de outro criador funcionou, via Claude API.

Duas análises moram aqui, uma para cada jeito de aprender com um clipe alheio
(ver o modelo ReferenceExample):

- `analyze_reference` — o modo alinhado. Recebe o trecho já localizado dentro do
  vídeo original (via aligner) mais o contexto ao redor, e pergunta por que
  AQUELE recorte foi escolhido. A força dela está no que ficou de fora.

- `analyze_standalone_clip` — o modo sem original. Não há contexto ao redor para
  comparar, então a pergunta muda: em vez de "por que aqui e não ali", é "o que
  este clipe faz, segundo a segundo". A resposta é construída em cima das quatro
  evidências medidas em services/clip_forensics.py — fala, som, imagem e cortes.

As duas devolvem o mesmo ReferenceAnalysis (hook/título/score/reason/tags), no
vocabulário do analyzer, para que o resultado sirva de exemplo few-shot sem que
o resto do sistema precise saber de qual modo ele veio. A segunda devolve
também a perícia detalhada, que é dela sozinha.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import List

import anthropic

from app.config import settings
from app.prompts.clip_forensics import build_forensics_prompt
from app.prompts.reference_analysis import build_reference_prompt
from app.services.clip_forensics import ClipEvidence, parse_json_response, timed_transcript

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
        parsed = parse_json_response(text_blocks[0])
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


async def analyze_standalone_clip(
    reference_id: str,
    evidence: ClipEvidence,
    title: str,
    channel: str,
    source_type: str,
    language: str,
    notas: str = "",
) -> tuple[ReferenceAnalysis, dict]:
    """
    Explica um clipe que chegou sozinho, a partir do que foi medido nele.

    Devolve `(analysis, forensics)`: a primeira no mesmo formato do modo
    alinhado — é ela que o confirm() publica como exemplo few-shot —, a segunda
    com a leitura detalhada (gancho quadro a quadro, batidas, papel do som,
    regras transferíveis), que fica guardada para a tela e para o prompt.

    Args:
        reference_id: ID da referência (para logging).
        evidence: fala, som, imagem e cortes medidos em clip_forensics.py.
        title / channel: o que o usuário informou sobre a origem do clipe.
        source_type: nicho da conta que vai aprender com ele.
        language: idioma detectado na transcrição.
        notas: observação do usuário, quando houver.
    """
    system_prompt, user_prompt = build_forensics_prompt(
        duration=evidence.duration,
        transcript=timed_transcript(evidence.words),
        audio=evidence.audio.as_prompt(),
        cuts=evidence.cut_rhythm(),
        visual=evidence.visual.as_prompt(),
        title=title,
        channel=channel,
        source_type=source_type,
        language=language,
        notas=notas,
    )

    logger.info(f"[{reference_id}] Pedindo a síntese da perícia ao Claude")

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    message = await client.messages.create(
        model=settings.claude_forensics_model,
        max_tokens=settings.claude_forensics_max_tokens,
        # Sem `thinking` de propósito, por dois motivos que se somam: o SDK
        # fixado no projeto (anthropic==0.40.0) nem conhece o parâmetro e
        # levanta TypeError, e no Opus 5 ele seria redundante — o raciocínio
        # adaptativo já é o padrão quando o parâmetro é omitido. Passá-lo
        # explicitamente custava um pipeline inteiro e não comprava nada.
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )

    text_blocks = [b.text for b in message.content if b.type == "text"]
    if not text_blocks:
        raise RuntimeError(
            f"Claude returned no text content (stop_reason={message.stop_reason})"
        )

    # Bater no teto de tokens produz JSON pela metade, e o erro de parse que vem
    # depois aponta para uma aspa não fechada na linha 27 — uma pista que não
    # leva a lugar nenhum. Aconteceu no primeiro clipe real; o diagnóstico é
    # barato e a mensagem diz o que fazer.
    if message.stop_reason == "max_tokens":
        raise RuntimeError(
            f"A síntese da perícia foi truncada no teto de "
            f"{settings.claude_forensics_max_tokens} tokens. Aumente "
            f"CLAUDE_FORENSICS_MAX_TOKENS no .env."
        )

    try:
        parsed = parse_json_response(text_blocks[-1])
    except json.JSONDecodeError as e:
        logger.error(
            f"[{reference_id}] Invalid JSON from Claude: {e}\nRaw: {text_blocks[-1][:500]}"
        )
        raise RuntimeError(f"Claude returned invalid JSON: {e}")

    forensics = parsed.get("forensics") or {}
    if not isinstance(forensics, dict):
        forensics = {}

    analysis = ReferenceAnalysis(
        hook=parsed.get("hook", ""),
        suggested_title=parsed.get("suggested_title", ""),
        virality_score=float(parsed.get("virality_score", 0) or 0),
        reason=parsed.get("reason", ""),
        tags=parsed.get("tags", []) or [],
        why_this_cut=parsed.get("why_this_cut", ""),
    )
    logger.info(
        f"[{reference_id}] Perícia sintetizada: nota {analysis.virality_score}, "
        f"{len(forensics.get('transferable_rules') or [])} regra(s) de corte"
    )
    return analysis, forensics
