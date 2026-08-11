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
from app.prompts.viral_analysis import (
    DEFAULT_SOURCE_TYPE,
    build_analysis_prompt,
    source_criteria,
)
from prompt_engine.prompt_builder import PromptBuilder

logger = logging.getLogger(__name__)


# Clipe costurado (só Siege): trecho menor que isto vira piscada, e a soma
# precisa manter o vídeo perto de um minuto em vez do round inteiro.
MIN_SEGMENT = 3.0
MAX_SEGMENTED_TOTAL = 70.0

# Peso de cada eixo no final_score, seguindo a ordem de importância dos sinais
# do algoritmo (completion rate primeiro, loop por último). Soma 1.0.
AXIS_WEIGHTS = {
    "retention_score": 0.30,
    "hook_score": 0.25,
    "shareability_score": 0.20,
    "comment_bait_score": 0.15,
    "loopability_score": 0.10,
}


@dataclass
class ViralClip:
    start: float
    end: float
    score: float           # 0-10, escala do sistema (= final_score / 10)
    hook: str
    suggested_title: str
    reason: str
    tags: List[str]
    # Eixos da rubrica, 0-10 cada. O cronograma de postagem escolhe o clip de
    # cada horário por um eixo específico, então eles são guardados um a um.
    hook_score: Optional[float] = None
    retention_score: Optional[float] = None
    shareability_score: Optional[float] = None
    loopability_score: Optional[float] = None
    comment_bait_score: Optional[float] = None
    verdict: str = "post"              # post | revisar_corte
    # Trechos costurados num clipe só (vazio = corte contínuo normal)
    segments: List[tuple] = field(default_factory=list)
    weak_points: List[str] = field(default_factory=list)
    trim_reason: str = ""
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


def parse_segments(
    raw, min_segment: float = MIN_SEGMENT, max_total: float = MAX_SEGMENTED_TOTAL
) -> list[tuple[float, float]]:
    """
    Trechos válidos para costurar num clipe só, ou lista vazia.

    Lista vazia significa "clipe contínuo normal" — é o caminho de todos os
    nichos menos Siege, e também a rede de segurança quando o modelo devolve
    algo estranho: na dúvida o sistema volta ao corte simples em vez de montar
    um vídeo picotado.

    Descarta trecho curto demais (vira piscada), fora de ordem ou sobreposto, e
    corta a lista quando a soma passa do teto — o clipe precisa ficar perto de
    um minuto, não do round inteiro.
    """
    if not isinstance(raw, list) or len(raw) < 2:
        return []

    parsed: list[tuple[float, float]] = []
    for item in raw:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            continue
        try:
            start, end = float(item[0]), float(item[1])
        except (TypeError, ValueError):
            continue
        if end - start < min_segment:
            continue
        if parsed and start < parsed[-1][1]:  # fora de ordem ou sobreposto
            continue
        parsed.append((start, end))

    if len(parsed) < 2:
        return []

    kept: list[tuple[float, float]] = []
    total = 0.0
    for start, end in parsed:
        if total + (end - start) > max_total:
            break
        kept.append((start, end))
        total += end - start

    return kept if len(kept) >= 2 else []


def _axis_scores(clip_data: dict) -> dict:
    """Os cinco eixos presentes na resposta, já limitados a 0-10."""
    scores = {}
    for axis in AXIS_WEIGHTS:
        value = clip_data.get(axis)
        if value is None:
            continue
        try:
            scores[axis] = max(0.0, min(10.0, float(value)))
        except (TypeError, ValueError):
            continue
    return scores


