"""
O começo do clipe se sustenta sozinho.

Os casos vêm de clipes reais de podcast: "Na verdade, eu perdi 200 mil..." teria
um gancho perfeito começando em "eu", e um deles mostrava outra pessoa nos
primeiros 0,4s, por causa de uma troca de câmera da fonte.
"""

import asyncio
from unittest.mock import AsyncMock, patch

import numpy as np
import pytest

from app.config import settings
from app.prompts.viral_analysis import source_criteria
from app.services.analyzer import (
    _clean_opening,
    _refine_bounds_with_vision,
    _rescue_event_starts,
    _snap_start,
    _start_after_fillers,
)
from app.services.audio_events import AudioLevels, Gap
from prompt_engine.prompt_builder import PromptBuilder


def _sentence(*texts: str, start: float = 10.0, step: float = 0.3) -> list[dict]:
    return [
        {"text": text, "start": start + i * step, "end": start + i * step + step}
        for i, text in enumerate(texts)
    ]


def _open(clip, words, cuts=(), video="v.mp4", min_dur=1, is_podcast=True, levels=None):
    with patch("app.services.analyzer.detect_cuts", AsyncMock(return_value=list(cuts))) as mock:
        asyncio.run(_clean_opening("job", clip, words, video, min_dur, is_podcast, levels))
    return mock


# ─── Muletas ───────────────────────────────────────────────────────────────────

def test_na_verdade_sai_do_comeco():
    words = _sentence("Na", "verdade,", "eu", "perdi", "200", "mil")
    assert _start_after_fillers(words, 10.0) == words[2]["start"]


@pytest.mark.parametrize("filler", ["Então", "Aí", "aí,", "Né,", "E"])
def test_muleta_de_sempre_sai_mesmo_sem_virgula(filler):
    words = _sentence(filler, "os", "cara", "vai")
    assert _start_after_fillers(words, 10.0) == words[1]["start"]


@pytest.mark.parametrize("filler", ["Olha,", "Bom,", "Assim,", "Tipo,", "Mano,", "Cara,", "Não,"])
def test_muleta_com_virgula_sai(filler):
    words = _sentence(filler, "eu", "perdi", "tudo")
    assert _start_after_fillers(words, 10.0) == words[1]["start"]


@pytest.mark.parametrize(
    "texts",
    [
        ("Olha", "o", "que", "ele", "fez"),
        ("Assim", "que", "eu", "cheguei"),
        ("Bom", "demais", "esse", "cara"),
        ("Tipo", "de", "coisa", "que"),
        ("Cara", "de", "pau", "total"),
        ("Não", "votei", "nele", "nunca"),
    ],
)
def test_muleta_sem_virgula_e_conteudo_e_fica(texts):
    assert _start_after_fillers(_sentence(*texts), 10.0) is None


def test_pausa_vale_como_a_virgula_que_a_transcricao_nao_pos():
    words = [
        {"text": "Olha", "start": 10.0, "end": 10.3},
        {"text": "eu", "start": 10.6, "end": 10.8},
        {"text": "perdi", "start": 10.8, "end": 11.0},
    ]
    assert _start_after_fillers(words, 10.0) == 10.6


def test_duas_muletas_seguidas_saem():
    words = _sentence("Não,", "na", "verdade,", "essa", "questão")
    assert _start_after_fillers(words, 10.0) == words[3]["start"]


def test_para_na_segunda_muleta():
    words = _sentence("Aí,", "mano,", "então,", "eu", "perdi")
    assert _start_after_fillers(words, 10.0) == words[2]["start"]


def test_limite_de_tempo_segura_a_remocao():
    """Uma muleta que demora é hesitação do falante, não uma muleta inofensiva."""
    words = [
        {"text": "Então,", "start": 10.0, "end": 10.3},
        {"text": "eu", "start": 12.0, "end": 12.2},
        {"text": "perdi", "start": 12.2, "end": 12.5},
    ]
    assert _start_after_fillers(words, 10.0) is None


def test_limites_vem_da_config(monkeypatch):
    monkeypatch.setattr(settings, "opening_filler_max_count", 1)
    words = _sentence("Aí,", "mano,", "eu", "perdi")
    assert _start_after_fillers(words, 10.0) == words[1]["start"]

    monkeypatch.setattr(settings, "opening_fillers", ["já"])
    monkeypatch.setattr(settings, "opening_fillers_need_pause", [])
    assert _start_after_fillers(_sentence("Aí,", "eu"), 10.0) is None
    assert _start_after_fillers(_sentence("Já", "eu"), 10.0) == 10.3


