"""
Legenda "caixa": a palavra falada ganha uma caixa, como opção a mais.

O ASS não faz caixa por palavra. Ela é um desenho vetorial medido com as métricas da
fonte, então o que precisa estar certo é a geometria: a caixa em volta da palavra que
está sendo dita, e só dela. O último teste passa pelo libass de verdade.
"""

import re
import subprocess

import numpy as np
import pytest
from PIL import Image

from app.clip_style import INK, CaptionStyle, ClipStyle, contrast_ratio
from app.config import settings
from app.services.fonts import install_for_render, load_font
from app.services.safe_area import RIGHT_LIMIT_X
from app.services.subtitler import (
    BOX_PADDING_X,
    box_word_gap,
    caption_geometry,
    generate_styled_captions,
    group_caption_lines,
    rounded_box_drawing,
)

ROSA_ASS = r"\1c&H5C37FD&"
INK_ASS = r"\1c&H0C0B0B&"


@pytest.fixture(autouse=True)
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path / "storage"))
    settings.ensure_dirs()


def _palavras(*textos, passo=0.5):
    return [
        {"text": t, "start": i * passo, "end": i * passo + passo * 0.8}
        for i, t in enumerate(textos)
    ]


def _gerar(tmp_path, palavras, estilo="caixa", modo="word_highlight", tamanho="M", layout="fullscreen"):
    style = ClipStyle(legenda=CaptionStyle(estilo=estilo, cor="#FD375C", tamanho=tamanho))
    saida = tmp_path / "l.ass"
    generate_styled_captions(
        palavras, 0.0, 100.0, modo, str(saida), style,
        caption_geometry(layout, tamanho), "Archivo ClipMint Legenda",
    )
    return [l for l in saida.read_text(encoding="utf-8").splitlines() if l.startswith("Dialogue")]


def _caixas(eventos):
    return [e for e in eventos if r"\p1" in e]


def _limites(evento):
    numeros = [int(n) for n in re.findall(r"-?\d+", evento.split(r"\p1}")[1].split("{")[0])]
    xs, ys = numeros[0::2], numeros[1::2]
    return min(xs), min(ys), max(xs), max(ys)


# ─── Uma caixa por estado ──────────────────────────────────────────────────────

def test_uma_caixa_por_palavra_falada(tmp_path):
    eventos = _gerar(tmp_path, _palavras("eu", "perdi", "tudo"))
    assert len(_caixas(eventos)) == 3


def test_caixa_e_palavra_ficam_na_tela_o_mesmo_tempo(tmp_path):
    eventos = _gerar(tmp_path, _palavras("eu", "perdi", "tudo"))
    primeira_caixa = _caixas(eventos)[0].split(",")[1:3]
    assert all(e.split(",")[1:3] == primeira_caixa for e in eventos[:4])


def test_palavra_falada_em_tinta_escura_sem_contorno(tmp_path):
    ativas = [e for e in _gerar(tmp_path, _palavras("eu", "perdi")) if INK_ASS in e]
    assert len(ativas) == 2
    assert all(r"\bord0" in e for e in ativas)


def test_palavras_vizinhas_ficam_brancas_com_contorno(tmp_path):
    eventos = _gerar(tmp_path, _palavras("eu", "perdi"))
    vizinhas = [e for e in eventos if r"\p1" not in e and INK_ASS not in e]
    assert vizinhas and all(r"\bord0" not in e and r"\1c" not in e for e in vizinhas)


def test_caixa_na_cor_escolhida(tmp_path):
    assert ROSA_ASS in _caixas(_gerar(tmp_path, _palavras("eu")))[0]


def test_caixa_fica_atras_do_texto(tmp_path):
    eventos = _gerar(tmp_path, _palavras("eu", "perdi"))
    assert all(e.startswith("Dialogue: 0,") for e in _caixas(eventos))
    assert all(e.startswith("Dialogue: 1,") for e in eventos if r"\p1" not in e)


# ─── As medidas ────────────────────────────────────────────────────────────────

def test_padding_lateral_da_especificacao(tmp_path):
    palavra = "perdi"
    x0, _, x1, _ = _limites(_caixas(_gerar(tmp_path, _palavras(palavra)))[0])
    largura = load_font("archivo", "legenda", 88).getlength(palavra)
    assert x1 - x0 == pytest.approx(largura + 2 * BOX_PADDING_X, abs=2)


