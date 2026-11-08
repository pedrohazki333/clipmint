"""
Layout A e a legenda do estilo do clipe.

As medidas estão em docs/LAYOUTS_V2.md. O que estes testes travam é a geometria, sem
olhar para um pixel: nada nas áreas seguras, a caixa de cada linha, a palavra-chave em
outra cor. O julgamento visual é feito nos quadros de um render real.
"""

import asyncio
import re

import pytest
from PIL import Image

from app.clip_style import ClipStyle, CaptionStyle, TitleStyle, contrast_ratio
from app.config import settings
from app.services import clipper
from app.services.fonts import font_family, font_path, install_for_render, load_font
from app.services.safe_area import RIGHT_LIMIT_X, Rect, unsafe_areas
from app.services.subtitler import (
    CAPTION_MAX_WIDTH,
    caption_geometry,
    generate_styled_captions,
    group_caption_lines,
)
from app.services.title_card import (
    TITLE_LINE_HEIGHT,
    TITLE_MAX_RIGHT,
    TITLE_PAD_X,
    TITLE_SIZE,
    TITLE_X,
    TITLE_Y,
    clean_title,
    fit_title,
    generate_fullscreen_title,
)

GANCHOS_REAIS = [
    "A política virou guerra, eu perdi 200 mil",
    "Eu mudei minha visão sobre o Neymar",
    "Minha mulher vota diferente de mim, e tudo bem",
    "Rico ou pobre, não consigo me libertar disso",
    "Debate sério, país dividido, e ele fez piada",
    "Perdi 200 mil seguidores numa noite",
]


@pytest.fixture(autouse=True)
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path / "storage"))
    settings.ensure_dirs()
    return tmp_path


# ─── Áreas seguras ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "rect,esperado",
    [
        (Rect(53, 197, 856, 95), []),
        (Rect(53, 100, 856, 95), ["topo"]),
        (Rect(53, 1500, 500, 100), ["base"]),
        (Rect(800, 1000, 200, 100), ["coluna da direita"]),
        # Acima da faixa da coluna da direita, pode ir até a borda.
        (Rect(800, 300, 200, 100), []),
    ],
)
def test_areas_seguras(rect, esperado):
    assert unsafe_areas(rect) == esperado


# ─── Título do layout A ────────────────────────────────────────────────────────

def _titulo(tmp_path, title, keyword=None, style=None):
    saida = tmp_path / "t.png"
    overlay = generate_fullscreen_title(title, keyword, style or ClipStyle(arroba={"texto": "@conta"}), str(saida))
    return overlay, saida


def test_titulo_na_posicao_da_especificacao(tmp_path):
    overlay, _ = _titulo(tmp_path, GANCHOS_REAIS[0])
    assert (overlay.x, overlay.y) == (53, 197)


@pytest.mark.parametrize("gancho", GANCHOS_REAIS)
def test_titulo_nao_passa_de_x_909_nem_das_areas_seguras(tmp_path, gancho):
    overlay, _ = _titulo(tmp_path, gancho)
    for rect in overlay.rects:
        assert rect.x + rect.w <= TITLE_MAX_RIGHT
        assert unsafe_areas(rect) == []


@pytest.mark.parametrize("gancho", GANCHOS_REAIS)
def test_titulo_nao_deixa_palavra_sozinha_no_fim(gancho):
    """Medido: a quebra simples deixava "MIL" sozinho numa linha."""
    linhas, _ = fit_title(clean_title(gancho), "archivo", TITLE_SIZE, TITLE_MAX_RIGHT - TITLE_X - 2 * TITLE_PAD_X)
    if len(linhas) > 1:
        assert len(linhas[-1].split()) > 1 or len(gancho.split()) <= len(linhas)


def test_cada_linha_tem_uma_caixa_da_largura_do_seu_texto(tmp_path):
    overlay, saida = _titulo(tmp_path, GANCHOS_REAIS[2], style=ClipStyle())
    assert len(overlay.rects) >= 2
    larguras = {round(r.w) for r in overlay.rects}
    assert len(larguras) > 1, "todas as caixas têm a mesma largura"
    assert overlay.rects[1].y - overlay.rects[0].y == round(TITLE_SIZE * TITLE_LINE_HEIGHT)

    imagem = Image.open(saida).convert("RGBA")
    assert imagem.getpixel((1, 1)) == (11, 11, 12, 255)
    # À direita da primeira caixa não há fundo: cada caixa acompanha a própria linha.
    canto = imagem.getpixel((imagem.width - 1, 1))
    assert canto[3] == 0 or overlay.rects[0].w >= imagem.width


