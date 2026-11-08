"""
Layout B: a faixa do título e a regra da capa.

A escolha da capa é testada sem abrir vídeo nenhum: as regras recebem o que já se sabe
sobre cada quadro. O julgamento de "é mesmo uma reação" é feito nos quadros de um
render real, com o resultado registrado em D138.
"""

import asyncio

import numpy as np
import pytest
from PIL import Image

from app.clip_style import ClipStyle, TitleStyle
from app.config import settings
from app.services import clipper
from app.services.cover_picker import (
    RULE_NEUTRAL,
    RULE_NO_FACE,
    RULE_OTHER,
    RULE_OTHER_LOUD,
    RULE_SPEAKER,
    FrameInfo,
    camera_references,
    choose_cover,
    color_signature,
    expression_score,
    loud_moments,
    main_camera,
    nearest_camera,
)
from app.services.safe_area import unsafe_areas
from app.services.title_card import (
    BAND_BORDER,
    BAND_H,
    BAND_TEXT_RIGHT,
    BAND_TITLE_SIZE,
    BAND_W,
    band_handle_color,
    generate_cover_band,
)

GANCHOS_REAIS = [
    "A política virou guerra, eu perdi 200 mil",
    "Minha mulher vota diferente de mim, e tudo bem",
    "Posso ganhar quanto for, sempre vou me identificar",
    "Rico ou pobre, não consigo me libertar disso",
]


@pytest.fixture(autouse=True)
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path / "storage"))
    settings.ensure_dirs()


# ─── As regras da capa ─────────────────────────────────────────────────────────

def _quadro(t=0.0, camera=0, rosto=True, expressao=0.0, alto=False, area=0.05):
    return FrameInfo(time=t, camera=camera, has_face=rosto, expression=expressao, loud=alto, area=area)


#: Câmera 0 aparece mais: é a de quem fala embaixo.
def _base():
    return [_quadro(t=float(i), camera=0, expressao=0.1) for i in range(10)]


def test_camera_que_mais_aparece_e_a_de_quem_fala():
    assert main_camera(_base() + [_quadro(camera=1)]) == 0


def test_regra_1_e_2_outro_rosto_em_momento_alto_vence():
    alvo = _quadro(t=20, camera=1, expressao=0.5, alto=True)
    quadros = _base() + [_quadro(t=21, camera=1, expressao=0.9), _quadro(t=22, camera=0, expressao=0.95, alto=True), alvo]
    escolha = choose_cover(quadros)
    assert escolha.frame is alvo
    assert escolha.rule == RULE_OTHER_LOUD


def test_regra_2_outro_rosto_mesmo_fora_do_momento_alto():
    alvo = _quadro(t=20, camera=1, expressao=0.5)
    quadros = _base() + [_quadro(t=22, camera=0, expressao=0.95, alto=True), alvo]
    escolha = choose_cover(quadros)
    assert escolha.frame is alvo
    assert escolha.rule == RULE_OTHER


def test_regra_3_so_quem_fala_usa_a_expressao_mais_forte():
    alvo = _quadro(t=20, camera=0, expressao=0.7)
    escolha = choose_cover(_base() + [alvo])
    assert escolha.frame is alvo
    assert escolha.rule == RULE_SPEAKER


def test_regra_3_prefere_o_momento_alto():
    alvo = _quadro(t=20, camera=0, expressao=0.5, alto=True)
    escolha = choose_cover(_base() + [_quadro(t=21, camera=0, expressao=0.9), alvo])
    assert escolha.frame is alvo


def test_outra_pessoa_neutra_nao_vence_a_reacao_de_quem_fala():
    """Um rosto diferente de cara parada não é a prévia de nada."""
    alvo = _quadro(t=20, camera=0, expressao=0.7)
    escolha = choose_cover(_base() + [_quadro(t=21, camera=1, expressao=0.1, alto=True), alvo])
    assert escolha.frame is alvo