def _clip_score(clip_data: dict, axes: dict) -> float:
    """
    Nota 0-10 do clip, que é o que o threshold e o banco usam.

    Com os cinco eixos presentes a média ponderada é recalculada aqui em vez de
    aceitar o `final_score` do modelo: LLM erra aritmética com frequência, e o
    cronograma escolhe por eixo — a nota geral precisa ser coerente com eles.
    Sem os eixos, cai para o `final_score` (0-100) e depois para o `score`
    (0-10) das respostas no formato antigo.
    """
    if len(axes) == len(AXIS_WEIGHTS):
        return sum(axes[axis] * weight for axis, weight in AXIS_WEIGHTS.items())

    final_score = clip_data.get("final_score")
    if final_score is not None:
        try:
            return max(0.0, min(10.0, float(final_score) / 10))
        except (TypeError, ValueError):
            pass

    try:
        return max(0.0, min(10.0, float(clip_data.get("score", 0))))
    except (TypeError, ValueError):
        return 0.0


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
    source_type: str = DEFAULT_SOURCE_TYPE,
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
        source_type: 'podcast' ou 'gameplay' — troca a rubrica aplicada.

    Returns:
        AnalysisResult com lista de ViralClip filtrados e notas da análise.
    """
    threshold = settings.virality_threshold
    min_dur = settings.min_clip_duration
    max_dur = settings.max_clip_duration

    logger.info(
        f"[{job_id}] Starting virality analysis. "
        f"Threshold: {threshold}, Duration: {duration_seconds:.0f}s, "
        f"Source: {source_type}"
    )

    user_prompt = build_analysis_prompt(
        words=words,
        title=title,
        channel=channel,
        duration_seconds=duration_seconds,
        threshold=threshold,
        min_duration=min_dur,
        max_duration=max_dur,
        preferred_min=settings.preferred_clip_min,
        preferred_max=settings.preferred_clip_max,
        source_type=source_type,
    )

    system_prompt = PromptBuilder().build(
        min_duration=min_dur,
        max_duration=max_dur,
        preferred_min=settings.preferred_clip_min,
        preferred_max=settings.preferred_clip_max,
        source_criteria=source_criteria(source_type),
    )

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
    raw_response = text_blocks[0]
    logger.info(f"[{job_id}] Claude response received ({len(raw_response)} chars)")

    try:
        parsed = _parse_claude_response(raw_response)
    except json.JSONDecodeError as e:
        logger.error(f"[{job_id}] Failed to parse Claude response: {e}\nRaw: {raw_response[:500]}")
        raise RuntimeError(f"Claude returned invalid JSON: {e}")

    raw_clips = parsed.get("clips", [])
    analysis_notes = parsed.get("analysis_notes", "")

    logger.info(f"[{job_id}] Claude identified {len(raw_clips)} clips before filtering")

    # Filtra por veredito, threshold e duração mínima
    segmented_allowed = (source_type or DEFAULT_SOURCE_TYPE).lower() == "siege"
    filtered: List[dict] = []
    for c in raw_clips:
        axes = _axis_scores(c)
        score = _clip_score(c, axes)
        c["_axes"] = axes
        c["_score"] = score
        c["_segments"] = parse_segments(c.get("segments")) if segmented_allowed else []
        start = float(c.get("start", 0))
        end = float(c.get("end", 0))
        # Costurado: a duração real é a soma dos trechos, não a janela bruta —
        # senão um ace espalhado seria medido pelo round inteiro.
        dur = (
            sum(e - s for s, e in c["_segments"]) if c["_segments"] else end - start
        )

        # O prompt manda não listar o que seria descartado, mas o modelo às
        # vezes lista e marca — respeitar o veredito evita renderizar à toa.
        if str(c.get("verdict", "post")).lower() == "descartar":
            logger.debug(f"[{job_id}] Clip [{start:.1f}-{end:.1f}] skipped: verdict=descartar")
            continue
        if score < threshold:
            logger.debug(f"[{job_id}] Clip [{start:.1f}-{end:.1f}] skipped: score {score} < threshold {threshold}")
            continue
        if dur < min_dur:
            logger.debug(f"[{job_id}] Clip [{start:.1f}-{end:.1f}] skipped: duration {dur:.1f}s < min {min_dur}s")
            continue

        filtered.append(c)

    logger.info(f"[{job_id}] {len(filtered)} clips passed threshold filter")

    # Divide clips longos — partes que ficarem abaixo da duração mínima são descartadas
    final_clips_data: List[dict] = []
    for c in filtered:
        if c["_segments"]:
            # Já foi montado para caber num vídeo só: dividir desmancharia a
            # jogada que a costura existe para manter inteira.
            final_clips_data.append(c)
            continue
        for part in _split_clip(c, words, max_dur):
            part_dur = part["end"] - part["start"]
            if part_dur < min_dur:
                logger.debug(
                    f"[{job_id}] Split part [{part['start']:.1f}-{part['end']:.1f}] "
                    f"skipped: duration {part_dur:.1f}s < min {min_dur}s"
                )
                continue
            final_clips_data.append(part)

    # Converte para dataclasses
    viral_clips: List[ViralClip] = []
    for c in final_clips_data:
        axes = c.get("_axes", {})
        viral_clips.append(ViralClip(
            start=float(c["start"]),
            end=float(c["end"]),
            score=c.get("_score", 0.0),
            # O banner usa 'hook'; a rubrica nova chama isso de
            # suggested_hook_caption. Aceita os dois nomes.
            hook=c.get("suggested_hook_caption") or c.get("hook", ""),
            suggested_title=c.get("suggested_title", ""),
            reason=c.get("reason", ""),
            tags=c.get("tags", []),
            hook_score=axes.get("hook_score"),
            retention_score=axes.get("retention_score"),
            shareability_score=axes.get("shareability_score"),
            loopability_score=axes.get("loopability_score"),
            comment_bait_score=axes.get("comment_bait_score"),
            verdict=str(c.get("verdict", "post")).lower(),
            segments=c.get("_segments", []),
            weak_points=[str(w) for w in (c.get("weak_points") or [])],
            trim_reason=c.get("trim_reason", ""),
            part_number=c.get("part_number"),
            parent_start=c.get("parent_start"),
        ))

    logger.info(f"[{job_id}] Final clips after split: {len(viral_clips)}")

    return AnalysisResult(clips=viral_clips, analysis_notes=analysis_notes)
