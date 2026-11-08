"""
O fim do clipe fecha a frase, e quem confirma isso é o áudio.

Os casos com nome de palavra vêm de clipes reais de um podcast: `foda.` termina
0,02s depois do corte pelo timestamp e mesmo assim saiu pela metade, porque o
áudio não parava ali; `mano?` tem um silêncio escondido dentro do timestamp.
"""

import math
import struct
import wave

import numpy as np
import pytest

from app.config import settings
from app.services.analyzer import (
    _close_clip_end,
    _confirmed_cut,
    _ends_sentence,
    _find_split_point,
    _split_clip,
)
from app.services.audio_events import AudioLevels, Gap, measure_levels

SPEECH_DB = -25.0
QUIET_DB = -60.0
STEP = 0.05


def _levels(total: float, quiet: list[tuple[float, float]] = (), loud: list[tuple[float, float]] = ()):
    """Áudio sintético: fala o tempo todo, menos nos trechos indicados."""
    values = np.full(int(total / STEP), SPEECH_DB, dtype=np.float32)
    for start, end in quiet:
        values[int(start / STEP):int(end / STEP)] = QUIET_DB
    for start, end in loud:
        values[int(start / STEP):int(end / STEP)] = SPEECH_DB + 10
    return AudioLevels(levels=values, speech_level=SPEECH_DB)


def _word(text: str, start: float, end: float | None = None) -> dict:
    return {"text": text, "start": start, "end": end if end is not None else start + 0.3}


def _clip(start: float, end: float, **extra) -> dict:
    return {"start": start, "end": end, "trim_reason": "", **extra}


def _close(clip, words, levels=None, gaps=(), min_dur=15, max_dur=90):
    _close_clip_end("job", clip, words, list(gaps), levels, min_dur, max_dur)
    return clip["end"]


# ─── O que conta como fim de frase ─────────────────────────────────────────────

@pytest.mark.parametrize("text", ["foda.", "mano?", "Nossa!", "assim…", "disse.\"", "fim.)"])
def test_reconhece_fim_de_frase(text):
    assert _ends_sentence(text)


@pytest.mark.parametrize("text", ["nunca", "assim,", "200.000", "foi—"])
def test_nao_e_fim_de_frase(text):
    assert not _ends_sentence(text)


# ─── A confirmação pelo áudio ──────────────────────────────────────────────────

def test_silencio_logo_depois_confirma():
    run = _confirmed_cut(_word("fim.", 20.0, 20.5), _levels(40, quiet=[(20.6, 21.5)]))
    assert run == pytest.approx((20.6, 21.5))


def test_fala_colada_nao_confirma():
    """`foda.` seguida de "Mas por que": pontuação certa, nada de pausa."""
    assert _confirmed_cut(_word("foda.", 20.0, 20.3), _levels(40)) is None


def test_silencio_escondido_no_fim_do_timestamp_confirma():
    """`mano?` dura 1,6s no timestamp, e o final dele é silêncio."""
    run = _confirmed_cut(_word("mano?", 20.0, 21.6), _levels(40, quiet=[(20.8, 21.6)]))
    assert run == pytest.approx((20.8, 21.6))


def test_silencio_no_comeco_do_timestamp_nao_confirma():
    """Com fala depois do silêncio, cortar ali comeria a palavra."""
    assert _confirmed_cut(_word("pé.", 20.0, 21.3), _levels(40, quiet=[(20.0, 20.9)])) is None


def test_silencio_antes_de_timestamp_atrasado_confirma():
    """`noite.` aparece depois de já ter sido dita, colada no fim do silêncio."""
    run = _confirmed_cut(_word("noite.", 21.0, 21.05), _levels(40, quiet=[(20.0, 21.0)]))
    assert run == pytest.approx((20.0, 21.0))


def test_sem_medicao_nao_ha_confirmacao():
    assert _confirmed_cut(_word("fim.", 20.0, 20.5), None) is None


# ─── Avanço e recuo ────────────────────────────────────────────────────────────

WORDS = [
    _word("Primeira", 1.0),
    _word("frase.", 25.0, 25.5),
    _word("Segunda", 26.0),
    _word("sem", 29.0),
    _word("fechar", 30.0),
    _word("agora.", 33.0, 33.5),
    _word("Depois", 34.5),
]


def test_avanca_ate_o_fim_de_frase_confirmado():
    levels = _levels(60, quiet=[(25.6, 25.95), (33.6, 34.4)])
    end = _close(_clip(0, 30.2), WORDS, levels)
    assert end == pytest.approx(33.6 + settings.end_breath)


def test_avancar_tem_prioridade_sobre_recuar():
    levels = _levels(60, quiet=[(25.6, 25.95), (33.6, 34.4)])
    assert _close(_clip(0, 30.2), WORDS, levels) > 30.2


def test_recua_quando_nao_ha_fim_a_frente_no_teto():
    words = WORDS[:5] + [_word("longe.", 40.0, 40.5)]
    levels = _levels(60, quiet=[(25.6, 25.95), (40.6, 41.0)])
    end = _close(_clip(0, 30.2), words, levels)
    assert end == pytest.approx(25.6 + settings.end_breath)