def test_nao_come_a_frase_inteira():
    assert _start_after_fillers(_sentence("Então"), 10.0) is None


def test_comeco_sem_muleta_nao_muda():
    assert _start_after_fillers(_sentence("Eu", "perdi", "tudo"), 10.0) is None


# ─── Início alinhado ───────────────────────────────────────────────────────────

def test_rabo_da_palavra_anterior_vai_para_a_seguinte():
    words = [
        {"text": "experiência?", "start": 228.9, "end": 229.51},
        {"text": "Na", "start": 229.51, "end": 229.7},
    ]
    assert _snap_start(words, 229.50) == 229.51


def test_comeco_da_palavra_recua_para_ela():
    words = [{"text": "Não,", "start": 155.58, "end": 155.72}]
    assert _snap_start(words, 155.60) == 155.58


def test_inicio_fora_de_palavra_nao_muda():
    assert _snap_start(_sentence("Eu"), 9.0) == 9.0


# ─── Clipe inteiro ─────────────────────────────────────────────────────────────

def test_no_podcast_abre_na_primeira_palavra_de_conteudo():
    words = _sentence("Na", "verdade,", "eu", "perdi")
    clip = {"start": 10.0, "end": 30.0, "trim_reason": ""}
    _open(clip, words)
    assert clip["start"] == words[2]["start"]
    assert "muleta" in clip["trim_reason"]


def test_no_gameplay_a_muleta_fica():
    """"Olha," é a preparação que o prompt do gameplay manda incluir."""
    words = _sentence("Olha,", "o", "que", "vai", "acontecer")
    clip = {"start": 10.0, "end": 30.0, "trim_reason": ""}
    mock = _open(clip, words, cuts=[0.1], is_podcast=False)
    assert clip["start"] == 10.0
    mock.assert_not_called()


def test_no_gameplay_o_inicio_tambem_sai_de_dentro_da_palavra():
    words = _sentence("palavra", "seguinte", "aqui")
    clip = {"start": 10.25, "end": 30.0, "trim_reason": ""}
    _open(clip, words, is_podcast=False)
    assert clip["start"] == words[1]["start"]


@pytest.mark.parametrize("cuts", [[], [0.05]])
def test_inicio_travado_nao_se_move(cuts):
    words = _sentence("Na", "verdade,", "eu", "perdi")
    clip = {"start": 10.0, "end": 30.0, "trim_reason": "", "_start_locked": True}
    mock = _open(clip, words, cuts=cuts)
    assert clip["start"] == 10.0
    mock.assert_not_called()


def test_resgate_por_audio_trava_o_inicio():
    """Abrir na reação sem o fato é o erro que o resgate existe para impedir."""
    gap = Gap(start=20.0, end=30.0, loudness=-10.0, speech_level=-25.0)
    words = _sentence("Então,", "olha", "isso", start=15.0)
    clip = {"start": 31.0, "end": 60.0, "trim_reason": ""}
    _rescue_event_starts("job", [clip], [gap], words, 90)
    resgatado = clip["start"]
    assert clip["_start_locked"] is True

    _open(clip, words)
    assert clip["start"] == resgatado


def test_imagem_que_recua_o_inicio_trava():
    scene = type("Scene", (), {"event_start": 12.0, "event_end": None, "summary": lambda self: "x"})()
    words = _sentence("Então,", "olha", "isso", start=11.5)
    clip = {"start": 20.0, "end": 40.0, "trim_reason": ""}
    with patch("app.services.analyzer.vision.look_many", AsyncMock(return_value=[scene])):
        asyncio.run(_refine_bounds_with_vision("job", "v.mp4", [clip], words, 90))
    assert clip["_start_locked"] is True
    assert "_end_locked" not in clip


def test_imagem_que_nao_mexe_no_inicio_nao_trava():
    scene = type("Scene", (), {"event_start": None, "event_end": 50.0, "summary": lambda self: "x"})()
    clip = {"start": 20.0, "end": 40.0, "trim_reason": ""}
    with patch("app.services.analyzer.vision.look_many", AsyncMock(return_value=[scene])):
        asyncio.run(_refine_bounds_with_vision("job", "v.mp4", [clip], [], 90))
    assert "_start_locked" not in clip
    assert clip["_end_locked"] is True


def test_nao_encurta_abaixo_da_duracao_minima():
    words = _sentence("Então,", "eu", "perdi")
    clip = {"start": 10.0, "end": 12.0, "trim_reason": ""}
    _open(clip, words, min_dur=2)
    assert clip["start"] == 10.0


