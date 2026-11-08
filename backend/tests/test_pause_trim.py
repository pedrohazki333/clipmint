"""
Sem tempo morto no meio do clipe de podcast, e com a risada intacta.

Os silêncios dos clipes reais estavam aos 3,10s e aos 5,90s, dentro do timestamp
das palavras: nenhum aparece como vão entre palavras, e por isso a pausa é medida no
áudio. Um vão de 2,85s no mesmo vídeo era fala, com as palavras espremidas noutro
lugar.
"""

import asyncio
from unittest.mock import AsyncMock, patch

import numpy as np
import pytest

from app.config import settings
from app.services.analyzer import _trim_clip_pauses, _trim_pauses
from app.services.audio_events import AudioLevels
from app.services.segments import (
    compact_segments,
    remap_words,
    remap_words_keeping,
    segments_without_pauses,
    total_duration,
)
from app.services.subtitler import generate_ass_subtitles
from app.workers.pipeline import _stitched_words

SPEECH_DB = -25.0
QUIET_DB = -60.0
STEP = 0.05


def _levels(total: float, quiet=(), loud=(), custom=()):
    values = np.full(int(total / STEP), SPEECH_DB, dtype=np.float32)
    for start, end in quiet:
        values[int(start / STEP):int(end / STEP)] = QUIET_DB
    for start, end in loud:
        values[int(start / STEP):int(end / STEP)] = SPEECH_DB + 10
    for start, end, level in custom:
        values[int(start / STEP):int(end / STEP)] = level
    return AudioLevels(levels=values, speech_level=SPEECH_DB)


def _clip(start=10.0, end=40.0, **extra):
    return {"start": start, "end": end, "trim_reason": "", "_segments": [], **extra}


# ─── Os trechos ────────────────────────────────────────────────────────────────

def test_quebra_deixando_margem_de_cada_lado():
    assert segments_without_pauses(0, 30, [(10.0, 12.0)], 0.12) == [(0, 10.12), (11.88, 30)]


def test_varias_pausas():
    segments = segments_without_pauses(0, 30, [(5.0, 6.0), (20.0, 21.0)], 0.1)
    assert segments == [(0, 5.1), (5.9, 20.1), (20.9, 30)]


def test_sem_pausa_o_intervalo_fica_inteiro():
    assert segments_without_pauses(5, 30, [], 0.12) == [(5, 30)]


def test_pausa_no_inicio_sai_sem_margem_antes():
    assert segments_without_pauses(5, 30, [(5.0, 6.0)], 0.1) == [(5.9, 30)]


def test_pausa_no_fim_sai_sem_margem_depois():
    assert segments_without_pauses(5, 30, [(29.0, 30.0)], 0.1) == [(5, 29.1)]


def test_pausa_menor_que_as_margens_fica():
    assert segments_without_pauses(0, 30, [(10.0, 10.2)], 0.12) == [(0, 30)]


# ─── O que sai ─────────────────────────────────────────────────────────────────

def test_silencio_sai_e_vira_trechos():
    clip = _clip()
    _trim_pauses("job", clip, _levels(60, quiet=[(20.0, 21.0)]), 15)
    assert np.allclose(clip["_segments"], [(10.0, 20.12), (20.88, 40.0)])
    assert "0.8s" in clip["trim_reason"]


def test_a_duracao_soma_o_que_ficou():
    clip = _clip()
    _trim_pauses("job", clip, _levels(60, quiet=[(20.0, 21.0), (30.0, 31.0)]), 15)
    assert total_duration(clip["_segments"]) == pytest.approx(30 - 2 * (1 - 2 * settings.trim_pause_margin))


def test_risada_nao_sai():
    """O melhor do corte: sem palavra nenhuma e acima do nível de fala."""
    clip = _clip()
    _trim_pauses("job", clip, _levels(60, loud=[(20.0, 23.0)]), 15)
    assert clip["_segments"] == []


def test_conversa_ao_fundo_nao_sai():
    """-40 dBFS numa pausa é sala com gente, e não silêncio: medido no vídeo real."""
    clip = _clip()
    _trim_pauses("job", clip, _levels(60, custom=[(20.0, 21.0, -40.0)]), 15)
    assert clip["_segments"] == []


