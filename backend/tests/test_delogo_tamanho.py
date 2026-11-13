"""
Delogo nunca cobre uma área do tamanho do vídeo.

O clipe 9fae72ee (12/11/2026) saiu com o painel de quem fala virado em listras:
o detector fundiu caixas de cantos opostos numa "marca" de 1920 × 1080, e o
delogo reconstruiu o quadro inteiro a partir das bordas.
"""

import asyncio

from app.services import clipper
from app.services.watermark import _cabe_como_marca


def test_marca_do_tamanho_de_um_logo_cabe():
    assert _cabe_como_marca((1700, 30, 180, 60), 1920, 1080)


def test_caixa_da_tela_inteira_nao_e_marca():
    assert not _cabe_como_marca((0, 0, 1920, 1080), 1920, 1080)


def test_faixa_que_atravessa_o_quadro_nao_e_marca():
    # 11% da área, mas 80% da largura: é a prateleira do cenário, não um logo.
    assert not _cabe_como_marca((0, 15, 1549, 155), 1920, 1080)


def test_render_ignora_regiao_grande_mesmo_se_o_detector_a_devolver(monkeypatch):
    monkeypatch.setattr(
        clipper, "detect_brand_regions",
        lambda *a: {"qr": [], "static": [(0, 0, 1920, 1080), (1700, 30, 180, 60)]},
    )

    async def dims(_):
        return 1920, 1080

    monkeypatch.setattr(clipper, "get_video_dimensions", dims)
    monkeypatch.setattr(clipper, "user_watermark_path", lambda *a: None)

    _inputs, parts, label, _n = asyncio.run(
        clipper._brand_layers("v.mp4", 0.0, 10.0, "podcast", None)
    )
    filtro = ";".join(parts)
    assert "w=1920" not in filtro and "h=1080" not in filtro
    assert "delogo=x=1700" in filtro
    assert label == "clean"


def test_so_regiao_grande_nao_gera_filtro_nenhum(monkeypatch):
    monkeypatch.setattr(
        clipper, "detect_brand_regions", lambda *a: {"qr": [], "static": [(0, 0, 1920, 1080)]}
    )

    async def dims(_):
        return 1920, 1080

    monkeypatch.setattr(clipper, "get_video_dimensions", dims)
    monkeypatch.setattr(clipper, "user_watermark_path", lambda *a: None)

    _inputs, parts, label, _n = asyncio.run(
        clipper._brand_layers("v.mp4", 0.0, 10.0, "podcast", None)
    )
    assert parts == [] and label == "0:v"
