"""
Testes básicos do analisador de viralidade.

Testa a lógica de parsing, splitting e formatação de prompt
sem fazer chamadas reais ao Claude API.
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.prompts.viral_analysis import (
    format_transcript_with_timestamps,
    format_duration,
    build_analysis_prompt,
)
from app.services.analyzer import (
    AXIS_WEIGHTS,
    _axis_scores,
    _clip_score,
    _find_split_point,
    _split_clip,
    _parse_claude_response,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────

SAMPLE_WORDS = [
    {"text": "Hello", "start": 0.0, "end": 0.5, "confidence": 0.99},
    {"text": "everyone", "start": 0.6, "end": 1.1, "confidence": 0.98},
    {"text": "today", "start": 1.2, "end": 1.6, "confidence": 0.97},
    {"text": "we", "start": 1.7, "end": 1.9, "confidence": 0.99},
    {"text": "talk", "start": 2.0, "end": 2.3, "confidence": 0.98},
    {"text": "about", "start": 2.4, "end": 2.7, "confidence": 0.97},
    {"text": "virality.", "start": 2.8, "end": 3.5, "confidence": 0.95},
    {"text": "It", "start": 4.0, "end": 4.2, "confidence": 0.99},
    {"text": "is", "start": 4.3, "end": 4.5, "confidence": 0.99},
    {"text": "fascinating!", "start": 4.6, "end": 5.2, "confidence": 0.96},
]


# ─── Testes de formatação ──────────────────────────────────────────────────────

def test_format_duration_seconds():
    assert format_duration(65) == "1:05"


def test_format_duration_hours():
    assert format_duration(3661) == "1:01:01"


def test_format_duration_zero():
    assert format_duration(0) == "0:00"


def test_format_transcript_groups_words():
    result = format_transcript_with_timestamps(SAMPLE_WORDS)
    assert "[" in result
    assert "Hello" in result
    # Deve ter pelo menos uma quebra de linha (múltiplos grupos)
    assert "\n" in result


def test_format_transcript_empty():
    result = format_transcript_with_timestamps([])
    assert result == "(empty transcript)"


def test_format_transcript_sentence_break():
    """Garante que fim de frase (.) quebra o grupo."""
    result = format_transcript_with_timestamps(SAMPLE_WORDS)
    lines = result.split("\n")
    # "virality." deve terminar um grupo
    has_virality_line = any("virality." in line for line in lines)
    assert has_virality_line


# ─── Testes de splitting ───────────────────────────────────────────────────────

def test_split_clip_no_split_needed():
    clip = {"start": 0.0, "end": 60.0, "score": 8.0, "hook": "", "suggested_title": "", "reason": "", "tags": []}
    result = _split_clip(clip, SAMPLE_WORDS, max_duration=90)
    assert len(result) == 1
    assert result[0] == clip


def test_split_clip_splits_long_clip():
    clip = {
        "start": 0.0, "end": 120.0, "score": 8.0,
        "hook": "Test", "suggested_title": "Test title",
        "reason": "Long clip", "tags": ["test"],
    }
    # Palavras no intervalo 0-120s
    words = [
        {"text": "word.", "start": 55.0, "end": 56.0, "confidence": 0.9},
        {"text": "next", "start": 58.0, "end": 59.0, "confidence": 0.9},
    ]
    result = _split_clip(clip, words, max_duration=90)
    assert len(result) == 2
    assert result[0]["part_number"] == 1
    assert result[1]["part_number"] == 2
    assert result[0]["end"] == result[1]["start"]  # corte consistente
    assert result[0]["parent_start"] == 0.0
    assert result[1]["parent_start"] == 0.0


def test_find_split_point_prefers_sentence_end():
    words = [
        {"text": "hello", "start": 55.0, "end": 56.0, "confidence": 0.9},
        {"text": "world.", "start": 57.0, "end": 58.0, "confidence": 0.9},  # fim de frase
        {"text": "foo", "start": 62.0, "end": 63.0, "confidence": 0.9},
    ]
    result = _find_split_point(words, target_time=60.0)
    assert result == 58.0  # fim de frase mais próximo


# ─── Testes de parsing ─────────────────────────────────────────────────────────

def test_parse_claude_response_plain_json():
    data = {"clips": [], "analysis_notes": "test"}
    raw = json.dumps(data)
    result = _parse_claude_response(raw)
    assert result == data


def test_parse_claude_response_with_markdown():
    data = {"clips": [], "analysis_notes": "test"}
    raw = f"```json\n{json.dumps(data)}\n```"
    result = _parse_claude_response(raw)
    assert result == data


def test_parse_claude_response_invalid_json():
    with pytest.raises(json.JSONDecodeError):
        _parse_claude_response("this is not json")


# ─── Testes do prompt builder ──────────────────────────────────────────────────

def test_build_analysis_prompt_contains_metadata():
    user = build_analysis_prompt(
        words=SAMPLE_WORDS,
        title="My Video",
        channel="Test Channel",
        duration_seconds=300,
        threshold=7.0,
        min_duration=15,
        max_duration=90,
    )
    assert "My Video" in user
    assert "Test Channel" in user
    # O threshold vai para o prompt na escala do final_score (0-100)
    assert "70" in user


def test_build_analysis_prompt_not_empty():
    user = build_analysis_prompt(
        words=SAMPLE_WORDS,
        title="T", channel="C", duration_seconds=60,
        threshold=7.0, min_duration=15, max_duration=90,
    )
    assert len(user) > 100


def test_build_analysis_prompt_switches_rubric_by_source():
    """Corte de podcast e de gameplay não são avaliados pelos mesmos critérios."""
    from app.prompts.viral_analysis import source_criteria

    podcast = build_analysis_prompt(
        words=SAMPLE_WORDS, title="T", channel="C", duration_seconds=60,
        threshold=7.0, min_duration=15, max_duration=90, source_type="podcast",
    )
    gameplay = build_analysis_prompt(
        words=SAMPLE_WORDS, title="T", channel="C", duration_seconds=60,
        threshold=7.0, min_duration=15, max_duration=90, source_type="gameplay",
    )

    assert "podcast" in podcast
    assert "gameplay" in gameplay
    assert "Frase-momento" in source_criteria("podcast")
    assert "Legibilidade sem áudio" in source_criteria("gameplay")
    # Tipo desconhecido não pode quebrar a análise
    assert source_criteria(None) == source_criteria("podcast")
    assert source_criteria("outra-coisa") == source_criteria("podcast")


# ─── Testes da rubrica de cinco eixos ──────────────────────────────────────────

FULL_AXES = {
    "hook_score": 9,
    "retention_score": 8,
    "shareability_score": 7,
    "loopability_score": 6,
    "comment_bait_score": 5,
}


def test_clip_score_recomputes_weighted_average():
    """
    A nota sai dos eixos, não do final_score que o modelo escreveu.

    LLM erra média ponderada com frequência, e o cronograma escolhe clipe por
    eixo — a nota geral tem que ser coerente com os eixos que ela resume.
    """
    clip = dict(FULL_AXES, final_score=99)  # aritmética errada de propósito
    axes = _axis_scores(clip)

    # 8*.30 + 9*.25 + 7*.20 + 5*.15 + 6*.10 = 7.4
    assert _clip_score(clip, axes) == pytest.approx(7.4)


def test_clip_score_falls_back_to_final_score():
    """Sem os eixos completos, o final_score (0-100) vira a nota 0-10."""
    clip = {"final_score": 82, "hook_score": 9}
    assert _clip_score(clip, _axis_scores(clip)) == pytest.approx(8.2)


def test_clip_score_falls_back_to_legacy_field():
    """Resposta no formato antigo continua sendo entendida."""
    clip = {"score": 8.6}
    assert _clip_score(clip, _axis_scores(clip)) == pytest.approx(8.6)


def test_clip_score_survives_garbage():
    assert _clip_score({}, {}) == 0.0
    assert _clip_score({"score": "não é número"}, {}) == 0.0


def test_axis_scores_clamps_out_of_range():
    """Eixo fora de 0-10 não pode contaminar a ordenação do cronograma."""
    axes = _axis_scores(dict(FULL_AXES, hook_score=42, retention_score=-3))
    assert axes["hook_score"] == 10.0
    assert axes["retention_score"] == 0.0


def test_axis_scores_ignores_missing_and_invalid():
    axes = _axis_scores({"hook_score": 7, "retention_score": None, "shareability_score": "x"})
    assert axes == {"hook_score": 7.0}


def test_axis_weights_sum_to_one():
    assert sum(AXIS_WEIGHTS.values()) == pytest.approx(1.0)


def test_siege_rubric_targets_r6_moments():
    """
    A aba de Siege existe porque o que vira clipe em R6 é específico:
    sequência de abates, morte rápida de um tiro, clutch e treta na call.
    """
    from app.prompts.viral_analysis import SOURCE_TYPES, source_criteria

    siege = source_criteria("siege")

    assert "siege" in SOURCE_TYPES
    for termo in ("Sequência de eliminações", "um tiro", "Clutch", "Treta"):
        assert termo in siege, termo
    # Só existe transcrição: a rubrica precisa dizer como inferir a jogada
    assert "SOMENTE a transcrição" in siege
    # A nota vem da qualidade dos abates, não de quantos nem de quão rápidos:
    # um 4k com quatro abates bonitos vale mais que um triplo relâmpago sortudo.
    assert "QUALIDADE de cada abate" in siege
    # Jogada espalhada não perde nota — quem se ajusta é o corte
    assert "derruba o CORTE" in siege
    assert "segments" in siege
    # E não pode ser confundida com as outras
    assert siege != source_criteria("gameplay")
    assert siege != source_criteria("podcast")


def test_siege_prompt_is_assembled_end_to_end():
    """O prompt do sistema monta com a rubrica de Siege, sem placeholder solto."""
    import re

    from prompt_engine.prompt_builder import PromptBuilder
    from app.prompts.viral_analysis import source_criteria

    system = PromptBuilder().build(
        min_duration=15, max_duration=90, source_criteria=source_criteria("siege")
    )
    user = build_analysis_prompt(
        words=SAMPLE_WORDS, title="T", channel="C", duration_seconds=60,
        threshold=7.0, min_duration=15, max_duration=90, source_type="siege",
    )

    assert "Sequência de eliminações" in system
    assert re.findall(r"{[a-z_]+}", system) == []
    assert "siege" in user


# ─── Clipes costurados (só Siege) ─────────────────────────────────────────────

def test_parse_segments_accepts_a_valid_ace():
    """Ace espalhado pelo round vira três trechos emendados."""
    from app.services.analyzer import parse_segments

    got = parse_segments([[1820.4, 1834.0], [1851.2, 1863.5], [1879.0, 1892.4]])

    assert got == [(1820.4, 1834.0), (1851.2, 1863.5), (1879.0, 1892.4)]


def test_parse_segments_drops_blinks_and_disorder():
    """Trecho curtíssimo vira piscada; fora de ordem ou sobreposto é lixo."""
    from app.services.analyzer import parse_segments

    assert parse_segments([[10.0, 11.0], [20.0, 25.0], [30.0, 36.0]]) == [
        (20.0, 25.0), (30.0, 36.0)
    ]
    # Segundo trecho começa antes de o primeiro acabar
    assert parse_segments([[10.0, 30.0], [25.0, 40.0]]) == []


def test_parse_segments_caps_the_total_duration():
    """
    O clipe tem que ficar perto de um minuto, não do round inteiro.

    Trechos que estouram o teto são cortados fora em vez de a lista ser
    descartada — o começo da jogada é o que se perde, como manda a rubrica.
    """
    from app.services.analyzer import parse_segments

    got = parse_segments([[0, 30], [40, 70], [80, 110], [120, 150]])

    assert got == [(0.0, 30.0), (40.0, 70.0)]  # 60s; o terceiro passaria de 70


def test_parse_segments_needs_at_least_two():
    """Um trecho só não é costura — é corte contínuo comum."""
    from app.services.analyzer import parse_segments

    assert parse_segments([[10.0, 40.0]]) == []
    assert parse_segments(None) == []
    assert parse_segments("não é lista") == []
    assert parse_segments([["a", "b"], [1, 2]]) == []


def test_remap_words_follows_the_stitched_timeline():
    """
    A legenda tem que acompanhar a emenda.

    Palavra do tempo morto descartado some junto — senão a legenda mostraria
    fala que não está mais no vídeo.
    """
    from app.services.segments import remap_words, total_duration

    words = [
        {"text": "peguei", "start": 10.0, "end": 10.5},
        {"text": "morto", "start": 25.0, "end": 25.4},   # cai no buraco
        {"text": "ace", "start": 50.0, "end": 50.6},
    ]
    segments = [(8.0, 14.0), (48.0, 54.0)]

    got = remap_words(words, segments)

    assert [w["text"] for w in got] == ["peguei", "ace"]
    assert got[0]["start"] == pytest.approx(2.0)    # 10.0 - 8.0
    assert got[1]["start"] == pytest.approx(8.0)    # 6.0 (1º trecho) + 50.0-48.0
    assert total_duration(segments) == pytest.approx(12.0)


# ─── O fato e a reação ─────────────────────────────────────────────────────────
# Corte que começa depois do momento é o erro mais caro do sistema: entrega a
# risada sem a piada. Ver services/audio_events.py.

def test_rescue_move_o_inicio_para_antes_do_fato():
    from app.services.analyzer import _rescue_event_starts
    from app.services.audio_events import Gap

    words = [
        {"text": "Você", "start": 20.0, "end": 20.4},
        {"text": "joga", "start": 20.5, "end": 21.0},
        {"text": "no", "start": 22.5, "end": 22.8},
        {"text": "mar.", "start": 24.3, "end": 26.0},
        # buraco alto de 20s: o momento em si
        {"text": "Finalmente!", "start": 46.0, "end": 47.0},
    ]
    gap = Gap(start=26.0, end=46.0, loudness=-14.0, speech_level=-27.0)
    clips = [{"start": 46.0, "end": 90.0, "_segments": [], "trim_reason": "corte enxuto"}]

    _rescue_event_starts("job", clips, [gap], words, max_duration=90)

    assert clips[0]["start"] == 20.0            # volta para antes do fato
    assert clips[0]["end"] == 90.0              # o fim não é tocado
    assert "corte enxuto" in clips[0]["trim_reason"]
    assert "reação sem o fato" in clips[0]["trim_reason"]


def test_rescue_nao_toca_em_clipe_costurado():
    """A lista de segmentos já define a linha do tempo — mexer no start a quebra."""
    from app.services.analyzer import _rescue_event_starts
    from app.services.audio_events import Gap

    words = [{"text": "Finalmente!", "start": 46.0, "end": 47.0}]
    gap = Gap(start=26.0, end=46.0, loudness=-14.0, speech_level=-27.0)
    clips = [{"start": 46.0, "end": 90.0, "_segments": [(46.0, 60.0), (70.0, 90.0)]}]

    _rescue_event_starts("job", clips, [gap], words, max_duration=90)

    assert clips[0]["start"] == 46.0


def test_rescue_sem_medicao_de_audio_e_no_op():
    """Vídeo sem leitura de loudness segue analisado só pelo texto, como antes."""
    from app.services.analyzer import _rescue_event_starts

    clips = [{"start": 46.0, "end": 90.0, "_segments": []}]
    _rescue_event_starts("job", clips, [], [], max_duration=90)
    assert clips[0]["start"] == 46.0


def test_prompt_anota_buraco_alto_para_o_modelo():
    """O buraco barulhento chega ao Claude como momento, não como ausência."""
    from app.services.audio_events import Gap

    gap = Gap(start=3.6, end=30.0, loudness=-14.0, speech_level=-27.0)
    user = build_analysis_prompt(
        words=SAMPLE_WORDS, title="T", channel="C", duration_seconds=60,
        threshold=7.0, min_duration=15, max_duration=90, gaps=[gap],
    )

    assert "ÁUDIO ALTO" in user
    assert "parênteses duplos" in user       # a legenda explicando a anotação
    assert "FATO" in user and "REAÇÃO" in user


def test_prompt_sem_gaps_nao_menciona_anotacao():
    user = build_analysis_prompt(
        words=SAMPLE_WORDS, title="T", channel="C", duration_seconds=60,
        threshold=7.0, min_duration=15, max_duration=90,
    )
    assert "parênteses duplos" not in user


def test_core_prompt_manda_incluir_o_fato():
    """A regra que evita o corte só-reação vive no system prompt."""
    from prompt_engine.prompt_builder import PromptBuilder

    system = PromptBuilder().build(min_duration=15, max_duration=90)

    assert "O fato e a reação" in system
    assert "ÁUDIO ALTO" in system
    # E a estratégia de duração não pode mais justificar cortar o momento fora
    assert "nunca justifica deixar o fato de fora" in system
