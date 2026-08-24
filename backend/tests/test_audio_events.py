"""
Testes da leitura de áudio nos buracos da transcrição.

O caso que deu origem ao módulo está reproduzido aqui com os números reais
medidos no vídeo: 21.4s sem uma palavra transcrita, a +13.5 dB do nível de
fala, e um corte que começava em 3051.8 — depois do fato, em cima da reação.

Não há pytest-asyncio no projeto, então os testes de corrotina rodam com
asyncio.run (mesma convenção de test_pipeline_resume.py).
"""

import asyncio

import pytest

from app.prompts.viral_analysis import format_gap, format_transcript_with_timestamps
from app.services.audio_events import (
    Gap,
    detect_gaps,
    find_gaps,
    rescue_start,
)


# ─── Fixtures: o trecho real do vídeo do Alan ─────────────────────────────────

def _word(text, start, end):
    return {"text": text, "start": start, "end": end, "confidence": 0.9}


# "Você joga no mar, eu acho." / "O que que é, cara?" / [21s de gargalhada] /
# "Finalmente eu recebi conteúdo premium aqui, mano."
FALL_WORDS = [
    _word("Eu", 3012.1, 3012.4),
    _word("falo", 3012.5, 3012.9),
    _word("acredita.", 3019.9, 3020.4),
    _word("Você", 3023.9, 3024.2),
    _word("joga", 3024.3, 3024.7),
    _word("no", 3027.1, 3027.3),
    _word("mar,", 3027.4, 3027.6),
    _word("eu", 3027.6, 3027.7),
    _word("acho.", 3027.7, 3027.8),
    _word("O", 3028.1, 3028.2),
    _word("que", 3028.3, 3028.5),
    _word("é,", 3029.8, 3030.0),
    _word("cara?", 3030.1, 3030.4),
    # buraco de 21.4s: o Fall sendo arremessado no mar
    _word("Finalmente", 3051.8, 3052.4),
    _word("eu", 3052.5, 3052.7),
    _word("recebi", 3052.8, 3053.3),
    _word("premium.", 3053.4, 3054.4),
]

LAUGHTER = Gap(start=3030.4, end=3051.8, loudness=-14.1, speech_level=-27.6)
QUIET = Gap(start=3020.4, end=3023.9, loudness=-45.0, speech_level=-27.6)


# ─── Classificação dos buracos ────────────────────────────────────────────────

def test_gargalhada_e_evento_forte():
    assert LAUGHTER.above_speech == pytest.approx(13.5)
    assert LAUGHTER.is_event
    assert LAUGHTER.is_strong_event
    assert not LAUGHTER.is_dead


def test_silencio_de_verdade_nao_e_evento():
    assert QUIET.is_dead
    assert not QUIET.is_event
    assert not QUIET.is_strong_event


def test_faixa_intermediaria_nao_e_evento_nem_tempo_morto():
    """Buraco a 2 dB da fala: som ambiente. Nenhum dos dois rótulos se aplica."""
    ambiguo = Gap(start=10.0, end=15.0, loudness=-25.0, speech_level=-27.0)
    assert not ambiguo.is_event
    assert not ambiguo.is_dead


def test_evento_curto_nao_aciona_resgate_automatico():
    """Alto mas de 3.5s: entra na anotação, não move corte sozinho."""
    curto = Gap(start=10.0, end=13.5, loudness=-12.0, speech_level=-27.0)
    assert curto.is_event
    assert not curto.is_strong_event


# ─── Localização dos buracos ──────────────────────────────────────────────────

def test_find_gaps_acha_o_buraco_da_gargalhada():
    gaps = find_gaps(FALL_WORDS)
    assert (3030.4, 3051.8) in gaps


def test_find_gaps_ignora_respiracao_entre_frases():
    words = [_word("a", 0.0, 1.0), _word("b", 1.5, 2.0)]
    assert find_gaps(words) == []


# ─── O resgate do corte ───────────────────────────────────────────────────────

def test_resgate_recupera_o_fato_perdido():
    """
    O caso real: corte em 3051.8-3083.3 pegava só a reação. O início volta
    para antes da gargalhada, incluindo a fala que preparava o momento.
    """
    start, event = rescue_start(3051.8, 3083.3, [QUIET, LAUGHTER], FALL_WORDS, 90)

    assert event is LAUGHTER
    assert start == 3023.9          # "Você joga no mar, eu acho."
    assert 3083.3 - start < 90


def test_resgate_nao_atravessa_o_buraco_anterior():
    """O preroll para no silêncio de 3.5s — o que vem antes é outro assunto."""
    start, _ = rescue_start(3051.8, 3083.3, [QUIET, LAUGHTER], FALL_WORDS, 90)
    assert start > 3020.4


def test_resgate_respeita_o_teto_de_duracao():
    """Não cabendo tudo, sacrifica o preroll — nunca o final, onde está a reação."""
    start, event = rescue_start(3051.8, 3083.3, [LAUGHTER], FALL_WORDS, 40)

    assert event is LAUGHTER
    assert start == 3083.3 - 40
    assert start < 3051.8  # ainda assim entra no evento, em vez de perdê-lo


