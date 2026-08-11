"""
Testes da leitura do HUD de Rainbow Six Siege.

O caso que originou o módulo: um clipe de 52s onde o streamer estava MORTO
durante 82% do tempo, comentando uma troca que o espectador nunca vê. A fala
sozinha não tinha como revelar isso — o jogo escreve "OBSERVANDO <nome>" na
tela quando você está assistindo um companheiro.
"""

from app.services.r6_hud import (
    DeadWindow,
    _windows_from_hits,
    dead_overlap,
    template_available,
)


def test_template_ships_with_the_app():
    """Sem o recorte de referência a detecção inteira fica desligada."""
    assert template_available()


def test_groups_consecutive_hits_into_one_window():
    """Morte em Siege dura dezenas de segundos: as amostras viram um intervalo."""
    windows = _windows_from_hits([100.0, 102.0, 104.0, 106.0], interval=2.0)

    assert len(windows) == 1
    assert windows[0].start == 100.0
    assert windows[0].end == 108.0


def test_separates_windows_far_apart():
    """Duas mortes distintas não podem virar uma janela só."""
    windows = _windows_from_hits([100.0, 102.0, 300.0, 302.0], interval=2.0)

    assert len(windows) == 2
    assert windows[0].end == 104.0
    assert windows[1].start == 300.0


def test_bridges_a_short_gap():
    """O texto some por um frame em troca de câmera — não é ressurreição."""
    windows = _windows_from_hits([100.0, 102.0, 106.0], interval=2.0)

    assert len(windows) == 1


def test_overlap_matches_the_real_rejected_clip():
    """
    Números reais do job do Nesk (agosto/2026).

    Clipe reprovado: 374.9–427.7 contra a janela de morte 362–418.
    """
    windows = [DeadWindow(start=362.0, end=418.0)]

    assert dead_overlap(windows, 374.9, 427.7) > 0.75
    # Os dois clipes que o usuário não reclamou ficam fora da janela
    assert dead_overlap(windows, 962.6, 1027.9) == 0.0
    assert dead_overlap(windows, 1391.0, 1430.6) == 0.0


def test_overlap_sums_several_windows_and_caps_at_one():
    windows = [DeadWindow(start=0.0, end=10.0), DeadWindow(start=20.0, end=30.0)]

    assert dead_overlap(windows, 0.0, 40.0) == 0.5
    assert dead_overlap(windows, 0.0, 10.0) == 1.0
    assert dead_overlap([], 0.0, 10.0) == 0.0
    assert dead_overlap(windows, 5.0, 5.0) == 0.0  # janela degenerada não divide por zero
