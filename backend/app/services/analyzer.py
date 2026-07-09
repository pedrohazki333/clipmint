"""
Serviço de análise de viralidade usando Claude API.

Este é o componente mais crítico do ClipMint. Ele recebe a transcrição completa
com timestamps e os metadados do vídeo, envia para o Claude e retorna uma lista
de segmentos com alto potencial viral, já filtrados pelo threshold configurado.

Lógica de split:
  Clips com duração > MAX_CLIP_DURATION são divididos em duas partes,
  buscando o ponto de corte mais natural (pausa ou fim de frase) na metade.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import List, Optional

import anthropic

from app.config import settings
from app.prompts.viral_analysis import build_analysis_prompt
from prompt_engine.prompt_builder import PromptBuilder

logger = logging.getLogger(__name__)

CLAUDE_MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 4096


@dataclass
class ViralClip:
    start: float
    end: float
    score: float
    hook: str
    suggested_title: str
    reason: str
    tags: List[str]
    # Clip dividido em partes (>MAX_CLIP_DURATION)
    part_number: Optional[int] = None
    parent_start: Optional[float] = None  # start do clip original antes do split


@dataclass
class AnalysisResult:
    clips: List[ViralClip]
    analysis_notes: str


def _find_split_point(words: List[dict], target_time: float) -> float:
    """
    Encontra o ponto de corte mais natural próximo de target_time.

    Prioriza fim de frases (pontuação). Se não encontrar em ±10s,
    retorna o tempo da pausa mais longa na janela.
    """
    window = 10.0  # segundos de tolerância para buscar quebra natural

    best_sentence_end: Optional[float] = None
    best_pause: Optional[tuple[float, float]] = None  # (gap_duration, time)

    for i, word in enumerate(words):
        t = word["end"]
        if abs(t - target_time) > window:
            continue

        # Fim de frase
        if word["text"].rstrip().endswith((".", "!", "?", "...")):
            if best_sentence_end is None or abs(t - target_time) < abs(best_sentence_end - target_time):
                best_sentence_end = t

        # Pausa entre palavras
        if i + 1 < len(words):
            gap = words[i + 1]["start"] - word["end"]
            if gap > 0.3:  # pausa > 300ms
                if best_pause is None or gap > best_pause[0]:
                    best_pause = (gap, word["end"])

    if best_sentence_end is not None:
        return best_sentence_end
    if best_pause is not None:
        return best_pause[1]
    return target_time


def _split_clip(clip_data: dict, words: List[dict], max_duration: int) -> List[dict]:
    """
    Divide um clip longo em duas partes com corte em ponto natural.

    Retorna lista de 1 ou 2 dicts, cada um com campos start/end/part_number/parent_start.
    """
    duration = clip_data["end"] - clip_data["start"]
    if duration <= max_duration:
        return [clip_data]

    mid_target = clip_data["start"] + duration / 2

    # Filtra palavras dentro do clip
    clip_words = [w for w in words if w["start"] >= clip_data["start"] and w["end"] <= clip_data["end"]]
    split_point = _find_split_point(clip_words, mid_target)

    part1 = dict(clip_data)
    part1["end"] = split_point
    part1["part_number"] = 1
    part1["parent_start"] = clip_data["start"]

    part2 = dict(clip_data)
    part2["start"] = split_point
    part2["part_number"] = 2
    part2["parent_start"] = clip_data["start"]

    logger.info(
        f"Split clip [{clip_data['start']:.1f}-{clip_data['end']:.1f}] "
        f"at {split_point:.1f}s → part1: {part1['end'] - part1['start']:.1f}s, "
        f"part2: {part2['end'] - part2['start']:.1f}s"
    )

    return [part1, part2]


def _parse_claude_response(raw: str) -> dict:
    """
    Extrai e parseia o JSON da resposta do Claude.

    O Claude às vezes envolve o JSON em blocos de código markdown;
    esta função lida com isso graciosamente.
    """
    raw = raw.strip()

    # Remove blocos de código markdown se presentes
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])

    return json.loads(raw)


async def analyze_virality(
    job_id: str,
    words: List[dict],
    title: str,
    channel: str,
    duration_seconds: float,
) -> AnalysisResult:
    """
    Analisa a transcrição completa e retorna segmentos com alto potencial viral.

    Envia o prompt ao Claude API, parseia a resposta JSON, aplica filtro de
    threshold e divide clips longos em duas partes quando necessário.

    Args:
        job_id: ID do job para logging.
        words: Lista de palavras com timestamps (dicts com text/start/end/confidence).
        title: Título do vídeo.
        channel: Nome do canal.
        duration_seconds: Duração total do vídeo em segundos.

    Returns:
        AnalysisResult com lista de ViralClip filtrados e notas da análise.
    """
    threshold = settings.virality_threshold
    min_dur = settings.min_clip_duration
    max_dur = settings.max_clip_duration

    logger.info(
        f"[{job_id}] Starting virality analysis. "
        f"Threshold: {threshold}, Duration: {duration_seconds:.0f}s"
    )

    _, user_prompt = build_analysis_prompt(
        words=words,
        title=title,
        channel=channel,
        duration_seconds=duration_seconds,
        threshold=threshold,
        min_duration=min_dur,
        max_duration=max_dur,
    )

    system_prompt = PromptBuilder().build(
        min_duration=min_dur,
        max_duration=max_dur,
    )

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    message = await client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=MAX_TOKENS,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )

    raw_response = message.content[0].text
    logger.info(f"[{job_id}] Claude response received ({len(raw_response)} chars)")

    try:
        parsed = _parse_claude_response(raw_response)
    except json.JSONDecodeError as e:
        logger.error(f"[{job_id}] Failed to parse Claude response: {e}\nRaw: {raw_response[:500]}")
        raise RuntimeError(f"Claude returned invalid JSON: {e}")

    raw_clips = parsed.get("clips", [])
    analysis_notes = parsed.get("analysis_notes", "")

    logger.info(f"[{job_id}] Claude identified {len(raw_clips)} clips before filtering")

    # Filtra por threshold e duração mínima
    filtered: List[dict] = []
    for c in raw_clips:
        score = float(c.get("score", 0))
        start = float(c.get("start", 0))
        end = float(c.get("end", 0))
        dur = end - start

        if score < threshold:
            logger.debug(f"[{job_id}] Clip [{start:.1f}-{end:.1f}] skipped: score {score} < threshold {threshold}")
            continue
        if dur < min_dur:
            logger.debug(f"[{job_id}] Clip [{start:.1f}-{end:.1f}] skipped: duration {dur:.1f}s < min {min_dur}s")
            continue

        filtered.append(c)

    logger.info(f"[{job_id}] {len(filtered)} clips passed threshold filter")

    # Divide clips longos
    final_clips_data: List[dict] = []
    for c in filtered:
        parts = _split_clip(c, words, max_dur)
        final_clips_data.extend(parts)

    # Converte para dataclasses
    viral_clips: List[ViralClip] = []
    for c in final_clips_data:
        viral_clips.append(ViralClip(
            start=float(c["start"]),
            end=float(c["end"]),
            score=float(c.get("score", 0)),
            hook=c.get("hook", ""),
            suggested_title=c.get("suggested_title", ""),
            reason=c.get("reason", ""),
            tags=c.get("tags", []),
            part_number=c.get("part_number"),
            parent_start=c.get("parent_start"),
        ))

    logger.info(f"[{job_id}] Final clips after split: {len(viral_clips)}")

    return AnalysisResult(clips=viral_clips, analysis_notes=analysis_notes)
