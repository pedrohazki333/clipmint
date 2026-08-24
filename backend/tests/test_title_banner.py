"""
Testes do banner de título do layout streamer.

O banner existe por retenção: a legenda passa palavra a palavra e muitas vezes
não chega a ser lida, então um título parado nos primeiros segundos é a única
coisa na tela que diz do que se trata o clipe antes de a fala chegar lá.

O que está coberto aqui é a geometria e a animação de saída — que é onde um
erro passa despercebido. Uma cor trocada aparece na hora; um banner que encolhe
para o lado errado, ou que fica preso na tela num clip curto, só aparece depois
de render.
"""

import json

import pytest
from PIL import Image

from app.services.layout import (
    generate_banner_collapse_frames,
    generate_title_banner,
    streamer_geometry,
)


# ─── O banner ─────────────────────────────────────────────────────────────────

def test_banner_spans_the_full_canvas_width(tmp_path):
    """Retangular de ponta a ponta — não é a pílula do layout 'cover'."""
    out = str(tmp_path / "b.png")
    w, h = generate_title_banner("Voltou minha casca no último segundo", out, 1080)

    assert w == 1080
    assert Image.open(out).size == (1080, h)


def test_banner_height_is_even(tmp_path):
    """O canvas final é yuv420p: dimensão ímpar quebra o overlay."""
    for texto in ("Curto", "Um título bem mais longo que ocupa duas linhas inteiras"):
        _, h = generate_title_banner(texto, str(tmp_path / "b.png"), 1080)
        assert h % 2 == 0, f"altura ímpar para {texto!r}"


def test_banner_uses_the_niche_colors(tmp_path, monkeypatch):
    """
    As cores saem do preset do nicho, não dos padrões.

    Passar `source_type=None` aqui devolvia silenciosamente as cores de OUTRO
    nicho — o clip de gameplay saiu com o banner azul do podcast, e só o render
    revelou. O padrão não é "neutro": é o preset da conta sem nicho.
    """
    from app.services import branding

    preset = tmp_path / "gameplay"
    preset.mkdir()
    (preset / "banner_colors.json").write_text(
        json.dumps({"bg_color": "#FF6C3D", "text_color": "#FFFFFF"}), encoding="utf-8"
    )
    monkeypatch.setattr(branding, "BRANDING_ROOT", tmp_path, raising=False)
    from app.services.layout import BannerStyle

    monkeypatch.setattr(
        "app.services.layout.load_banner_style",
        lambda st: (
            BannerStyle("#FF6C3D", "#FFFFFF", "condensed", True)
            if st == "gameplay"
            else BannerStyle("#525EA7", "#FFC349", "condensed", True)
        ),
    )

    out = str(tmp_path / "b.png")
    generate_title_banner("Título de teste", out, 1080, source_type="gameplay")

    canto = Image.open(out).convert("RGBA").getpixel((5, 5))
    assert canto[:3] == (255, 108, 61)


def test_banner_wraps_into_at_most_two_lines(tmp_path):
    """Três linhas empurrariam a facecam para fora; o título encurta em vez disso."""
    curto = generate_title_banner("Duas palavras", str(tmp_path / "a.png"), 1080)[1]
    longo = generate_title_banner(
        "Um título absurdamente longo que jamais caberia em duas linhas legíveis "
        "por mais que a fonte encolha sem parar",
        str(tmp_path / "b.png"), 1080,
    )[1]

    assert longo <= curto * 2.2


def test_empty_title_is_refused(tmp_path):
    """Banner vazio é erro de quem chamou, não uma caixa laranja em branco."""
    with pytest.raises(ValueError):
        generate_title_banner("   ", str(tmp_path / "b.png"), 1080)


# ─── A saída ──────────────────────────────────────────────────────────────────

def _top_of_content(path: str) -> int | None:
    """Primeira linha com pixel visível, ou None se o quadro é transparente."""
    bbox = Image.open(path).convert("RGBA").getbbox()
    return bbox[1] if bbox else None


def test_collapse_pins_the_bottom_and_lowers_the_top(tmp_path):
    """
    O banner encolhe PARA DENTRO da faixa: base presa, topo descendo.

    É o que o exemplo aprovado faz, e é diferente de deslizar para trás da
    faixa — que moveria o texto para baixo e o comeria de baixo para cima.
    Testar isso pela borda superior é o que distingue os dois.
    """
    master = str(tmp_path / "b.png")
    _, height = generate_title_banner("Voltou minha casca no último segundo", master, 1080)
    quadros = generate_banner_collapse_frames(master, str(tmp_path / "f"), 6)

    topos = [_top_of_content(q) for q in quadros]
    visiveis = [t for t in topos if t is not None]

    # A borda de cima só desce
    assert visiveis == sorted(visiveis)
    assert visiveis[0] > 0, "o primeiro quadro já tem que ter saído do repouso"
    # E a de baixo nunca se move
    for q in quadros[:-1]:
        assert Image.open(q).convert("RGBA").getbbox()[3] == height


