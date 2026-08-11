"""
Testes do estilo da faixa divisória (cor de fundo, cor do texto e fonte).

A faixa é gerada em toda renderização do modo streamer, então o que importa
aqui é que a configuração seja lida sem nunca derrubar o pipeline: arquivo
corrompido, fonte que não existe na máquina e hex inválido têm que cair em
padrões, e o que chega pela API tem que ser validado antes de virar arquivo.
"""

import json

import pytest
from PIL import Image
from pydantic import ValidationError

from app.config import settings
from app.routers.settings import BarStyle
from app.services.layout import (
    BAR_DEFAULT_BG_HEX,
    BAR_DEFAULT_FONT,
    BAR_DEFAULT_TEXT_HEX,
    BAR_FONTS,
    available_bar_fonts,
    generate_divider_bar,
    load_bar_style,
)


def _write_style(tmp_path, monkeypatch, content: str, source: str = "podcast") -> None:
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path))
    # Os presets são por nicho: storage/branding/<nicho>/bar_style.json
    from app.services.branding import BAR_STYLE_FILE, preset_path

    preset_path(source, BAR_STYLE_FILE).write_text(content, encoding="utf-8")


# ─── Configuração salva ───────────────────────────────────────────────────────

def test_bar_style_defaults_without_config(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path))

    assert load_bar_style() == (
        BAR_DEFAULT_BG_HEX, BAR_DEFAULT_TEXT_HEX, BAR_DEFAULT_FONT, False
    )


def test_bar_style_reads_saved_config(tmp_path, monkeypatch):
    _write_style(tmp_path, monkeypatch, json.dumps({
        "bg_color": "#123456", "text_color": "#ABCDEF", "font": "inter",
    }))

    assert load_bar_style() == ("#123456", "#ABCDEF", "inter", True)


def test_bar_style_survives_a_corrupt_config(tmp_path, monkeypatch):
    """Arquivo quebrado não pode derrubar o render — cai no padrão."""
    _write_style(tmp_path, monkeypatch, "{isso não é json")

    assert load_bar_style() == (
        BAR_DEFAULT_BG_HEX, BAR_DEFAULT_TEXT_HEX, BAR_DEFAULT_FONT, False
    )


def test_bar_style_completes_a_partial_config(tmp_path, monkeypatch):
    """Só a cor de fundo salva: o resto vem dos padrões."""
    _write_style(tmp_path, monkeypatch, json.dumps({"bg_color": "#000000"}))

    bg, text, font, customized = load_bar_style()
    assert (bg, text, font, customized) == (
        "#000000", BAR_DEFAULT_TEXT_HEX, BAR_DEFAULT_FONT, True
    )


# ─── Fontes disponíveis ───────────────────────────────────────────────────────

def test_available_fonts_are_a_subset_of_the_catalog():
    fonts = available_bar_fonts()

    assert all(f["key"] in BAR_FONTS for f in fonts)
    assert all(f["label"] for f in fonts)


# ─── Geração da imagem ────────────────────────────────────────────────────────

def test_divider_bar_uses_the_chosen_background(tmp_path):
    path = tmp_path / "bar.png"

    generate_divider_bar(400, 40, str(path), None, "teste", "#102030", "#FFEEDD", "sans")

    img = Image.open(path).convert("RGB")
    _, dominant = max(img.getcolors(img.width * img.height))
    assert dominant == (0x10, 0x20, 0x30)


def test_divider_bar_draws_the_chosen_text_color(tmp_path):
    path = tmp_path / "bar.png"

    generate_divider_bar(400, 40, str(path), None, "teste", "#000000", "#FF0000", "sans")

    img = Image.open(path).convert("RGB")
    colors = {color for _, color in img.getcolors(img.width * img.height)}
    assert (255, 0, 0) in colors


def test_divider_bar_falls_back_when_the_font_is_missing(tmp_path):
    """Fonte desinstalada (ou config antiga) não pode quebrar a renderização."""
    path = tmp_path / "bar.png"

    generate_divider_bar(400, 40, str(path), None, "teste", None, None, "fonte-que-nao-existe")

    assert Image.open(path).size == (400, 40)