def test_palavra_chave_sai_na_cor_da_marca(tmp_path):
    _, saida = _titulo(tmp_path, "Perdi 200 mil seguidores", "200", ClipStyle(marca="#3EC8FF"))
    pixels = Image.open(saida).convert("RGB").getdata()
    assert (62, 200, 255) in set(pixels)


def test_sem_palavra_chave_nao_ha_cor_da_marca(tmp_path):
    _, saida = _titulo(tmp_path, "Perdi 200 mil seguidores", None, ClipStyle(marca="#3EC8FF"))
    assert (62, 200, 255) not in set(Image.open(saida).convert("RGB").getdata())


def test_identidade_azul_e_amarela_aparece_no_titulo(tmp_path):
    style = ClipStyle(marca="#FAC007", titulo=TitleStyle(fundo="#032DA5", texto="#FAC007"))
    _, saida = _titulo(tmp_path, "Perdi tudo", "tudo", style)
    cores = set(Image.open(saida).convert("RGB").getdata())
    assert (3, 45, 165) in cores
    assert (250, 192, 7) in cores


def test_arroba_aparece_uma_vez_abaixo_do_titulo(tmp_path):
    overlay, _ = _titulo(tmp_path, GANCHOS_REAIS[1])
    arroba, *caixas = overlay.rects
    assert arroba.y >= caixas[-1].y + caixas[-1].h


def test_titulo_desligado_deixa_so_o_arroba(tmp_path):
    overlay, _ = _titulo(
        tmp_path, "Texto", style=ClipStyle(titulo=TitleStyle(ligado=False), arroba={"texto": "@c"})
    )
    assert len(overlay.rects) == 1
    assert overlay.rects[0].y == TITLE_Y


def test_arroba_desligado_nao_aparece(tmp_path):
    overlay, _ = _titulo(tmp_path, "Texto", style=ClipStyle(arroba={"texto": "@c", "ligado": False}))
    assert len(overlay.rects) == 1


def test_sem_titulo_e_sem_arroba_nao_ha_imagem(tmp_path):
    overlay, saida = _titulo(tmp_path, "Texto", style=ClipStyle(titulo=TitleStyle(ligado=False)))
    assert overlay is None
    assert not saida.exists()


def test_titulo_enorme_diminui_em_vez_de_vazar(tmp_path):
    overlay, _ = _titulo(tmp_path, "palavra " * 30, style=ClipStyle())
    assert len(overlay.rects) <= 4 or all(r.x + r.w <= TITLE_MAX_RIGHT + 200 for r in overlay.rects)


def test_emoji_sai_do_titulo():
    assert clean_title("Perdi tudo 😱") == "PERDI TUDO"


def test_caixa_alta_mantem_acentos():
    assert clean_title("não é ação") == "NÃO É AÇÃO"


@pytest.mark.parametrize("marca", ["#FD375C", "#FFD23F", "#3EC8FF", "#9DFF4F"])
def test_contraste_do_titulo_na_paleta(marca):
    assert contrast_ratio(marca, ClipStyle().titulo.fundo) >= 4.5
    assert contrast_ratio(ClipStyle().titulo.texto, ClipStyle().titulo.fundo) >= 4.5


# ─── Fontes ────────────────────────────────────────────────────────────────────

def test_cada_papel_tem_a_sua_familia():
    familias = {font_family(font_path("archivo", papel)) for papel in ("titulo", "legenda", "arroba")}
    assert familias == {
        "Archivo ClipMint Titulo",
        "Archivo ClipMint Legenda",
        "Archivo ClipMint Arroba",
    }


def test_fonte_nao_instalada_cai_na_archivo(monkeypatch):
    from app.services import fonts

    monkeypatch.setitem(fonts.BAR_FONTS, "condensed", ("X", ["/nao/existe.ttf"]))
    assert font_path("condensed", "legenda").name == "ArchivoClipMintLegenda.ttf"


def test_pasta_do_render_tem_so_a_fonte_pedida(tmp_path):
    """O libass carrega todos os arquivos da pasta: não pode ser a do sistema."""
    familia, pasta = install_for_render("archivo", "legenda", tmp_path)
    assert familia == "Archivo ClipMint Legenda"
    assert [p.name for p in pasta.iterdir()] == ["ArchivoClipMintLegenda.ttf"]