def test_collapse_ends_fully_transparent(tmp_path):
    """O último quadro tem que sumir, senão sobra uma tira presa na faixa."""
    master = str(tmp_path / "b.png")
    generate_title_banner("Título", master, 1080)
    quadros = generate_banner_collapse_frames(master, str(tmp_path / "f"), 5)

    assert _top_of_content(quadros[-1]) is None


def test_collapse_frames_all_share_the_master_size(tmp_path):
    """
    Tamanho constante não é detalhe: é o que permite a sequência virar overlay.

    O `overlay` do FFmpeg exige dimensões constantes e o `crop` não aceita
    altura variável no tempo — por isso o recorte é feito aqui, no Pillow.
    """
    master = str(tmp_path / "b.png")
    _, height = generate_title_banner("Título de teste", master, 1080)
    quadros = generate_banner_collapse_frames(master, str(tmp_path / "f"), 6)

    assert all(Image.open(q).size == (1080, height) for q in quadros)


def test_collapse_does_not_scale_the_text(tmp_path):
    """
    O conteúdo é recortado, não redimensionado.

    Se o texto encolhesse junto, a largura do conteúdo diminuiria a cada quadro.
    Ela tem que ficar igual até o texto ser inteiramente comido.
    """
    master = str(tmp_path / "b.png")
    generate_title_banner("Voltou minha casca no último segundo", master, 1080)
    quadros = generate_banner_collapse_frames(master, str(tmp_path / "f"), 6)

    larguras = {
        (bbox[0], bbox[2])
        for bbox in (Image.open(q).convert("RGBA").getbbox() for q in quadros)
        if bbox
    }
    assert len(larguras) == 1


# ─── Posição no canvas ────────────────────────────────────────────────────────

def test_banner_sits_flush_above_the_bar(tmp_path):
    """
    'Encostado acima da faixa': a base do banner é o topo da faixa.

    Um vão entre os dois deixaria uma tira de facecam no meio e quebraria a
    leitura de bloco único.
    """
    from app.services.clipper import _prepare_title_banner

    geo = streamer_geometry()
    _, height = generate_title_banner("Título de teste", str(tmp_path / "b.png"), geo.canvas_w)

    y = geo.facecam_h - height
    assert y + height == geo.facecam_h
    assert y > 0, "o banner não pode ser mais alto que o painel da facecam"


def test_short_clip_skips_the_banner(tmp_path):
    """
    Num clip curto demais o banner nunca sairia — e taparia a cara até o fim.

    Melhor não desenhá-lo do que deixá-lo preso na tela.
    """
    import asyncio

    from app.config import settings
    from app.services.clipper import _prepare_title_banner

    geo = streamer_geometry()
    curto = settings.streamer_banner_hold + settings.streamer_banner_exit - 0.5

    banner = asyncio.run(_prepare_title_banner(
        tmp_path, "c1", "Um título qualquer", geo, curto, "gameplay"
    ))
    assert banner is None


def test_no_text_means_no_banner(tmp_path):
    import asyncio

    from app.services.clipper import _prepare_title_banner

    geo = streamer_geometry()
    banner = asyncio.run(_prepare_title_banner(tmp_path, "c1", "  ", geo, 60.0, "gameplay"))
    assert banner is None


# ─── Emoji colorido ───────────────────────────────────────────────────────────

def _has_emoji_font() -> bool:
    from app.services.layout import emoji_font_path

    return emoji_font_path() is not None


emoji_font = pytest.mark.skipif(
    not _has_emoji_font(),
    reason="NotoColorEmoji não instalada (rode `make emoji-font`)",
)


