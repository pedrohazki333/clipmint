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
    system, user = build_analysis_prompt(
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
    assert "7.0" in user
    assert "15" in system
    assert "90" in system


def test_build_analysis_prompt_not_empty():
    system, user = build_analysis_prompt(
        words=SAMPLE_WORDS,
        title="T", channel="C", duration_seconds=60,
        threshold=7.0, min_duration=15, max_duration=90,
    )
    assert len(system) > 100
    assert len(user) > 100