# ─── Legenda ───────────────────────────────────────────────────────────────────

def _palavras(*textos, passo=0.5):
    return [
        {"text": t, "start": i * passo, "end": i * passo + passo * 0.8}
        for i, t in enumerate(textos)
    ]


def test_geometria_do_layout_a():
    geo = caption_geometry("fullscreen")
    assert (geo.center_y, geo.size, geo.outline) == (1205, 88, 9)


def test_geometria_do_layout_b():
    geo = caption_geometry("cover")
    assert (geo.center_y, geo.size) == (1205, 80)


@pytest.mark.parametrize("tamanho,fator", [("P", 0.85), ("M", 1.0), ("G", 1.15)])
def test_tamanhos(tamanho, fator):
    assert caption_geometry("fullscreen", tamanho).size == round(88 * fator)


def test_legenda_nao_cai_em_area_segura():
    geo = caption_geometry("fullscreen")
    rect = Rect(540 - geo.max_width / 2, geo.center_y - geo.size, geo.max_width, geo.size * 2)
    assert unsafe_areas(rect) == []
    assert 540 + geo.max_width / 2 <= RIGHT_LIMIT_X


def test_streamer_mantem_a_posicao_pela_margem():
    geo = caption_geometry("streamer", canvas_w=1080, canvas_h=1920, margin_v=500)
    assert geo.center_y == 1920 - 500 - 44


def test_original_acompanha_a_resolucao_da_fonte():
    geo = caption_geometry("original", canvas_w=1920, canvas_h=1080)
    assert geo.canvas_w == 1920
    assert geo.size < 88
    assert geo.max_width == round(1920 * 0.9)


def test_linhas_respeitam_a_largura():
    fonte = load_font("archivo", "legenda", 88)
    palavras = _palavras("responsabilidade", "empresariamente", "absolutamente", "eu", "fui")
    for linha in group_caption_lines(palavras, fonte, CAPTION_MAX_WIDTH):
        if len(linha) > 1:
            assert fonte.getlength(" ".join(w["text"] for w in linha)) <= CAPTION_MAX_WIDTH


def test_no_maximo_tres_palavras_por_linha():
    fonte = load_font("archivo", "legenda", 40)
    linhas = group_caption_lines(_palavras(*"a b c d e f g".split()), fonte, 742)
    assert [len(l) for l in linhas] == [3, 3, 1]


def test_fim_de_frase_fecha_a_linha():
    fonte = load_font("archivo", "legenda", 40)
    linhas = group_caption_lines(_palavras("Acabou.", "Outra", "frase"), fonte, 742)
    assert [w["text"] for w in linhas[0]] == ["Acabou."]


def _gerar(tmp_path, palavras, modo="word_highlight", style=None, layout="fullscreen"):
    style = style or ClipStyle(legenda=CaptionStyle(estilo="cor", cor="#3EC8FF"))
    saida = tmp_path / "l.ass"
    generate_styled_captions(
        palavras, 0.0, 100.0, modo, str(saida), style, caption_geometry(layout), "Archivo ClipMint Legenda",
    )
    return saida.read_text(encoding="utf-8") if saida.exists() else None


def test_legenda_usa_a_cor_escolhida(tmp_path):
    texto = _gerar(tmp_path, _palavras("eu", "perdi", "tudo"))
    assert r"\1c&HFFC83E&" in texto  # #3EC8FF na ordem do ASS
    assert "FFFF00" not in texto.upper().replace("&H00FFFFFF", "")


def test_legenda_usa_a_fonte_o_tamanho_e_o_contorno(tmp_path):
    texto = _gerar(tmp_path, _palavras("eu"))
    assert "Style: Caption,Archivo ClipMint Legenda,88," in texto
    assert ",1,9,0,5," in texto  # BorderStyle 1, contorno 9, sem sombra, centralizada


def test_legenda_fica_no_centro_da_especificacao(tmp_path):
    assert r"\an5\pos(540,1205)" in _gerar(tmp_path, _palavras("eu"))


def test_uma_palavra_destacada_por_evento(tmp_path):
    texto = _gerar(tmp_path, _palavras("eu", "perdi", "tudo"))
    eventos = [l for l in texto.splitlines() if l.startswith("Dialogue")]
    assert len(eventos) == 3
    for evento in eventos:
        assert evento.count(r"\1c&HFFC83E&") == 1