def test_nunca_escolhe_quadro_neutro_havendo_outro():
    quadros = _base() + [_quadro(t=20, camera=0, expressao=0.4)]
    assert choose_cover(quadros).frame.expression >= 0.32


def test_sem_nenhuma_reacao_avisa_na_regra():
    escolha = choose_cover(_base())
    assert escolha.rule == RULE_NEUTRAL


def test_sem_rosto_usa_o_meio():
    quadros = [_quadro(t=float(i), rosto=False) for i in range(5)]
    escolha = choose_cover(quadros)
    assert escolha.rule == RULE_NO_FACE
    assert escolha.frame.time == 2.0


def test_sem_quadros_nao_ha_escolha():
    assert choose_cover([]) is None


def test_empate_vai_para_o_maior_rosto():
    grande = _quadro(t=20, camera=1, expressao=0.5, area=0.2)
    assert choose_cover(_base() + [_quadro(t=21, camera=1, expressao=0.5, area=0.05), grande]).frame is grande


# ─── Momentos altos ────────────────────────────────────────────────────────────

def test_acha_o_pico_acima_da_fala():
    niveis = np.full(1200, -25.0)  # 60s em blocos de 50ms
    niveis[400:440] = -15.0  # 20s a 22s, 10 dB acima
    picos = loud_moments(niveis)
    assert len(picos) == 1
    assert 20.0 <= picos[0] <= 22.0


def test_sem_pico_nao_ha_momento_alto():
    assert loud_moments(np.full(1200, -25.0)) == []


def test_picos_vem_do_mais_alto_para_o_mais_baixo():
    niveis = np.full(1200, -25.0)
    niveis[200:240] = -18.0
    niveis[800:840] = -12.0
    picos = loud_moments(niveis)
    assert picos[0] > 40
    assert picos[1] < 20


def test_um_pico_nao_vira_varios():
    niveis = np.full(1200, -25.0)
    niveis[400:500] = -15.0
    assert len(loud_moments(niveis)) <= 3


def test_audio_curto_ou_mudo_nao_quebra():
    assert loud_moments(np.empty(0)) == []
    assert loud_moments(np.full(5, -25.0)) == []
    assert loud_moments(np.full(1200, -120.0)) == []


# ─── Câmeras ───────────────────────────────────────────────────────────────────

def _cenario(cor_lateral, cor_centro=(40, 40, 40)):
    imagem = np.zeros((90, 160, 3), dtype=np.uint8)
    imagem[:] = cor_lateral
    imagem[:, 40:120] = cor_centro
    return imagem


AMARELO_BGR, AZUL_BGR = (0, 200, 240), (160, 40, 10)


def test_mesmo_cenario_com_gente_diferente_no_centro_e_a_mesma_camera():
    a = color_signature(_cenario(AMARELO_BGR, (10, 10, 200)))
    b = color_signature(_cenario(AMARELO_BGR, (200, 200, 10)))
    assert len(camera_references([a, b])) == 1


def test_cenarios_diferentes_sao_cameras_diferentes():
    a = color_signature(_cenario(AMARELO_BGR))
    b = color_signature(_cenario(AZUL_BGR))
    assert len(camera_references([a, b, a])) == 2


def test_quadro_vai_para_a_camera_mais_parecida():
    a = color_signature(_cenario(AMARELO_BGR))
    b = color_signature(_cenario(AZUL_BGR))
    referencias = camera_references([a, b])
    assert nearest_camera(color_signature(_cenario(AZUL_BGR, (90, 90, 90))), referencias) == 1
    assert nearest_camera(color_signature(_cenario(AMARELO_BGR, (90, 90, 90))), referencias) == 0


# ─── Expressão ─────────────────────────────────────────────────────────────────

class _Ponto:
    def __init__(self, x, y):
        self.x, self.y = x, y