def test_divider_bar_ignores_invalid_hex(tmp_path):
    """parse_hex_color já protege o pipeline: hex inválido vira o padrão."""
    path = tmp_path / "bar.png"

    generate_divider_bar(400, 40, str(path), None, "teste", "roxo", "#FFFFFF", "sans")

    assert Image.open(path).size == (400, 40)


# ─── Validação da API ─────────────────────────────────────────────────────────

def test_bar_style_payload_normalizes_short_hex():
    style = BarStyle(bg_color="#abc", text_color="#FFF", font="inter")

    assert (style.bg_color, style.text_color) == ("#AABBCC", "#FFFFFF")


@pytest.mark.parametrize(
    "payload",
    [
        {"bg_color": "azul", "text_color": "#FFFFFF", "font": "inter"},
        {"bg_color": "#FFFFFF", "text_color": "#GGGGGG", "font": "inter"},
        {"bg_color": "#FFFFFF", "text_color": "#000000", "font": "comic-sans"},
    ],
)
def test_bar_style_payload_rejects_invalid_input(payload):
    with pytest.raises(ValidationError):
        BarStyle(**payload)


# ─── Isolamento entre nichos ──────────────────────────────────────────────────

def test_bar_style_is_per_niche(tmp_path, monkeypatch):
    """
    Podcast e gameplay guardam estilos independentes.

    Era o ponto do preset por conta: configurar um nicho não pode mudar a
    identidade do outro, senão o clipe sai com a marca da conta errada.
    """
    _write_style(tmp_path, monkeypatch, json.dumps({
        "bg_color": "#111111", "text_color": "#EEEEEE", "font": "inter",
    }), source="podcast")
    _write_style(tmp_path, monkeypatch, json.dumps({
        "bg_color": "#992200", "text_color": "#FFCC00", "font": "condensed",
    }), source="gameplay")

    assert load_bar_style("podcast") == ("#111111", "#EEEEEE", "inter", True)
    assert load_bar_style("gameplay") == ("#992200", "#FFCC00", "condensed", True)


def test_bar_style_unknown_niche_falls_back(tmp_path, monkeypatch):
    """Nicho desconhecido lê o do podcast em vez de quebrar o render."""
    _write_style(tmp_path, monkeypatch, json.dumps({
        "bg_color": "#123456", "text_color": "#ABCDEF", "font": "inter",
    }), source="podcast")

    assert load_bar_style("nicho-que-nao-existe") == load_bar_style("podcast")
    assert load_bar_style(None) == load_bar_style("podcast")


def test_legacy_branding_is_copied_to_both_niches(tmp_path, monkeypatch):
    """A marca global antiga não pode sumir: ela vira o preset dos dois nichos."""
    from app.services.branding import (
        BAR_STYLE_FILE,
        migrate_legacy_branding,
        preset_path,
    )

    monkeypatch.setattr(settings, "storage_dir", str(tmp_path))
    settings.branding_dir.mkdir(parents=True, exist_ok=True)
    (settings.branding_dir / BAR_STYLE_FILE).write_text(
        json.dumps({"bg_color": "#ABCABC", "text_color": "#FFFFFF", "font": "inter"}),
        encoding="utf-8",
    )

    migrate_legacy_branding()

    assert load_bar_style("podcast") == ("#ABCABC", "#FFFFFF", "inter", True)
    assert load_bar_style("gameplay") == ("#ABCABC", "#FFFFFF", "inter", True)

    # Rodar de novo não sobrescreve o que o usuário já diferenciou
    preset_path("gameplay", BAR_STYLE_FILE).write_text(
        json.dumps({"bg_color": "#000000", "text_color": "#FFFFFF", "font": "inter"}),
        encoding="utf-8",
    )
    migrate_legacy_branding()
    assert load_bar_style("gameplay")[0] == "#000000"
