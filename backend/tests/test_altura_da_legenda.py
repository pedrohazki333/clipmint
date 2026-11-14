"""
A altura da legenda é escolhida no estilo: num podcast, a de sempre pode cair na boca
de quem fala. Ela precisa chegar ao render, ficar dentro dos limites e sobreviver à
troca do destaque no pedido.
"""

import pytest
from pydantic import ValidationError

from app.clip_style import (
    CAPTION_Y_DEFAULT,
    CAPTION_Y_MAX,
    CAPTION_Y_MIN,
    CaptionStyle,
    ClipStyle,
)
from app.services.safe_area import BOTTOM, CANVAS_H, TOP
from app.services.subtitler import caption_geometry


def test_estilo_antigo_sem_altura_fica_no_padrao():
    estilo = ClipStyle.model_validate({"legenda": {"cor": "#FFD23F", "estilo": "cor"}})
    assert estilo.legenda.altura == CAPTION_Y_DEFAULT


@pytest.mark.parametrize("altura", [CAPTION_Y_MIN - 1, CAPTION_Y_MAX + 1])
def test_altura_fora_dos_limites_e_recusada(altura):
    with pytest.raises(ValidationError):
        CaptionStyle(altura=altura)


def test_limites_ficam_fora_da_interface_do_tiktok_ate_no_tamanho_grande():
    for altura in (CAPTION_Y_MIN, CAPTION_Y_MAX):
        g = caption_geometry("fullscreen", "G", altura=altura)
        metade = round(g.size * 0.6)  # a linha tem 1,09x a letra, mais a borda da caixa
        assert g.center_y - metade >= TOP
        assert g.center_y + metade <= CANVAS_H - BOTTOM


@pytest.mark.parametrize("layout", ["fullscreen", "cover", "crop"])
def test_a_altura_escolhida_chega_a_geometria(layout):
    assert caption_geometry(layout, altura=1400).center_y == 1400


def test_a_altura_acompanha_a_escala_do_quadro():
    assert caption_geometry("cover", canvas_w=540, canvas_h=960, altura=1400).center_y == 700


def test_original_e_margem_fixa_ignoram_a_altura():
    assert caption_geometry("original", altura=1400) == caption_geometry("original")
    com_margem = caption_geometry("crop", margin_v=300, altura=1400)
    assert com_margem == caption_geometry("crop", margin_v=300)