# ─── Troca de câmera ───────────────────────────────────────────────────────────

def test_troca_de_camera_antes_da_fala_avanca_o_inicio():
    words = [{"text": "Eu", "start": 10.5, "end": 10.7}]
    clip = {"start": 10.0, "end": 30.0, "trim_reason": ""}
    mock = _open(clip, words, cuts=[0.3])
    assert clip["start"] == pytest.approx(10.34)
    assert mock.await_args.kwargs == {"start": 10.0, "duration": settings.opening_scene_window}


def test_troca_de_camera_dentro_da_palavra_mantem_o_inicio():
    words = [{"text": "Eu", "start": 10.0, "end": 10.5}]
    clip = {"start": 10.0, "end": 30.0, "trim_reason": ""}
    _open(clip, words, cuts=[0.3])
    assert clip["start"] == 10.0


def test_troca_de_camera_nao_pula_palavra_inteira_antes_dela():
    """O caso real: pular até a troca comia "eu perdi 200 mil seguidores"."""
    words = [
        {"text": "eu", "start": 10.0, "end": 10.1},
        {"text": "perdi", "start": 10.1, "end": 10.2},
        {"text": "tudo", "start": 11.0, "end": 11.3},
    ]
    clip = {"start": 10.0, "end": 30.0, "trim_reason": ""}
    _open(clip, words, cuts=[0.3])
    assert clip["start"] == 10.0


def test_troca_de_camera_com_fala_no_audio_e_nao_no_timestamp_mantem():
    """Timestamp espremido: nenhuma palavra no trecho, e o áudio segue falando."""
    levels = AudioLevels(levels=np.full(800, -25.0, dtype=np.float32), speech_level=-25.0)
    words = [{"text": "Eu", "start": 10.5, "end": 10.7}]
    clip = {"start": 10.0, "end": 30.0, "trim_reason": ""}
    _open(clip, words, cuts=[0.3], levels=levels)
    assert clip["start"] == 10.0


def test_troca_de_camera_com_silencio_no_audio_avanca():
    values = np.full(800, -25.0, dtype=np.float32)
    values[int(10.0 / 0.05):int(10.5 / 0.05)] = -60.0
    levels = AudioLevels(levels=values, speech_level=-25.0)
    words = [{"text": "Eu", "start": 10.5, "end": 10.7}]
    clip = {"start": 10.0, "end": 30.0, "trim_reason": ""}
    _open(clip, words, cuts=[0.3], levels=levels)
    assert clip["start"] == pytest.approx(10.34)


def test_troca_de_camera_nao_passa_da_palavra():
    words = [{"text": "Eu", "start": 10.32, "end": 10.5}]
    clip = {"start": 10.0, "end": 30.0, "trim_reason": ""}
    _open(clip, words, cuts=[0.3])
    assert clip["start"] == pytest.approx(10.32)


def test_considera_o_inicio_depois_de_tirar_a_muleta():
    """No clipe real a troca caía dentro de `verdade,`: sair a muleta já resolve."""
    words = _sentence("Na", "verdade,", "eu", "perdi")
    clip = {"start": 10.0, "end": 30.0, "trim_reason": ""}
    mock = _open(clip, words)
    assert mock.await_args.kwargs["start"] == words[2]["start"]


def test_sem_video_nao_procura_troca():
    words = _sentence("Eu", "perdi")
    clip = {"start": 10.0, "end": 30.0, "trim_reason": ""}
    mock = _open(clip, words, video=None)
    mock.assert_not_called()


# ─── O prompt ──────────────────────────────────────────────────────────────────

def _system(source: str) -> str:
    return PromptBuilder().build(
        min_duration=15,
        max_duration=90,
        preferred_min=25,
        preferred_max=40,
        source_criteria=source_criteria(source),
    )


def test_prompt_exige_primeira_frase_que_se_sustenta():
    assert "quem nunca viu este vídeo" in _system("gameplay")
    assert "quem nunca viu este vídeo" in _system("podcast")


def test_abertura_na_afirmacao_de_impacto_e_so_do_podcast():
    """No gameplay o core manda começar na preparação, e isto a contradiria."""
    assert "eu perdi 200 mil seguidores numa noite" in _system("podcast")
    assert "eu perdi 200 mil seguidores numa noite" not in _system("gameplay")


def test_prompt_exige_fechar_o_raciocinio():
    assert "fechando o raciocínio" in _system("podcast")
    assert "Termine em frase completa ou pausa natural" not in _system("podcast")