def _rosto(abertura, largura_boca, olhos=0.4):
    pontos = {i: _Ponto(0.5, 0.5) for i in range(300)}
    pontos[13], pontos[14] = _Ponto(0.5, 0.6), _Ponto(0.5, 0.6 + abertura)
    pontos[61], pontos[291] = _Ponto(0.5 - largura_boca / 2, 0.62), _Ponto(0.5 + largura_boca / 2, 0.62)
    pontos[33], pontos[263] = _Ponto(0.5 - olhos / 2, 0.4), _Ponto(0.5 + olhos / 2, 0.4)
    return pontos


def test_boca_aberta_pontua_mais_que_fechada():
    assert expression_score(_rosto(0.15, 0.2)) > expression_score(_rosto(0.0, 0.2))


def test_sorriso_de_boca_fechada_pontua():
    """É o que pega a reação com o microfone na frente da boca."""
    assert expression_score(_rosto(0.0, 0.34)) > expression_score(_rosto(0.0, 0.2))


def test_rosto_neutro_fica_abaixo_do_limiar():
    assert expression_score(_rosto(0.01, 0.2)) < 0.32


def test_rosto_sem_boca_detectada_nao_quebra():
    assert expression_score(_rosto(0.0, 0.0)) == 0.0


# ─── A faixa ───────────────────────────────────────────────────────────────────

def _faixa(tmp_path, titulo="Perdi tudo", keyword="tudo", style=None):
    saida = tmp_path / "f.png"
    style = style or ClipStyle(arroba={"texto": "@conta"})
    plano = generate_cover_band(titulo, keyword, style, str(saida))
    return plano, Image.open(saida).convert("RGB")


def test_faixa_tem_as_medidas_da_especificacao(tmp_path):
    _, imagem = _faixa(tmp_path)
    assert imagem.size == (BAND_W, BAND_H) == (1080, 256)


def test_borda_de_8px_em_cima_e_embaixo_na_cor_da_marca(tmp_path):
    _, imagem = _faixa(tmp_path, style=ClipStyle(marca="#3EC8FF"))
    ciano = (62, 200, 255)
    assert BAND_BORDER == 8
    for y in (0, 7, 248, 255):
        assert imagem.getpixel((5, y)) == ciano
    assert imagem.getpixel((5, 8)) == (11, 11, 12)
    assert imagem.getpixel((5, 247)) == (11, 11, 12)


def test_identidade_azul_e_amarela_na_faixa(tmp_path):
    style = ClipStyle(marca="#FAC007", titulo=TitleStyle(fundo="#032DA5", texto="#FAC007"))
    _, imagem = _faixa(tmp_path, style=style)
    assert imagem.getpixel((5, 100)) == (3, 45, 165)
    assert imagem.getpixel((5, 2)) == (250, 192, 7)


@pytest.mark.parametrize("gancho", GANCHOS_REAIS)
def test_texto_da_faixa_nao_vaza_nem_entra_em_area_segura(tmp_path, gancho):
    plano, _ = _faixa(tmp_path, gancho)
    for rect in plano.rects:
        assert rect.x + rect.w <= BAND_TEXT_RIGHT
        assert unsafe_areas(rect) == []
    alturas = [r.y + r.h for r in plano.rects]
    assert max(alturas) <= 800 + BAND_H - BAND_BORDER


def test_titulo_que_nao_cabe_diminui(tmp_path):
    plano, _ = _faixa(tmp_path, "Posso ganhar quanto for, sempre vou me identificar com isso tudo aqui")
    assert plano.size < BAND_TITLE_SIZE


def test_titulo_curto_fica_no_tamanho_da_especificacao(tmp_path):
    plano, _ = _faixa(tmp_path)
    assert plano.size == BAND_TITLE_SIZE == 67


def test_arroba_uma_vez_so_abaixo_do_titulo(tmp_path):
    plano, _ = _faixa(tmp_path)
    assert len(plano.rects) == len(plano.lines) + 1
    assert plano.rects[-1].y > plano.rects[0].y


def test_arroba_no_cinza_da_especificacao():
    assert band_handle_color(ClipStyle()) == "#C9C9CF"


