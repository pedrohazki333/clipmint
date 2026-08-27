"""
Testes da marca d'água queimada no clipe.

Duas coisas já quebraram na mão e são o que os testes aqui prendem:

1. **O slot errado.** A logo que cobre QR code e a arte que assina o clipe são
   arquivos diferentes. Se um caminho vazar para o outro, uma conta sai assinada
   com a imagem que outra escolheu — e só se descobre no vídeo publicado.
2. **A âncora vertical.** A marca é posicionada pelo CENTRO. Ancorar pelo topo
   faz a arte subir ou descer só por ser mais alta ou mais baixa, e o
   enquadramento medido no clipe de referência se perde na primeira troca de
   arte.
"""

import pytest

from app.config import settings
from app.services.branding import CLIP_WATERMARK_FILE, WATERMARK_FILE, preset_path
from app.services.clipper import _clip_watermark_filters
from app.services.watermark import clip_watermark_path, user_watermark_path


def _write_art(tmp_path, monkeypatch, filename: str, source: str = "gameplay"):
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path))
    path = preset_path(source, filename)
    path.write_bytes(b"\x89PNG\r\n\x1a\n")  # conteúdo não importa aqui
    return path


# ─── Resolução do arquivo ─────────────────────────────────────────────────────

def test_no_art_means_no_watermark(tmp_path, monkeypatch):
    """Sem arte, None — é o estado normal de uma conta que não marca clipes."""
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path))

    assert clip_watermark_path("gameplay") is None


def test_art_is_found_when_configured(tmp_path, monkeypatch):
    path = _write_art(tmp_path, monkeypatch, CLIP_WATERMARK_FILE)

    assert clip_watermark_path("gameplay") == str(path)


def test_the_two_watermark_slots_are_independent(tmp_path, monkeypatch):
    """
    A logo de cobrir QR não pode virar marca do clipe, nem o contrário.

    É o que impede uma conta que só configurou a logo antiga de começar a
    queimá-la no vídeo sem ninguém ter pedido.
    """
    _write_art(tmp_path, monkeypatch, WATERMARK_FILE)

    assert user_watermark_path("gameplay") is not None
    assert clip_watermark_path("gameplay") is None


def test_art_is_per_niche(tmp_path, monkeypatch):
    _write_art(tmp_path, monkeypatch, CLIP_WATERMARK_FILE, source="gameplay")

    assert clip_watermark_path("gameplay") is not None
    assert clip_watermark_path("podcast") is None


# ─── Geometria do overlay ─────────────────────────────────────────────────────

def _filters(canvas_w=1080, canvas_h=1920):
    return _clip_watermark_filters(
        input_idx=2, base_label="withbar", out_label="withwm",
        canvas_w=canvas_w, canvas_h=canvas_h,
    )


def test_matches_the_reference_clip():
    """
    Os padrões reproduzem o clipe de referência: 200px de largura num canvas de
    1080 e centro a 79.4% da altura. Se alguém mexer nos defaults sem querer,
    é aqui que aparece.
    """
    scale, overlay = _filters()

    assert "scale=200:-1" in scale
    assert "1524-overlay_h/2" in overlay


def test_width_follows_the_canvas():
    """Frações, não pixels: dobrar a saída dobra a marca junto."""
    scale, _ = _filters(canvas_w=2160, canvas_h=3840)

    assert "scale=400:-1" in scale


def test_height_is_free_so_the_aspect_survives():
    """`-1` na altura: arte larga não pode sair esmagada."""
    scale, _ = _filters()

    assert ":-1" in scale
    assert "force_original_aspect_ratio" not in scale


def test_anchored_by_the_center_not_the_top():
    _, overlay = _filters()

    assert "overlay_h/2" in overlay
    assert "(main_w-overlay_w)/2" in overlay


def test_alpha_is_multiplied_not_replaced():
    """`aa` multiplica o alfa — o recorte da arte continua recortado."""
    scale, _ = _filters()

    assert "format=rgba" in scale
    assert f"colorchannelmixer=aa={settings.clip_watermark_opacity:.3f}" in scale


def test_labels_are_wired_to_the_chain():
    scale, overlay = _filters()

    assert scale.startswith("[2:v]")
    assert overlay.startswith("[withbar][cwm]")
    assert overlay.endswith("[withwm]")


@pytest.mark.parametrize("opacity,expected", [(2.0, "1.000"), (-1.0, "0.000")])
def test_opacity_outside_the_range_is_clamped(monkeypatch, opacity, expected):
    """Um valor absurdo no .env não pode gerar filtro que o FFmpeg recusa."""
    monkeypatch.setattr(settings, "clip_watermark_opacity", opacity)
    scale, _ = _filters()

    assert f"colorchannelmixer=aa={expected}" in scale
