"""
Candidatos de compilado: onde olhar antes de decidir o que entra.

Duas etapas, nesta ordem:

  1. `propose_candidates` — uma passada barata do Claude sobre a transcrição
     inteira que aponta os instantes que merecem um olhar. Ela não julga nem
     monta nada.
  2. `describe_candidates` — a visão descreve esses instantes, preenchendo
     `Observation.scene`.

O resultado entra na transcrição enviada à análise final como anotação, do
mesmo jeito que os buracos de áudio já entram (ver prompts/viral_analysis.py).

Por que existe: a origem das janelas de visão eram os BURACOS da transcrição, o
que assume que o momento mora no silêncio. Medido nos seis trechos do compilado
real do alanzoka, dois não tinham buraco nenhum — fala contínua — e somavam
quase metade do vídeo publicado. Eles nunca chegavam descritos ao modelo. Aqui
a janela deixa de depender de silêncio.

Nunca levanta: sem candidatos, a análise volta a ser o que era, decidindo com a
transcrição e os buracos de áudio.
"""

import logging
from dataclasses import dataclass
from typing import Optional

import anthropic

from app.config import settings
from app.prompts.candidate_scan import build_candidate_prompt
from app.prompts.moment_assembly import build_assembly_prompt, format_moment
from app.services.moderation_terms import prompt_rule
from prompt_engine.prompt_builder import PromptBuilder
from app.prompts.viral_analysis import format_duration
from app.services import vision
from app.services.clip_forensics import parse_json_response

logger = logging.getLogger(__name__)

# Teto de tokens da passada 1. Ela devolve uma lista curta de janelas com uma
# linha de justificativa cada — não precisa do orçamento da análise inteira.
_MAX_TOKENS = 4000

# Janela mínima e máxima de um candidato. Abaixo do mínimo a visão recebe
# quadros de mais ou de menos para dizer o que mudou; acima do máximo o
# candidato vira "o assunto" em vez de "o momento".
_MIN_WINDOW = 6.0
_MAX_WINDOW = 30.0

# Candidatos que se sobrepõem por mais que isto são o mesmo acontecimento.
_MERGE_OVERLAP = 0.5

_QUESTION = (
    "Estes quadros cobrem um momento em que a conversa sugere que aconteceu "
    "alguma coisa. Compare os quadros entre si e diga o que MUDA na tela: algo "
    "ou alguém que aparece, atravessa, some, morre, se move de um jeito "
    "estranho ou está fora de lugar. Personagens de outros jogadores contam, "
    "mesmo pequenos, escuros ou no canto do quadro — a graça costuma estar no "
    "que o amigo faz. Descreva também o rosto de quem aparece na facecam e se "
    "ele muda de expressão. Se de fato nada muda, diga isso explicitamente em "
    "vez de descrever o cenário parado.\n"
    + vision.JSON_RULES
)


@dataclass
class Observation:
    """Um instante que vale olhar, e o que a imagem mostrou nele."""

    start: float
    end: float
    why: str = ""
    scene: Optional[str] = None

    @property
    def duration(self) -> float:
        return self.end - self.start