def test_sem_evento_o_corte_fica_como_estava():
    start, event = rescue_start(3051.8, 3083.3, [QUIET], FALL_WORDS, 90)
    assert start == 3051.8
    assert event is None


def test_corte_que_ja_contem_o_evento_nao_muda():
    """Modelo acertou sozinho: o resgate não tem o que fazer."""
    start, event = rescue_start(3023.9, 3083.3, [LAUGHTER], FALL_WORDS, 90)
    assert start == 3023.9
    assert event is None


def test_corte_muito_depois_do_evento_nao_e_puxado():
    """Fala 30s depois não é reação àquilo — puxar seria inventar contexto."""
    start, event = rescue_start(3082.0, 3120.0, [LAUGHTER], FALL_WORDS, 90)
    assert start == 3082.0
    assert event is None


# ─── Anotação enviada ao modelo ───────────────────────────────────────────────

def test_anotacao_de_evento_diz_que_aconteceu_algo():
    line = format_gap(LAUGHTER)
    assert "ÁUDIO ALTO" in line
    assert "dB" in line and "+1" in line
    assert "21s" in line


def test_anotacao_de_silencio_diz_tempo_morto():
    assert "tempo morto" in format_gap(QUIET)


def test_transcricao_intercala_a_anotacao_na_posicao_certa():
    text = format_transcript_with_timestamps(FALL_WORDS, [QUIET, LAUGHTER])
    lines = text.splitlines()

    evento = next(i for i, l in enumerate(lines) if "ÁUDIO ALTO" in l)
    reacao = next(i for i, l in enumerate(lines) if "Finalmente" in l)
    fato_antes = next(i for i, l in enumerate(lines) if "mar," in l)

    assert fato_antes < evento < reacao


def test_transcricao_sem_gaps_continua_como_antes():
    assert "((" not in format_transcript_with_timestamps(FALL_WORDS)


# ─── Degradação ───────────────────────────────────────────────────────────────

def test_audio_ausente_nao_derruba_a_analise():
    """Sem leitura de áudio o pipeline segue só com o texto, como antes."""
    gaps = asyncio.run(detect_gaps("job", "/nao/existe/audio.wav", FALL_WORDS))
    assert gaps == []


def test_transcricao_sem_buracos_nem_toca_no_ffmpeg():
    words = [_word("a", 0.0, 1.0), _word("b", 1.2, 2.0)]
    assert asyncio.run(detect_gaps("job", "/nao/existe/audio.wav", words)) == []


# ─── O corte que abre em cima do evento ───────────────────────────────────────
# Segundo jeito de perder a preparação, visto na prática depois que a anotação
# de imagem deixou o modelo confiante para abrir direto no barulho.

def test_resgate_recua_corte_que_abre_em_cima_do_evento():
    """
    Corte 3030.4-3083.3: contém o evento inteiro, mas abre no meio da
    gargalhada, sem a fala que monta a piada.
    """
    start, event = rescue_start(3030.4, 3083.3, [QUIET, LAUGHTER], FALL_WORDS, 90)

    assert event is LAUGHTER
    assert start == 3023.9          # "Você joga no mar, eu acho."


def test_corte_bem_antes_do_evento_nao_e_tocado():
    """Já contém a preparação: não há o que resgatar."""
    start, event = rescue_start(3012.0, 3083.3, [LAUGHTER], FALL_WORDS, 90)

    assert start == 3012.0
    assert event is None


def test_corte_no_meio_do_evento_nao_e_tocado():
    """
    Depois da tolerância de abertura o corte é uma escolha, não um descuido —
    mexer nele seria adivinhar.
    """
    start, event = rescue_start(3045.0, 3083.3, [LAUGHTER], FALL_WORDS, 90)

    assert start == 3045.0
    assert event is None


# ─── Tamanho da construção ────────────────────────────────────────────────────
# Caso Bahiaqz: o payoff (bomba explodindo) só é engraçado por causa de 128s de
# negociação sem pausa antes dele. Sem esse número o modelo lê a negociação como
# enchimento e abre o corte direto no barulho.

def test_construcao_longa_e_sinalizada():
    gap = Gap(start=486.8, end=514.9, loudness=-13.4, speech_level=-25.3,
              buildup_start=358.2)

    assert gap.buildup == pytest.approx(128.6)
    assert gap.has_long_buildup


def test_construcao_curta_nao_e_sinalizada():
    """8-25s é preparação normal de frase, não muda onde o corte começa."""
    gap = Gap(start=241.4, end=248.0, loudness=-13.0, speech_level=-25.3,
              buildup_start=231.1)

    assert not gap.has_long_buildup


def test_gap_sem_construcao_medida_nao_quebra():
    gap = Gap(start=100.0, end=110.0, loudness=-13.0, speech_level=-25.3)
    assert gap.buildup == 0.0
    assert not gap.has_long_buildup


def test_anotacao_avisa_onde_a_construcao_comeca():
    gap = Gap(start=486.8, end=514.9, loudness=-13.4, speech_level=-25.3,
              buildup_start=358.2)

    line = format_gap(gap)
    assert "sem pausa desde 358.2s" in line
    assert "respeitando o teto" in line


def test_anotacao_de_evento_curto_nao_menciona_construcao():
    line = format_gap(LAUGHTER)
    assert "de construção" not in line