def test_arroba_troca_de_cor_onde_o_cinza_nao_se_le():
    style = ClipStyle(marca="#000000", titulo=TitleStyle(fundo="#E8E8E8", texto="#000000"))
    assert band_handle_color(style) == "#000000"


def test_faixa_sem_titulo_nem_arroba_ainda_existe(tmp_path):
    plano, imagem = _faixa(tmp_path, style=ClipStyle(titulo=TitleStyle(ligado=False)))
    assert plano.rects == []
    assert imagem.size == (1080, 256)


def test_palavra_chave_na_cor_da_marca(tmp_path):
    _, imagem = _faixa(tmp_path, "Perdi 200 mil", "200", ClipStyle(marca="#3EC8FF"))
    miolo = imagem.crop((0, 8, BAND_W, BAND_H - 8))
    assert (62, 200, 255) in {miolo.getpixel((x, y)) for x in range(0, 700, 2) for y in range(0, 240, 2)}


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
        return {
            "center_x": 0.5, "center_y": 0.35, "confidence": 0.9, "method": "mediapipe",
            "keyframes": [(0.0, 0.5), (0.2, 0.52)],
        }

    def capa_falsa(video, ini, fim, saida, w, h, **k):
        capturado["capa"] = (w, h)
        Image.new("RGB", (w, h)).save(saida)
        return "regra de teste"

    monkeypatch.setattr(clipper, "run_ffmpeg", falso_ffmpeg)
    monkeypatch.setattr(clipper, "get_video_dimensions", dimensoes)
    monkeypatch.setattr(clipper, "_log_clip_quality", sem_qualidade)
    monkeypatch.setattr(clipper, "track_faces", rastreio)
    monkeypatch.setattr(clipper, "generate_reaction_cover", capa_falsa)
    monkeypatch.setattr(clipper, "detect_brand_regions", lambda *a, **k: {"qr": [], "static": []})
    monkeypatch.setattr(clipper, "user_watermark_path", lambda *a, **k: None)
    return capturado


def _capa_e_faixa(caplog=None):
    return asyncio.run(
        clipper.cut_cover(
            job_id="j", clip_id="c", video_path="v.mp4", start_time=10.0, end_time=40.0,
            words=[{"text": "oi", "start": 11.0, "end": 11.5}], subtitle_mode="word_highlight",
            banner_text="Perdi tudo", keyword="tudo", style=ClipStyle(arroba={"texto": "@c"}),
        )
    )


def _cadeia(capturado):
    args = capturado["args"]
    return args[args.index("-filter_complex") + 1]


def test_geometria_do_layout_b(render):
    _capa_e_faixa()
    cadeia = _cadeia(render)
    assert render["capa"] == (1080, 800)
    assert "scale=1080:864" in cadeia
    assert "pad=1080:1920:0:1056" in cadeia
    assert "overlay=0:0" in cadeia
    assert "overlay=0:800" in cadeia


def test_quem_fala_e_recortado_na_proporcao_do_painel(render):
    _capa_e_faixa()
    # 1080x864 = 1,25: uma fonte de 1080 de altura dá 1350 de largura.
    assert "crop@dyn=1350:1080" in _cadeia(render)


def test_faixa_antiga_do_arroba_repetido_saiu(render, monkeypatch):
    def nao_pode(*a, **k):
        raise AssertionError("a faixa antiga não deveria ser desenhada")

    monkeypatch.setattr(clipper, "generate_divider_bar", nao_pode)
    _capa_e_faixa()


def test_legenda_entra_por_ultimo(render):
    _capa_e_faixa()
    cadeia = _cadeia(render)
    assert cadeia.index("overlay=0:800") < cadeia.index("ass=")


def test_o_log_diz_qual_regra_decidiu(render, caplog):
    import logging

    with caplog.at_level(logging.INFO, logger="app.services.clipper"):
        _capa_e_faixa()
    assert "regra de teste" in caplog.text