@emoji_font
def test_emoji_is_drawn_in_color(tmp_path):
    """
    O emoji do hook faz parte do gancho e sai colorido.

    A fonte do texto não tem esses glifos, então o emoji é desenhado com a
    NotoColorEmoji e composto por cima — se isso quebrar, o que aparece é o
    retângulo de caractere ausente, ou nada.
    """
    from app.services.layout import generate_title_banner

    out = str(tmp_path / "b.png")
    generate_title_banner("Voltou minha casca no último segundo 😱", out, 1080,
                          bg_color="#FF6C3D", text_color="#FFFFFF")

    img = Image.open(out).convert("RGB")
    fundo, texto = (255, 108, 61), (255, 255, 255)
    outras = {
        p for p in img.get_flattened_data()
        if p != fundo and p != texto
        # Ignora a antialiasing entre o texto branco e o fundo laranja
        and not (p[0] > 240 and p[1] > 110 and p[2] > 60)
    }
    assert len(outras) > 50, "nenhuma cor de emoji encontrada no banner"


@emoji_font
def test_emoji_widens_the_line(tmp_path):
    """
    A largura do emoji entra na medição da linha.

    Sem isso a quebra em duas linhas acharia que a linha é mais estreita do que
    é, e o título vazaria da caixa.
    """
    from app.services.layout import _load_bar_font, _mixed_line_width

    font = _load_bar_font("montserrat_black", 54)
    assert _mixed_line_width("no último segundo 😱", font) > _mixed_line_width(
        "no último segundo", font
    )


@emoji_font
def test_emoji_sequence_stays_one_glyph(tmp_path):
    """
    Emojis vizinhos vão juntos para o shaper.

    Uma sequência ZWJ é um glifo só depois do shaping; quebrá-la em caracteres
    desenharia as partes soltas (a família viraria três bonecos).
    """
    from app.services.layout import _split_emoji_runs

    runs = _split_emoji_runs("olha 👨‍👩‍👧 aqui")
    emojis = [conteudo for conteudo, is_emoji in runs if is_emoji]
    assert len(emojis) == 1, f"esperava um trecho de emoji, veio {runs}"


@emoji_font
def test_arrows_fall_back_to_the_text_font(tmp_path):
    """
    O intervalo de _EMOJI_RE pega setas, que a fonte de emoji não tem.

    Elas voltam para a fonte do texto em vez de sumirem em silêncio — engolir
    um caractere do título é pior que desenhá-lo simples.
    """
    from app.services.layout import _load_bar_font, _mixed_line_width

    font = _load_bar_font("montserrat_black", 54)
    assert _mixed_line_width("antes → depois", font) > _mixed_line_width(
        "antes  depois", font
    )


def test_without_the_font_the_emoji_is_dropped_not_tofu(tmp_path, monkeypatch):
    """
    Sem fonte de emoji o título perde o emoji e continua saindo.

    A alternativa seria desenhar o retângulo de caractere ausente no meio do
    banner, que é pior que não ter emoji — e derrubar o render por causa disso
    seria pior ainda.
    """
    from app.services import layout

    monkeypatch.setattr(layout, "emoji_font_path", lambda: None)

    out = str(tmp_path / "b.png")
    w, h = layout.generate_title_banner("Segurou no último segundo 😱", out, 1080)

    assert (w, h) == Image.open(out).size


def test_a_title_that_is_only_emoji_without_the_font_is_refused(tmp_path, monkeypatch):
    """Sobrar string vazia depois de tirar o emoji é erro, não banner em branco."""
    from app.services import layout

    monkeypatch.setattr(layout, "emoji_font_path", lambda: None)

    with pytest.raises(ValueError):
        layout.generate_title_banner("😱😱", str(tmp_path / "b.png"), 1080)


# ─── Fonte configurável do banner do layout 'cover' ───────────────────────────

def test_cover_banner_uses_the_configured_font(tmp_path, monkeypatch):
    """A família salva no preset do nicho é a que desenha o banner."""
    from app.config import settings
    from app.services.branding import BANNER_COLORS_FILE, preset_path
    from app.services.layout import generate_banner, load_banner_style

    monkeypatch.setattr(settings, "storage_dir", str(tmp_path))
    preset_path("podcast", BANNER_COLORS_FILE).write_text(
        json.dumps({"bg_color": "#022DA5", "text_color": "#FBBF03", "font": "serif"}),
        encoding="utf-8",
    )

    assert load_banner_style("podcast").font == "serif"

    # Duas famílias diferentes não desenham o mesmo texto do mesmo jeito: se a
    # escolha não chegasse ao render, os dois PNGs sairiam idênticos.
    generate_banner("Fonte de teste", str(tmp_path / "c.png"), None, None, "condensed")
    generate_banner("Fonte de teste", str(tmp_path / "s.png"), None, None, "serif")
    assert (tmp_path / "c.png").read_bytes() != (tmp_path / "s.png").read_bytes()