def test_so_o_silencio_de_verdade_sai_de_um_trecho_misto():
    clip = _clip()
    levels = _levels(60, quiet=[(20.0, 21.0)], loud=[(21.0, 23.0)])
    _trim_pauses("job", clip, levels, 15)
    assert np.allclose(clip["_segments"], [(10.0, 20.12), (20.88, 40.0)])


def test_pausa_curta_fica(monkeypatch):
    clip = _clip()
    _trim_pauses("job", clip, _levels(60, quiet=[(20.0, 20.4)]), 15)
    assert clip["_segments"] == []

    monkeypatch.setattr(settings, "trim_pause_min", 0.3)
    _trim_pauses("job", clip, _levels(60, quiet=[(20.0, 20.8)]), 15)
    assert len(clip["_segments"]) == 2


def test_remocao_pequena_nao_compensa_a_emenda():
    """0,5s de pausa menos as margens são 0,26s: abaixo de 0,3s."""
    clip = _clip()
    _trim_pauses("job", clip, _levels(60, quiet=[(20.0, 20.5)]), 15)
    assert clip["_segments"] == []
    assert clip["trim_reason"] == ""


def test_nao_deixa_abaixo_da_duracao_minima():
    clip = _clip(10.0, 26.0)
    _trim_pauses("job", clip, _levels(60, quiet=[(20.0, 22.0)]), 15)
    assert clip["_segments"] == []


def test_so_uma_pausa_no_comeco_nao_costura():
    clip = _clip()
    _trim_pauses("job", clip, _levels(60, quiet=[(10.0, 11.0)]), 15)
    assert clip["_segments"] == []
    assert clip["start"] == pytest.approx(10.88)


# ─── Quando vale ───────────────────────────────────────────────────────────────

def _run(source="podcast", mode="individual", clip=None, levels="padrão"):
    clip = clip or _clip()
    levels = _levels(60, quiet=[(20.0, 21.0)]) if levels == "padrão" else levels
    _trim_clip_pauses("job", [clip], levels, 15, source, mode)
    return clip


def test_ligado_no_podcast():
    assert _run()["_segments"]


@pytest.mark.parametrize("source", ["gameplay", "siege"])
def test_desligado_fora_do_podcast(source):
    assert _run(source=source)["_segments"] == []


def test_desligado_no_compilado():
    assert _run(mode="compilation")["_segments"] == []


def test_flag_desliga(monkeypatch):
    monkeypatch.setattr(settings, "trim_pauses_enabled", False)
    assert _run()["_segments"] == []


def test_ligada_por_padrao():
    assert settings.model_fields["trim_pauses_enabled"].default is True


def test_clipe_ja_costurado_passa_intacto():
    original = [(10.0, 15.0), (30.0, 40.0)]
    assert _run(clip=_clip(_segments=list(original)))["_segments"] == original


def test_sem_medicao_de_audio_nao_mexe():
    assert _run(levels=None)["_segments"] == []


# ─── As legendas ───────────────────────────────────────────────────────────────

def _word(text, start, end):
    return {"text": text, "start": start, "end": end}


SEGMENTS = [(10.0, 20.0), (22.0, 30.0)]


def test_palavra_normal_cai_na_linha_nova():
    moved = remap_words_keeping([_word("depois", 25.0, 25.5)], SEGMENTS)[0]
    assert moved["start"] == pytest.approx(13.0)
    assert moved["end"] == pytest.approx(13.5)


def test_palavra_com_timestamp_no_silencio_fica_na_legenda():
    """`para noite.` aparece num silêncio de 1s, dita logo antes dele."""
    moved = remap_words_keeping([_word("noite.", 20.5, 20.6)], SEGMENTS)
    assert [w["text"] for w in moved] == ["noite."]
    assert moved[0]["start"] == pytest.approx(10.0)
    assert moved[0]["end"] - moved[0]["start"] == pytest.approx(0.05)


def test_palavra_que_cruza_a_emenda_fica():
    moved = remap_words_keeping([_word("pé.", 19.0, 23.0)], SEGMENTS)[0]
    assert moved["start"] == pytest.approx(9.0)
    assert moved["end"] == pytest.approx(11.0)


