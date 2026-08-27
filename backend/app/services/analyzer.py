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
from app.services.candidates import (
    assemble_compilations,
    describe_candidates,
    propose_candidates,
)
from app.prompts.viral_analysis import (
    COMPILATION_TARGET,
    DEFAULT_SOURCE_TYPE,
    GAP_LEGEND,
    build_analysis_prompt,
    format_transcript_with_timestamps,
    source_criteria,
)
from app.services import vision
from app.services.audio_events import Gap, rescue_start
from app.services.moderation_terms import find_risky_terms
from prompt_engine.prompt_builder import PromptBuilder

logger = logging.getLogger(__name__)


# Clipe costurado (Siege e compilado): trecho menor que isto vira piscada, e a
# soma precisa manter o vídeo perto de um minuto em vez do round inteiro.
MIN_SEGMENT = 3.0
MAX_SEGMENTED_TOTAL = 70.0

# Distância mínima entre dois trechos de um COMPILADO para eles serem momentos
# diferentes. Sem isso, "a ordem não precisa ser cronológica" degenera: no
# primeiro job com duas passadas o modelo devolveu [5575.3-5600.1] seguido de
# [5547.3-5575.3] — um bloco contínuo de 53s fatiado ao meio e tocado de trás
# para frente, o que sai visivelmente quebrado. Trechos que se encostam são o
# MESMO acontecimento e voltam a ser um só. 30s é folgado: os trechos do
# compilado real do alanzoka distavam minutos uns dos outros.
COMPILATION_MIN_GAP = 30.0

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


def _merge_adjacent(
    segments: list[tuple[float, float]], min_gap: float
) -> list[tuple[float, float]]:
    """
    Funde trechos vizinhos na FONTE, preservando a ordem editorial.

    Dois trechos que se encostam são um acontecimento só, fatiado. Fundir em
    vez de descartar é o que salva o resto do compilado: o modelo costuma errar
    isso em um par e acertar nos outros.
    """
    indexed = list(enumerate(segments))
    merged: list[list] = []
    for index, (start, end) in sorted(indexed, key=lambda pair: pair[1][0]):
        if merged and start - merged[-1][2] <= min_gap:
            merged[-1][0] = min(merged[-1][0], index)
            merged[-1][2] = max(merged[-1][2], end)
            continue
        merged.append([index, start, end])

    # De volta à ordem em que o modelo entregou — ela é a montagem.
    merged.sort(key=lambda item: item[0])
    return [(start, end) for _, start, end in merged]