def _clean(raw: list, video_duration: float) -> list[Observation]:
    """Descarta janela impossível, apara a duração e funde as sobrepostas."""
    parsed: list[Observation] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            start = float(item["start"])
            end = float(item["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if end <= start or start < 0 or start >= video_duration:
            continue
        end = min(end, video_duration)
        # Janela curta demais não dá quadros suficientes para comparar; longa
        # demais dilui o que mudou entre eles.
        if end - start < _MIN_WINDOW:
            end = min(start + _MIN_WINDOW, video_duration)
        if end - start > _MAX_WINDOW:
            end = start + _MAX_WINDOW
        parsed.append(Observation(start=start, end=end, why=str(item.get("why", "")).strip()))

    parsed.sort(key=lambda o: o.start)

    merged: list[Observation] = []
    for obs in parsed:
        if merged and obs.start < merged[-1].end - _MERGE_OVERLAP:
            previous = merged[-1]
            previous.end = max(previous.end, obs.end)
            continue
        merged.append(obs)
    return merged


async def propose_candidates(
    job_id: str,
    transcript_text: str,
    title: str,
    channel: str,
    duration_seconds: float,
    gap_legend: str = "",
    max_candidates: Optional[int] = None,
) -> list[Observation]:
    """
    Os instantes que merecem um olhar, segundo a transcrição.

    Lista vazia = a análise segue como sempre, sem anotação de imagem além dos
    buracos de áudio.
    """
    limit = max_candidates or settings.compilation_candidates
    prompt = build_candidate_prompt(
        transcript_with_timestamps=transcript_text,
        title=title,
        channel=channel,
        duration_str=format_duration(duration_seconds),
        gap_legend=gap_legend,
        max_candidates=limit,
        min_window=int(_MIN_WINDOW),
        max_window=int(_MAX_WINDOW),
    )

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    try:
        message = await client.messages.create(
            model=settings.claude_model,
            max_tokens=_MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        blocks = [b.text for b in message.content if b.type == "text"]
        data = parse_json_response(blocks[0]) if blocks else {}
    except Exception as exc:  # noqa: BLE001 — camada opcional, nunca derruba o job
        logger.warning(f"[{job_id}] Varredura de candidatos falhou ({exc}) — seguindo sem ela")
        return []

    candidates = _clean(data.get("candidates") or [], duration_seconds)[:limit]
    logger.info(
        f"[{job_id}] Varredura apontou {len(candidates)} candidato(s) para a visão olhar"
    )
    # As janelas por extenso, e não só a contagem: quando a montagem escolhe
    # mal, é este log que separa os dois problemas possíveis — a varredura não
    # apontou o momento certo (passada 1), ou apontou e a montagem preferiu
    # outro (passada 2). Sem ele os dois chegam idênticos ao log.
    for index, candidate in enumerate(candidates, 1):
        logger.info(
            f"[{job_id}]   candidato {index:2}: "
            f"[{candidate.start:.0f}-{candidate.end:.0f}] {candidate.why[:80]}"
        )
    return candidates


async def describe_candidates(
    job_id: str, video_path: str, candidates: list[Observation]
) -> None:
    """
    Preenche `scene` nos candidatos, no lugar.

    Nunca levanta: sem descrição o candidato ainda serve de anotação com a
    justificativa de texto, que é melhor que nada.
    """
    if not settings.vision_enabled or not candidates:
        return

    windows = [(c.start, c.end) for c in candidates]
    scenes = await vision.look_many(job_id, video_path, windows, [_QUESTION] * len(windows))

    described = 0
    for candidate, scene in zip(candidates, scenes):
        if scene is None:
            continue
        candidate.scene = scene.summary()
        described += 1

    logger.info(
        f"[{job_id}] {described}/{len(candidates)} candidato(s) descritos pela imagem"
    )


# ─── Montagem ─────────────────────────────────────────────────────────────────

# Teto de tokens da montagem. A entrada é um cardápio curto e a saída são
# números mais alguns campos de texto — nada perto do orçamento da análise.
_ASSEMBLY_MAX_TOKENS = 4000

# Caracteres de fala mostrados por momento. O suficiente para o modelo saber do
# que se trata sem transformar o cardápio numa segunda transcrição.
_SPEECH_CHARS = 220

# Teto da soma dos trechos de um compilado. O mesmo de parse_segments, aplicado
# aqui para o corte ser DELIBERADO: o backstop lá apara pelo fim da lista e pode
# derrubar o compilado inteiro. Medido na primeira montagem real: o modelo
# escolheu 4 momentos de ~28s (106s e 110s), o dobro do alvo, e a aparagem cega
# deixou um dos compilados com um trecho só — ou seja, sem compilado nenhum.
_MAX_TOTAL = 70.0


def _speech_in(words: list[dict], start: float, end: float) -> str:
    """A fala transcrita dentro da janela, aparada."""
    said = [w["text"] for w in words if w["start"] >= start and w["end"] <= end]
    text = " ".join(said).strip()
    return text[:_SPEECH_CHARS] + ("…" if len(text) > _SPEECH_CHARS else "")


def _menu(observations: list[Observation], words: list[dict]) -> str:
    """O cardápio numerado — a única coisa que a montagem enxerga."""
    return "\n\n".join(
        format_moment(
            index=i,
            start=obs.start,
            end=obs.end,
            speech=_speech_in(words, obs.start, obs.end),
            scene=obs.scene or "",
            why=obs.why,
        )
        for i, obs in enumerate(observations, 1)
    )


def _resolve(picked, observations: list[Observation]) -> list[tuple[float, float]]:
    """
    Números → trechos, na ordem em que o modelo os entregou.

    Número fora da lista ou repetido é descartado em vez de derrubar o
    compilado inteiro: o resto da montagem continua válido.
    """
    segments: list[tuple[float, float]] = []
    seen: set[int] = set()
    for item in picked if isinstance(picked, list) else []:
        try:
            index = int(item)
        except (TypeError, ValueError):
            continue
        if index in seen or not (1 <= index <= len(observations)):
            continue
        seen.add(index)
        obs = observations[index - 1]
        segments.append((obs.start, obs.end))
    return segments


async def assemble_compilations(
    job_id: str,
    observations: list[Observation],
    words: list[dict],
    title: str,
    channel: str,
    target: str,
    count: int = 2,
) -> tuple[list[dict], str]:
    """
    Monta compilados escolhendo momentos do cardápio.

    Devolve (clipes, notas) no mesmo formato que a análise normal produz, com
    `segments` já resolvidos. Lista vazia = a análise segue pelo caminho comum.
    """
    if len(observations) < 3:
        logger.info(f"[{job_id}] Candidatos de menos ({len(observations)}) para montar compilado")
        return [], ""

    prompt = build_assembly_prompt(
        moments=_menu(observations, words),
        title=title,
        channel=channel,
        target=target,
        count=count,
        moderation_rule=prompt_rule(),
    )

    # A calibração entra como system prompt, mas SEM o core_prompt: dele vem a
    # tarefa "ache clipes nesta transcrição", que é o enquadramento que esta
    # passada existe para evitar.
    # Teto maior que o padrão de 6: os exemplos de um compilado inteiro vêm em
    # conjunto, e cortar um deles tira justamente a peça que ensina a função
    # dela na montagem (abertura, respiro, fechamento).
    calibration = PromptBuilder().examples_section(max_examples=10)

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    try:
        message = await client.messages.create(
            model=settings.claude_model,
            max_tokens=_ASSEMBLY_MAX_TOKENS,
            system=calibration or anthropic.NOT_GIVEN,
            messages=[{"role": "user", "content": prompt}],
        )
        blocks = [b.text for b in message.content if b.type == "text"]
        data = parse_json_response(blocks[0]) if blocks else {}
    except Exception as exc:  # noqa: BLE001 — nunca derruba o job
        logger.warning(f"[{job_id}] Montagem do compilado falhou ({exc}) — análise comum")
        return [], ""

    clips: list[dict] = []
    for entry in data.get("compilations") or []:
        if not isinstance(entry, dict):
            continue
        segments = _resolve(entry.get("moments"), observations)
        if len(segments) < 2:
            logger.warning(
                f"[{job_id}] Compilado descartado: {len(segments)} momento(s) válido(s)"
            )
            continue
        # Momentos demais: corta pelo FIM, que é onde a montagem põe o de
        # menor impacto — a abertura é escolhida primeiro e nunca se perde.
        dropped = 0
        while len(segments) > 2 and sum(e - s for s, e in segments) > _MAX_TOTAL:
            segments.pop()
            dropped += 1
        if dropped:
            logger.info(
                f"[{job_id}] Compilado passava de {_MAX_TOTAL:.0f}s — "
                f"{dropped} momento(s) do fim cortado(s)"
            )

        clip = {k: v for k, v in entry.items() if k != "moments"}
        # Marca a origem: um compilado montado que perde os trechos na
        # validação NÃO tem forma contínua que faça sentido (o intervalo bruto
        # pode ser meia hora de vídeo). Ver o descarte no analyzer.
        clip["_assembled"] = True
        # `start`/`end` descrevem o intervalo bruto que o compilado atravessa; a
        # duração do vídeo é a soma dos trechos, calculada adiante.
        clip["start"] = min(s for s, _ in segments)
        clip["end"] = max(e for _, e in segments)
        clip["segments"] = [list(seg) for seg in segments]
        clips.append(clip)
        total = sum(e - s for s, e in segments)
        logger.info(
            f"[{job_id}] Compilado com {len(segments)} momento(s), {total:.1f}s: "
            + " → ".join(f"{s:.0f}-{e:.0f}" for s, e in segments)
        )

    if not clips:
        logger.warning(f"[{job_id}] Montagem não devolveu compilado utilizável")
    return clips, str(data.get("analysis_notes", ""))