def test_remap_antigo_descartaria_as_mesmas_palavras():
    """É a razão de existir um segundo remap, e o Siege continua com o antigo."""
    words = [_word("noite.", 20.5, 20.6), _word("pé.", 19.0, 23.0)]
    assert remap_words(words, SEGMENTS) == []


def test_nenhuma_palavra_some_e_a_ordem_se_mantem():
    words = [_word(f"p{i}", 10.0 + i * 0.5, 10.0 + i * 0.5 + 0.3) for i in range(39)]
    moved = remap_words_keeping(words, SEGMENTS)
    assert [w["text"] for w in moved] == [w["text"] for w in words]
    starts = [w["start"] for w in moved]
    assert starts == sorted(starts)
    assert all(w["end"] <= total_duration(SEGMENTS) for w in moved)


def test_palavra_fora_do_clipe_nao_entra():
    words = [_word("antes", 5.0, 5.3), _word("depois", 31.0, 31.3)]
    assert remap_words_keeping(words, SEGMENTS) == []


def test_ultima_palavra_cabe_na_duracao():
    moved = remap_words_keeping([_word("fim.", 29.99, 31.0)], SEGMENTS)[0]
    assert moved["end"] <= total_duration(SEGMENTS)
    assert moved["start"] < moved["end"]


def test_podcast_preserva_e_siege_descarta():
    words = [_word("noite.", 20.5, 20.6)]
    assert _stitched_words(words, SEGMENTS, "podcast", "individual")
    assert _stitched_words(words, SEGMENTS, "siege", "individual") == []
    assert _stitched_words(words, SEGMENTS, "podcast", "compilation") == []


# ─── A legenda do corte contínuo ───────────────────────────────────────────────

def test_ultima_palavra_com_timestamp_alem_do_corte_aparece(tmp_path):
    """O corte cai no silêncio escondido em `mano?`, que foi dita inteira antes dele."""
    words = [_word("Eu", 1.0, 1.3), _word("mano?", 1.3, 3.0)]
    output = tmp_path / "legenda.ass"
    generate_ass_subtitles(words, 0.0, 2.0, "traditional", str(output))
    assert "mano?" in output.read_text(encoding="utf-8")


def test_palavra_depois_do_corte_nao_aparece(tmp_path):
    words = [_word("Eu", 1.0, 1.3), _word("depois", 2.5, 3.0)]
    output = tmp_path / "legenda.ass"
    generate_ass_subtitles(words, 0.0, 2.0, "traditional", str(output))
    assert "depois" not in output.read_text(encoding="utf-8")


# ─── A duração real do arquivo costurado ───────────────────────────────────────

def test_legenda_acompanha_a_duracao_real():
    """Cada trecho arredonda para cima no quadro: 0,18s em 6 trechos, medido."""
    words = [_word("fim", 29.0, 29.5)]
    nominal = total_duration(SEGMENTS)
    moved = remap_words_keeping(words, SEGMENTS, stitched_duration=nominal * 1.01)[0]
    assert moved["start"] == pytest.approx(17.0 * 1.01)
    assert moved["end"] == pytest.approx(17.5 * 1.01)


def test_duracao_real_chega_ate_a_legenda_do_podcast():
    words = [_word("fim", 29.0, 29.5)]
    moved = _stitched_words(words, SEGMENTS, "podcast", "individual", 18.18)[0]
    assert moved["start"] == pytest.approx(17.0 * 1.01)


def test_compact_devolve_a_duracao_real_do_arquivo(tmp_path):
    async def _run_it():
        with (
            patch("app.services.segments.run_ffmpeg", AsyncMock()),
            patch("app.services.segments.get_duration", AsyncMock(return_value=18.18)),
        ):
            return await compact_segments("job", "c", "v.mp4", SEGMENTS, str(tmp_path / "s.mp4"))

    assert asyncio.run(_run_it()) == 18.18


def test_compact_sem_conseguir_medir_devolve_a_nominal(tmp_path):
    async def _run_it():
        with (
            patch("app.services.segments.run_ffmpeg", AsyncMock()),
            patch("app.services.segments.get_duration", AsyncMock(side_effect=RuntimeError("x"))),
        ):
            return await compact_segments("job", "c", "v.mp4", SEGMENTS, str(tmp_path / "s.mp4"))

    assert asyncio.run(_run_it()) == total_duration(SEGMENTS)