def test_sem_padding_vertical(tmp_path):
    _, y0, _, y1 = _limites(_caixas(_gerar(tmp_path, _palavras("perdi")))[0])
    assert y1 - y0 == pytest.approx(sum(load_font("archivo", "legenda", 88).getmetrics()), abs=2)


def test_caixa_centrada_em_y_1205(tmp_path):
    _, y0, _, y1 = _limites(_caixas(_gerar(tmp_path, _palavras("perdi")))[0])
    assert (y0 + y1) / 2 == pytest.approx(1205, abs=1)


def test_cantos_com_raio_de_19():
    desenho = rounded_box_drawing(100, 100, 300, 200, 19)
    assert desenho.startswith("m 119 100 l 281 100 ")
    assert "b " in desenho


def test_raio_nao_passa_de_metade_da_altura():
    desenho = rounded_box_drawing(0, 0, 200, 20, 19)
    assert desenho.startswith("m 10 0 ")


def test_caixa_envolve_a_palavra_certa(tmp_path):
    eventos = _gerar(tmp_path, _palavras("eu", "perdi", "tudo"))
    for caixa, texto in zip(_caixas(eventos), [e for e in eventos if INK_ASS in e]):
        centro_texto = float(re.search(r"\\pos\(([\d.]+),", texto).group(1))
        x0, _, x1, _ = _limites(caixa)
        assert (x0 + x1) / 2 == pytest.approx(centro_texto, abs=1.5)


def test_caixa_nao_encosta_na_palavra_vizinha(tmp_path):
    eventos = _gerar(tmp_path, _palavras("eu", "perdi", "tudo"))
    fonte = load_font("archivo", "legenda", 88)
    caixa_meio = _limites(_caixas(eventos)[1])
    estado = eventos[4:8]
    vizinha = [e for e in estado if e.endswith("tudo")][0]
    centro = float(re.search(r"\\pos\(([\d.]+),", vizinha).group(1))
    assert caixa_meio[2] < centro - fonte.getlength("tudo") / 2


def test_posicao_das_palavras_nao_muda_entre_estados(tmp_path):
    """A linha não pode pular quando a caixa troca de palavra."""
    eventos = _gerar(tmp_path, _palavras("eu", "perdi", "tudo"))
    posicoes: dict[str, set[str]] = {}
    for evento in eventos:
        if r"\p1" in evento:
            continue
        texto = evento.rsplit("}", 1)[1]
        posicoes.setdefault(texto, set()).add(re.search(r"\\pos\(([\d.]+),", evento).group(1))
    assert all(len(v) == 1 for v in posicoes.values())


# ─── Largura e áreas seguras ───────────────────────────────────────────────────

def test_linha_nao_entra_na_coluna_da_direita(tmp_path):
    palavras = _palavras("responsabilidade", "de", "todos", "empresariamente", "falando", "aqui")
    for caixa in _caixas(_gerar(tmp_path, palavras)):
        assert _limites(caixa)[2] <= RIGHT_LIMIT_X


def test_linhas_contam_o_espaco_maior_da_caixa():
    fonte = load_font("archivo", "legenda", 88)
    geo = caption_geometry("fullscreen")
    palavras = _palavras("responsabilidade", "de", "todos")
    linhas = group_caption_lines(palavras, fonte, geo.max_width, gap=box_word_gap(geo))
    assert sum(len(l) for l in linhas) == 3
    for linha in linhas:
        largura = sum(fonte.getlength(w["text"]) for w in linha) + box_word_gap(geo) * (len(linha) - 1)
        assert largura <= geo.max_width or len(linha) == 1


def test_palavra_enorme_encolhe_junto_com_a_caixa(tmp_path):
    eventos = _gerar(tmp_path, _palavras("anticonstitucionalissimamente" * 2))
    x0, _, x1, _ = _limites(_caixas(eventos)[0])
    assert x1 <= RIGHT_LIMIT_X
    assert x0 >= 150
    assert any(r"\fscx" in e for e in eventos)