def test_modo_tradicional_continua_sem_destaque(tmp_path):
    texto = _gerar(tmp_path, _palavras("eu", "perdi", "tudo"), modo="traditional")
    eventos = [l for l in texto.splitlines() if l.startswith("Dialogue")]
    assert len(eventos) == 1
    assert r"\1c" not in eventos[0]
    assert "eu perdi tudo" in eventos[0]


def test_modo_sem_legenda_continua_sem_arquivo(tmp_path):
    assert _gerar(tmp_path, _palavras("eu"), modo="none") is None


def test_palavra_enorme_encolhe_em_vez_de_vazar(tmp_path):
    assert r"\fscx" in _gerar(tmp_path, _palavras("anticonstitucionalissimamente" * 2))


def test_texto_nao_vira_comando_de_ass(tmp_path):
    texto = _gerar(tmp_path, _palavras(r"{\b1}oi"))
    assert r"{\b1}" not in texto


def test_palavra_com_timestamp_alem_do_corte_aparece(tmp_path):
    saida = tmp_path / "l.ass"
    palavras = [{"text": "mano?", "start": 1.0, "end": 3.0}]
    generate_styled_captions(
        palavras, 0.0, 2.0, "word_highlight", str(saida), ClipStyle(), caption_geometry("fullscreen"), "X",
    )
    assert "mano?" in saida.read_text(encoding="utf-8")


# ─── O render ──────────────────────────────────────────────────────────────────

@pytest.fixture
def render(monkeypatch):
    capturado: dict = {}

    async def falso_ffmpeg(*args, description=""):
        capturado["args"] = list(args)
        with open(args[-1], "wb") as f:
            f.write(b"x" * 100)

    async def dimensoes(path):
        return 1920, 1080

    async def sem_qualidade(*a, **k):
        return None

    async def rastreio(*a, **k):
        capturado["rastreou"] = True
        return {
            "center_x": 0.5, "center_y": 0.35, "confidence": 0.9, "method": "mediapipe",
            "keyframes": [(0.0, 0.5), (0.2, 0.52)],
        }

    monkeypatch.setattr(clipper, "run_ffmpeg", falso_ffmpeg)
    monkeypatch.setattr(clipper, "get_video_dimensions", dimensoes)
    monkeypatch.setattr(clipper, "_log_clip_quality", sem_qualidade)
    monkeypatch.setattr(clipper, "track_faces", rastreio)
    monkeypatch.setattr(clipper, "detect_brand_regions", lambda *a, **k: {"qr": [], "static": []})
    monkeypatch.setattr(clipper, "user_watermark_path", lambda *a, **k: None)
    return capturado


def _tela_cheia(style=None, titulo="Perdi tudo", modo="word_highlight"):
    return asyncio.run(
        clipper.cut_fullscreen(
            job_id="j", clip_id="c", video_path="v.mp4", start_time=10.0, end_time=40.0,
            words=[{"text": "oi", "start": 11.0, "end": 11.5}], subtitle_mode=modo,
            banner_text=titulo, keyword="tudo", style=style or ClipStyle(arroba={"texto": "@c"}),
        )
    )


def _cadeia(capturado):
    args = capturado["args"]
    return args[args.index("-filter_complex") + 1]


def test_tela_cheia_ocupa_o_quadro_inteiro(render):
    _tela_cheia()
    cadeia = _cadeia(render)
    assert "scale=1080:1920" in cadeia
    assert "pad=" not in cadeia


def test_tela_cheia_sempre_acompanha_o_rosto(render, monkeypatch):
    monkeypatch.setattr(settings, "face_tracking_enabled", False)
    _tela_cheia()
    assert render["rastreou"] is True
    assert re.search(r"crop@dyn=\d+:1080", _cadeia(render))


def test_tela_cheia_sobrepoe_o_titulo_no_lugar_certo(render):
    _tela_cheia()
    assert "overlay=53:197" in _cadeia(render)


def test_tela_cheia_sem_titulo_nem_arroba_nao_sobrepoe_nada(render):
    _tela_cheia(style=ClipStyle(titulo=TitleStyle(ligado=False)))
    assert "overlay" not in _cadeia(render)


def test_legenda_entra_depois_do_titulo_com_a_pasta_de_fonte(render):
    _tela_cheia()
    cadeia = _cadeia(render)
    assert cadeia.index("overlay=") < cadeia.index("ass=")
    assert "fontsdir=" in cadeia


def test_sem_legenda_nao_ha_ass(render):
    _tela_cheia(modo="none")
    assert "ass=" not in _cadeia(render)