def test_confirmado_atras_vence_nao_confirmado_a_frente():
    """A escolha do dono: o que só a pontuação sustenta é o último recurso."""
    levels = _levels(60, quiet=[(25.6, 25.95)])
    end = _close(_clip(0, 30.2), WORDS, levels)
    assert end == pytest.approx(25.6 + settings.end_breath)


def test_sem_confirmacao_nenhuma_avanca_e_registra():
    clip = _clip(0, 30.2)
    end = _close(clip, WORDS, _levels(60))
    assert end == pytest.approx(33.5 + settings.end_breath)
    assert "SEM confirmação" in clip["trim_reason"]


def test_ja_fechado_e_confirmado_cai_no_silencio():
    """Corrige também o rabo morto: `end` bem depois de a fala ter parado."""
    words = [_word("Começo", 1.0), _word("fim.", 20.0, 20.4), _word("Outro", 23.0)]
    assert _close(_clip(0, 22.0), words, _levels(40, quiet=[(20.5, 22.9)])) == pytest.approx(
        20.5 + settings.end_breath
    )


def test_palavra_cruzando_o_corte_conta_como_a_ultima():
    """`foda.` começa antes do `end` e termina depois: é a frase que está aberta."""
    words = [_word("Começo", 1.0), _word("foi", 20.0), _word("foda.", 20.3, 20.72), _word("Mas", 21.5)]
    end = _close(_clip(0, 20.7), words, _levels(40, quiet=[(20.8, 21.4)]))
    assert end == pytest.approx(20.8 + settings.end_breath)


def test_nao_invade_a_palavra_seguinte():
    words = [_word("Começo", 1.0), _word("foda.", 20.0, 20.3), _word("Mas", 20.4)]
    assert _close(_clip(0, 20.1), words) == pytest.approx(20.4)


def test_respiro_nao_passa_do_fim_do_silencio():
    words = [_word("Começo", 1.0), _word("fim.", 20.0, 20.3), _word("Mas", 20.7)]
    levels = _levels(40, quiet=[(20.35, 20.65)])
    assert _close(_clip(0, 20.2), words, levels) == pytest.approx(20.6, abs=0.06)


# ─── Limites de duração ────────────────────────────────────────────────────────

def test_nao_avanca_alem_do_teto_de_duracao():
    levels = _levels(120, quiet=[(25.6, 25.95), (33.6, 34.4)])
    end = _close(_clip(0, 30.2), WORDS, levels, max_dur=32)
    assert end == pytest.approx(25.6 + settings.end_breath)


def test_nao_recua_abaixo_da_duracao_minima():
    words = [_word("Curta.", 5.0, 5.5), _word("Sem", 12.0), _word("fim", 13.0)]
    clip = _clip(0, 13.0)
    end = _close(clip, words, _levels(40, quiet=[(5.6, 6.0)]), min_dur=8)
    assert end == 13.0
    assert "Fim mantido" in clip["trim_reason"]


def test_avanco_respeita_o_teto_configurado(monkeypatch):
    monkeypatch.setattr(settings, "end_extend_max", 2.0)
    monkeypatch.setattr(settings, "end_retreat_max", 1.0)
    clip = _clip(0, 30.2)
    assert _close(clip, WORDS, _levels(60, quiet=[(33.6, 34.4)])) == 30.2


def test_recuo_respeita_o_teto_configurado(monkeypatch):
    monkeypatch.setattr(settings, "end_retreat_max", 2.0)
    monkeypatch.setattr(settings, "end_extend_max", 1.0)
    assert _close(_clip(0, 30.2), WORDS, _levels(60, quiet=[(25.6, 25.95)])) == 30.2


def test_nada_serve_mantem_e_registra():
    words = [_word("nada", 1.0), _word("fecha", 10.0), _word("aqui", 20.0)]
    clip = _clip(0, 20.5)
    assert _close(clip, words, _levels(40)) == 20.5
    assert "Fim mantido" in clip["trim_reason"]


def test_janela_que_sera_dividida_pode_passar_do_teto():
    """Quem precisa caber é cada parte; o teto vale para elas, no divisor."""
    words = [_word("Começo", 1.0), _word("sem", 100.0), _word("fim.", 103.0, 103.4)]
    end = _close(_clip(0, 100.5), words, _levels(200, quiet=[(103.5, 104.0)]), max_dur=90)
    assert end == pytest.approx(103.5 + settings.end_breath)


# ─── O que não pode ser mexido ─────────────────────────────────────────────────

def test_fim_da_imagem_nao_recua():
    words = [_word("Começo", 1.0), _word("fim.", 25.0, 25.5), _word("sem", 29.0)]
    clip = _clip(0, 29.5, _end_locked=True)
    assert _close(clip, words, _levels(60, quiet=[(25.6, 26.0)])) == 29.5