@pytest.mark.parametrize("tamanho,base", [("P", 88 * 0.85), ("M", 88), ("G", 88 * 1.15)])
def test_tamanhos_mudam_a_caixa(tmp_path, tamanho, base):
    _, y0, _, y1 = _limites(_caixas(_gerar(tmp_path, _palavras("eu"), tamanho=tamanho))[0])
    assert y1 - y0 == pytest.approx(base * 1.09, rel=0.15)


def test_layout_b_usa_o_tamanho_dele(tmp_path):
    _, y0, _, y1 = _limites(_caixas(_gerar(tmp_path, _palavras("eu"), layout="cover"))[0])
    assert y1 - y0 == pytest.approx(sum(load_font("archivo", "legenda", 80).getmetrics()), abs=2)


# ─── É uma opção a mais ────────────────────────────────────────────────────────

def test_estilo_cor_continua_sem_caixa(tmp_path):
    eventos = _gerar(tmp_path, _palavras("eu", "perdi"), estilo="cor")
    assert not _caixas(eventos)
    assert len(eventos) == 2


def test_modo_tradicional_continua_sem_caixa(tmp_path):
    eventos = _gerar(tmp_path, _palavras("eu", "perdi"), modo="traditional")
    assert not _caixas(eventos)


@pytest.mark.parametrize("cor", ["#FD375C", "#FFD23F", "#3EC8FF", "#9DFF4F"])
def test_texto_escuro_se_le_na_paleta(cor):
    assert contrast_ratio(INK, cor) >= 4.5


# ─── Pelo libass de verdade ────────────────────────────────────────────────────

def test_libass_pinta_a_caixa_em_volta_da_palavra(tmp_path):
    """A fonte passa pelo mesmo caminho do render. A caixa é rosa, onde a medida diz."""
    _, pasta = install_for_render("archivo", "legenda", tmp_path)
    ass = tmp_path / "l.ass"
    style = ClipStyle(legenda=CaptionStyle(estilo="caixa", cor="#FD375C"))
    geo = caption_geometry("fullscreen")
    generate_styled_captions(
        [{"text": "perdi", "start": 0.0, "end": 2.0}], 0.0, 2.0, "word_highlight",
        str(ass), style, geo, "Archivo ClipMint Legenda",
    )
    png = tmp_path / "q.png"

    def escapa(caminho) -> str:
        return str(caminho).replace("\\", "/").replace(":", "\\:")

    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=gray:s=1080x1920:d=1",
         "-frames:v", "1", "-vf", f"ass='{escapa(ass)}':fontsdir='{escapa(pasta)}'", str(png)],
        check=True, timeout=60,
    )
    pixels = np.array(Image.open(png).convert("RGB")).astype(int)
    rosa = (abs(pixels[:, :, 0] - 253) < 25) & (abs(pixels[:, :, 1] - 55) < 25) & (abs(pixels[:, :, 2] - 92) < 25)
    ys, xs = np.where(rosa)
    assert len(xs) > 1000
    assert ys.mean() == pytest.approx(1205, abs=4)
    assert xs.mean() == pytest.approx(540, abs=4)
    largura = load_font("archivo", "legenda", 88).getlength("perdi")
    assert xs.max() - xs.min() == pytest.approx(largura + 2 * BOX_PADDING_X, abs=4)
    # A palavra aparece em tinta escura dentro da caixa, e ocupa a largura que o Pillow
    # mediu. Sem isto o texto saía 31% menor que a medida, e sobrava caixa dos dois lados:
    # o libass mede a fonte pelas métricas de Windows, e o Pillow pelas tipográficas.
    miolo = pixels[ys.min():ys.max(), xs.min():xs.max()]
    escuro = miolo.sum(axis=2) < 90
    assert escuro.sum() > 500
    colunas = np.where(escuro.any(axis=0))[0]
    # A medida inclui o espaço lateral das letras, e a tinta não: daí a folga.
    assert colunas.max() - colunas.min() == pytest.approx(largura, abs=16)
    assert colunas.min() == pytest.approx(BOX_PADDING_X, abs=10)
    # E centrada na altura: as duas métricas têm centros de linha diferentes.
    linhas = np.where(escuro.any(axis=1))[0]
    assert (linhas.min() + linhas.max()) / 2 == pytest.approx(miolo.shape[0] / 2, abs=10)