def parse_segments(
    raw,
    min_segment: float = MIN_SEGMENT,
    max_total: float = MAX_SEGMENTED_TOTAL,
    chronological: bool = True,
    min_gap: float = COMPILATION_MIN_GAP,
) -> list[tuple[float, float]]:
    """
    Trechos válidos para costurar num clipe só, ou lista vazia.

    Lista vazia significa "clipe contínuo normal" — é o caminho de todo job em
    modo individual fora do Siege, e também a rede de segurança quando o modelo
    devolve algo estranho: na dúvida o sistema volta ao corte simples em vez de
    montar um vídeo picotado.

    Descarta trecho curto demais (vira piscada) ou sobreposto, e corta a lista
    quando a soma passa do teto — o clipe precisa ficar perto de um minuto, não
    do round inteiro.

    `chronological=False` (compilado) aceita trechos fora de ordem. Num ace de
    Siege a ordem é a do acontecimento e inverter seria mentir sobre a jogada;
    num compilado a ordem é EDITORIAL — medido no compilado real do alanzoka,
    os 6 trechos vinham de 64min, 6min, 71min, 94min, 46min e 51min, nessa
    ordem, abrindo pela risada mais forte. Com a regra cronológica, tudo depois
    do primeiro trecho era descartado e o compilado virava um clipe de 8s.
    Sobreposição continua barrada nos dois modos: é o mesmo material duas vezes.
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
        if chronological:
            if parsed and start < parsed[-1][1]:  # fora de ordem ou sobreposto
                continue
        elif any(start < prev_end and prev_start < end for prev_start, prev_end in parsed):
            continue
        parsed.append((start, end))

    if len(parsed) < 2:
        return []

    # Só no compilado: em Siege os trechos de um ace são vizinhos de propósito
    # (a caminhada entre os abates), e fundi-los desmancharia a feature.
    if not chronological:
        parsed = _merge_adjacent(parsed, min_gap)
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


async def _scan_for_compilation(
    job_id: str,
    words: List[dict],
    gaps,
    title: str,
    channel: str,
    duration_seconds: float,
    video_path: Optional[str],
) -> list:
    """
    Passada 1 do compilado: aponta instantes e manda a visão descrevê-los.

    Sem vídeo em disco a varredura ainda vale — as justificativas de texto vão
    para a anotação mesmo sem imagem —, mas é a descrição visual que carrega o
    peso, então é ela que o log reporta.
    """
    transcript_text = format_transcript_with_timestamps(words, gaps)
    observations = await propose_candidates(
        job_id=job_id,
        transcript_text=transcript_text,
        title=title,
        channel=channel,
        duration_seconds=duration_seconds,
        gap_legend=GAP_LEGEND.strip() if gaps else "",
    )
    if observations and video_path:
        await describe_candidates(job_id, video_path, observations)
    return observations


def _log_segment_decision(job_id: str, clip: dict, raw_segments, allowed: bool) -> None:
    """Por que este clipe saiu costurado ou contínuo."""
    window = f"[{clip.get('start')}-{clip.get('end')}]"
    accepted = clip["_segments"]
    if accepted:
        total = sum(end - start for start, end in accepted)
        logger.info(
            f"[{job_id}] Clip {window}: {len(accepted)} trecho(s) costurado(s), "
            f"{total:.1f}s somados"
        )
        return
    if raw_segments and allowed:
        count = len(raw_segments) if isinstance(raw_segments, list) else "?"
        logger.warning(
            f"[{job_id}] Clip {window}: os {count} trecho(s) devolvidos pelo modelo "
            f"foram RECUSADOS (menos de 2 válidos, curtos demais, sobrepostos, ou "
            f"acima do teto de {MAX_SEGMENTED_TOTAL:.0f}s somados) — sai contínuo"
        )
    elif raw_segments and not allowed:
        logger.info(f"[{job_id}] Clip {window}: trechos ignorados (modo não permite costura)")


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


def _rescue_event_starts(
    job_id: str,
    clips: List[dict],
    gaps: List[Gap],
    words: List[dict],
    max_duration: int,
) -> None:
    """
    Devolve ao corte o fato que a fala está comentando, quando ele ficou de fora.

    Rede de segurança do que o prompt já pede. O modelo lê texto, e a tentação
    de começar na primeira palavra depois de um buraco é forte demais para
    depender só de instrução: um clipe que abre logo após um buraco barulhento
    está, quase por definição, mostrando a reação sem a causa.

    Só mexe no `start`, só o empurra para trás e só quando o áudio confirma que
    havia um evento ali. Trecho costurado passa intacto — a lista de segmentos
    já define a linha do tempo do clipe.
    """
    if not gaps:
        return

    for clip in clips:
        if clip.get("_segments"):
            continue

        start = float(clip.get("start", 0))
        end = float(clip.get("end", 0))
        new_start, event = rescue_start(start, end, gaps, words, max_duration)
        if event is None:
            continue

        clip["start"] = new_start
        note = (
            f"Início recuado de {start:.1f}s para {new_start:.1f}s: o corte "
            f"começava depois de {event.duration:.0f}s de áudio alto "
            f"({event.above_speech:+.0f} dB vs fala) em "
            f"[{event.start:.1f}-{event.end:.1f}], ou seja, pegava a reação sem o fato."
        )
        clip["trim_reason"] = f"{clip.get('trim_reason', '').strip()} {note}".strip()
        logger.info(f"[{job_id}] {note}")


def _bounds_question(start: float, end: float) -> str:
    """
    A pergunta do refino, montada por concatenação.

    Nada de `.format()` aqui: JSON_RULES contém um exemplo de JSON, e as chaves
    dele seriam lidas como campos de substituição.
    """
    return (
        f"Estes quadros cercam um corte que vai de {start:.1f}s a {end:.1f}s.\n"
        "Diga onde, nesta linha do tempo, está o acontecimento visual — "
        "e se há algum.\n" + vision.JSON_RULES
    )


def _snap_to_word(words: List[dict], time: float) -> float:
    """
    Recua até o começo da palavra que está sendo dita, se houver uma.

    O keyframe cai onde o codificador quis, não onde a frase começa; sem isto
    um corte pode abrir no meio de uma palavra.
    """
    for word in words:
        if word["start"] <= time < word["end"]:
            return word["start"]
    return time


async def _refine_bounds_with_vision(
    job_id: str,
    video_path: str,
    clips: List[dict],
    words: List[dict],
    max_duration: int,
) -> None:
    """
    Usa a imagem para esticar o corte até conter o acontecimento inteiro.

    A regra que governa tudo aqui: esta função só AFROUXA. Ela empurra o início
    para trás e o fim para frente, nunca o contrário — perder o fato custa o
    clipe inteiro, sobrar meio segundo não custa nada.

    E ela não vota no veredito. A versão anterior marcava `revisar_corte`
    quando a visão dizia que nada acontecia; o campo devolveu respostas opostas
    para a mesma janela em duas execuções seguidas, então saiu. O que fica é o
    que se mostrou estável entre rodadas: a descrição do que está na tela e os
    instantes do acontecimento.

    A descrição é gravada no `trim_reason` mesmo quando o corte não muda — é
    assim que, um mês depois, dá para saber o que havia naquele trecho sem
    reabrir o vídeo.
    """
    targets = [c for c in clips if not c.get("_segments")][: settings.vision_max_windows]
    if not targets:
        return

    margin = settings.vision_window
    windows = [
        (float(c["start"]) - margin, float(c["end"]) + margin) for c in targets
    ]
    questions = [
        _bounds_question(float(c["start"]), float(c["end"])) for c in targets
    ]

    scenes = await vision.look_many(job_id, video_path, windows, questions)

    for clip, scene in zip(targets, scenes):
        if scene is None:
            continue

        start, end = float(clip["start"]), float(clip["end"])
        notes: List[str] = []

        new_start, new_end = start, end
        if scene.event_start is not None and scene.event_start < start:
            new_start = _snap_to_word(words, scene.event_start)
        if scene.event_end is not None and scene.event_end > end:
            new_end = scene.event_end

        if new_end - new_start > max_duration:
            # Não cabe tudo: sacrifica o começo, porque o fim é onde está a
            # reação — mesma prioridade do resgate por áudio.
            new_start = new_end - max_duration

        if new_start < start or new_end > end:
            notes.append(
                f"Limites abertos pela imagem: [{start:.1f}-{end:.1f}] → "
                f"[{new_start:.1f}-{new_end:.1f}]."
            )
            clip["start"], clip["end"] = new_start, new_end
            logger.info(
                f"[{job_id}] Corte [{start:.1f}-{end:.1f}] aberto para "
                f"[{new_start:.1f}-{new_end:.1f}] pela imagem"
            )

        notes.append(f"Na imagem: {scene.summary()}")
        note = " ".join(notes)
        clip["trim_reason"] = f"{clip.get('trim_reason', '').strip()} {note}".strip()


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


def _warn_risky_wording(job_id: str, clips: List[ViralClip]) -> None:
    """
    Avisa quando o banner ou o título saem com vocabulário de violência.

    Aviso, e não reescrita: o hook é uma frase, e trocar palavra por palavra
    dentro dela devolve português torto. Quem decide é quem posta — o log diz
    qual clipe e qual palavra, e o texto está a um clique de ser editado antes
    do render. Ver `app.services.moderation_terms` para o que é documentado e
    o que é precaução.
    """
    for clip in clips:
        for field, text in (("banner", clip.hook), ("título", clip.suggested_title)):
            terms = find_risky_terms(text)
            if terms:
                logger.warning(
                    f"[{job_id}] Clip [{clip.start:.1f}-{clip.end:.1f}] com "
                    f"{', '.join(terms)!r} no {field} — vocabulário que pode "
                    f"custar alcance no TikTok: {text!r}"
                )


async def analyze_virality(
    job_id: str,
    words: List[dict],
    title: str,
    channel: str,
    duration_seconds: float,
    source_type: str = DEFAULT_SOURCE_TYPE,
    gaps: Optional[List[Gap]] = None,
    video_path: Optional[str] = None,
    clip_mode: str = "individual",
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
        clip_mode: 'compilation' PEDE um compilado (vários momentos costurados
            num vídeo só). Não é garantia: sem material que se sustente, o
            modelo devolve clipes individuais e o pipeline segue normal.
        gaps: Buracos da transcrição medidos por services.audio_events. Anotam
            o prompt e alimentam o resgate de cortes que começam depois do fato.
        video_path: Vídeo em disco. Presente, a imagem entra na decisão dos
            limites de cada corte (ver _refine_bounds_with_vision).

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

    # Compilado: antes de escolher, descobrir onde olhar. A origem de janela
    # dos buracos de áudio é cega para o momento que acontece com todo mundo
    # falando junto — e num compilado isso é metade do material bom.
    observations = []
    assembled: List[dict] = []
    assembly_notes = ""
    if clip_mode == "compilation":
        observations = await _scan_for_compilation(
            job_id, words, gaps, title, channel, duration_seconds, video_path
        )
        assembled, assembly_notes = await assemble_compilations(
            job_id=job_id,
            observations=observations,
            words=words,
            title=title,
            channel=channel,
            target=COMPILATION_TARGET,
        )

    if assembled:
        # A montagem já escolheu, a partir de um cardápio de momentos inteiros.
        # Pedir a mesma coisa de novo pela transcrição não acrescenta nada e
        # traz de volta o enquadramento que faz o modelo fatiar um momento só.
        raw_clips = assembled
        analysis_notes = assembly_notes
        logger.info(f"[{job_id}] {len(raw_clips)} compilado(s) montados do cardápio")
    else:
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
            gaps=gaps,
            clip_mode=clip_mode,
            observations=observations,
        )

        system_prompt = PromptBuilder().build(
            min_duration=min_dur,
            max_duration=max_dur,
            preferred_min=settings.preferred_clip_min,
            preferred_max=settings.preferred_clip_max,
            source_criteria=source_criteria(source_type),
        )

        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

        # Streaming, e não `create`, por causa do tamanho da resposta.
        #
        # Uma análise de vídeo longo devolve dezenas de candidatos com cinco
        # eixos e uma justificativa cada: passa de 16k tokens de saída com
        # facilidade. Acima disso o SDK precisa de streaming para a conexão não
        # estourar o timeout de HTTP enquanto o modelo ainda escreve — sem ele,
        # subir `claude_max_tokens` só trocaria "resposta cortada" por
        # "timeout". `get_final_message()` devolve a mensagem montada, então
        # daqui para baixo nada muda.
        async with client.messages.stream(
            model=settings.claude_model,
            max_tokens=settings.claude_max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        ) as stream:
            message = await stream.get_final_message()

        # O teto de saída é um modo de falha CONHECIDO e tem sintoma próprio:
        # a resposta vem cortada no meio e o JSON não fecha. Sem esta checagem
        # ela caía no except de JSONDecodeError logo abaixo e virava "Claude
        # returned invalid JSON" — que manda investigar o parser quando o
        # problema é o `claude_max_tokens`.
        if message.stop_reason == "max_tokens":
            raise RuntimeError(
                f"Resposta cortada no teto de {settings.claude_max_tokens} tokens "
                f"de saída. Aumente CLAUDE_MAX_TOKENS ou reduza o tamanho do "
                f"vídeo analisado."
            )
        logger.info(
            f"[{job_id}] Análise: {message.usage.input_tokens} tokens de entrada, "
            f"{message.usage.output_tokens} de saída "
            f"(teto {settings.claude_max_tokens})"
        )
        # Estes números só existem AQUI: a API devolve `usage` na resposta e ele
        # não volta depois. Sem gravar agora, o custo de análise viraria
        # estimativa por contagem de caracteres. A chamada tem sessão própria e
        # engole exceção — medir não pode derrubar a análise que já deu certo.
        from app.services import usage_monitor

        await usage_monitor.registrar_analise_job(
            job_id,
            model=settings.claude_model,
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
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
    compilation = clip_mode == "compilation"
    segmented_allowed = compilation or (source_type or DEFAULT_SOURCE_TYPE).lower() == "siege"
    for c in raw_clips:
        raw_segments = c.get("segments")
        c["_segments"] = (
            parse_segments(raw_segments, chronological=not compilation)
            if segmented_allowed
            else []
        )
        # Cair no corte contínuo é a rede de segurança certa, mas em silêncio
        # ela vira "o modo compilado não funciona" sem nenhuma pista de por quê:
        # o modelo pode não ter devolvido trecho nenhum, ou ter devolvido
        # trechos que o parse recusou. São problemas opostos e o log tem que
        # separar os dois.
        _log_segment_decision(job_id, c, raw_segments, segmented_allowed)

    # Compilado montado que perdeu os trechos não vira clipe contínuo: o
    # intervalo bruto dele vai do primeiro ao último momento e pode cobrir meia
    # hora de vídeo. Medido: um compilado recusado virou um "clipe" de 1950s,
    # que o divisor partiu em duas metades de 16 minutos e o render aceitou.
    dropped = [c for c in raw_clips if c.get("_assembled") and not c["_segments"]]
    for c in dropped:
        logger.warning(
            f"[{job_id}] Compilado [{c.get('start'):.0f}-{c.get('end'):.0f}] descartado: "
            f"sem trechos válidos não existe versão contínua dele"
        )
    raw_clips = [c for c in raw_clips if not (c.get("_assembled") and not c["_segments"])]

    if compilation and not any(c["_segments"] for c in raw_clips):
        logger.warning(
            f"[{job_id}] Modo COMPILADO pedido, mas nenhum clipe saiu costurado — "
            f"a entrega vira {len(raw_clips)} clipe(s) individual(is)"
        )

    # Antes de filtrar: recuar o início alonga o clipe, então um corte que
    # perdeu o fato e ficou curto demais precisa ser resgatado enquanto ainda
    # está na lista.
    _rescue_event_starts(job_id, raw_clips, gaps or [], words, max_dur)

    filtered: List[dict] = []
    for c in raw_clips:
        axes = _axis_scores(c)
        score = _clip_score(c, axes)
        c["_axes"] = axes
        c["_score"] = score
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

    # A imagem entra por último, depois do filtro e antes do split: refinar um
    # candidato que seria descartado é desperdício, e refinar uma METADE de um
    # clipe já dividido não faz sentido — o acontecimento é do clipe inteiro.
    if video_path and settings.vision_enabled and filtered:
        await _refine_bounds_with_vision(
            job_id, video_path, filtered, words, max_dur
        )

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
            # Rede de segurança: o divisor corta em DUAS partes, então uma
            # janela absurda ainda sai absurda depois dele. Sem este teto um
            # engano de montagem virou render de 16 minutos.
            if part_dur > max_dur:
                logger.warning(
                    f"[{job_id}] Split part [{part['start']:.1f}-{part['end']:.1f}] "
                    f"descartada: {part_dur:.0f}s continua acima do teto de {max_dur}s"
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

    _warn_risky_wording(job_id, viral_clips)

    logger.info(f"[{job_id}] Final clips after split: {len(viral_clips)}")

    return AnalysisResult(clips=viral_clips, analysis_notes=analysis_notes)