def test_fim_da_imagem_pode_avancar():
    clip = _clip(0, 30.2, _end_locked=True)
    assert _close(clip, WORDS, _levels(60, quiet=[(33.6, 34.4)])) == pytest.approx(
        33.6 + settings.end_breath
    )


def test_fim_em_evento_de_audio_fica():
    gap = Gap(start=25.5, end=30.0, loudness=-15.0, speech_level=SPEECH_DB)
    assert _close(_clip(0, 29.0), WORDS, _levels(60), gaps=[gap]) == 29.0


def test_fim_em_risada_curta_fica():
    """Curta demais para virar buraco de 3s, mas continua sendo a reação."""
    words = [_word("Começo", 1.0), _word("sem", 20.0, 20.3)]
    assert _close(_clip(0, 22.0), words, _levels(40, loud=[(20.4, 22.0)])) == 22.0


def test_clipe_sem_fala_nao_quebra():
    assert _close(_clip(100, 130), WORDS, _levels(200)) == 130


# ─── O divisor ─────────────────────────────────────────────────────────────────

def test_split_procura_fim_de_frase_alem_dos_10s_antes_de_cair_em_pausa():
    words = [
        _word("tem", 58.0, 58.3),
        _word("pausa", 59.0, 59.3),
        _word("depois", 60.0, 60.3),
        _word("fim.", 75.0, 75.3),
    ]
    assert _find_split_point(words, 60.0) == 75.3


def test_split_prefere_o_fim_confirmado_ao_mais_perto():
    words = [_word("perto.", 61.0, 61.3), _word("longe.", 70.0, 70.3), _word("Mais", 72.0)]
    levels = _levels(200, quiet=[(70.4, 71.0)])
    assert _find_split_point(words, 60.0, levels) == 70.3


def test_split_nao_escolhe_ponto_que_estoura_o_teto():
    """Uma parte acima do teto é descartada inteira depois do divisor."""
    words = [_word("fora.", 92.0, 92.3)]  # dentro da janela, mas a parte 1 estouraria
    parts = _split_clip(_clip(0, 170), words, 90, _levels(200), min_duration=15)
    assert [p["end"] - p["start"] for p in parts] == [85, 85]


def test_silencio_longo_chega_inteiro_a_parte_2():
    """O fim do silêncio é onde a parte 2 abre: não pode vir truncado pela busca."""
    words = [_word("fim.", 70.0, 70.3), _word("Eu", 74.0, 74.2)]
    parts = _split_clip(_clip(0, 140), words, 90, _levels(200, quiet=[(70.4, 73.9)]), min_duration=15)
    assert parts[1]["start"] == pytest.approx(73.9)


def test_parte_2_abre_na_primeira_palavra_e_nao_no_silencio():
    """Num clipe real a parte 2 abria com 0,69s mortos."""
    words = [_word("fim.", 70.0, 70.3), _word("Eu", 71.0, 71.2)]
    parts = _split_clip(_clip(0, 140), words, 90, _levels(200, quiet=[(70.4, 70.95)]), min_duration=15)
    assert parts[0]["end"] == pytest.approx(70.4 + settings.end_breath)
    assert parts[1]["start"] == pytest.approx(70.95)


def test_partes_nunca_se_sobrepoem():
    words = [_word("fim.", 70.0, 70.3), _word("Colada", 70.32, 70.6)]
    parts = _split_clip(_clip(0, 140), words, 90, _levels(200), min_duration=15)
    assert parts[0]["end"] <= parts[1]["start"]


# ─── A medição ─────────────────────────────────────────────────────────────────

def _write_wav(path, seconds_quiet_loud, rate=16000):
    """Trechos alternados: (duração, amplitude) em seno de 440 Hz."""
    frames = bytearray()
    t = 0
    for seconds, amplitude in seconds_quiet_loud:
        for _ in range(int(seconds * rate)):
            frames += struct.pack("<h", int(amplitude * 32767 * math.sin(2 * math.pi * 440 * t / rate)))
            t += 1
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(bytes(frames))


def test_mede_o_silencio_do_arquivo_de_verdade(tmp_path):
    path = tmp_path / "audio.wav"
    _write_wav(path, [(5.0, 0.2), (1.0, 0.0005), (5.0, 0.2)])
    words = [_word(f"p{i}", i * 0.5, i * 0.5 + 0.3) for i in range(10)]

    levels = measure_levels("job", str(path), words)

    assert levels is not None
    assert levels.speech_level == pytest.approx(-17, abs=1)
    runs = levels.quiet_runs(0, 11, 25.0, 0.5)
    assert len(runs) == 1
    assert runs[0][0] == pytest.approx(5.0, abs=0.06)
    assert runs[0][1] == pytest.approx(6.0, abs=0.06)


def test_arquivo_que_nao_existe_nao_derruba_o_job(tmp_path):
    assert measure_levels("job", str(tmp_path / "nada.wav"), []) is None


def test_sem_fala_para_calibrar_nao_mede(tmp_path):
    path = tmp_path / "audio.wav"
    _write_wav(path, [(2.0, 0.2)])
    assert measure_levels("job", str(path), []) is None
