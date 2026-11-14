"""
O filtergraph que o render monta — travado por caracterização.

Estes testes não existem para descrever o que o filtro DEVERIA ser: existem
para congelar o que ele É, antes de mexer no código que o monta. O
`cut_and_crop` tinha os componentes testados (capa, banner, faixa, marca) mas
nada cobria a montagem — e é ali que uma refatoração quebra o vídeo de um jeito
que só aparece assistindo.

Tudo em volta é dublê: o que importa é a string que chega ao FFmpeg.
"""

import asyncio

import pytest

from app.config import settings
from app.services import clipper


@pytest.fixture
def render(tmp_path, monkeypatch):
    """Roda o cut_and_crop com tudo dublado e devolve (inputs, chain)."""
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path))
    settings.ensure_dirs()

    capturado: dict = {}

    async def falso_ffmpeg(*args, description=""):
        capturado["args"] = list(args)
        # O arquivo final precisa existir: o chamador lê o tamanho dele.
        destino = args[-1]
        with open(destino, "wb") as f:
            f.write(b"x" * 100)

    async def sem_dimensoes(path):
        return 1920, 1080

    async def sem_qualidade(*a, **k):
        return None

    monkeypatch.setattr(clipper, "run_ffmpeg", falso_ffmpeg)
    monkeypatch.setattr(clipper, "get_video_dimensions", sem_dimensoes)
    monkeypatch.setattr(clipper, "_log_clip_quality", sem_qualidade)
    monkeypatch.setattr(clipper, "generate_cover", lambda *a, **k: "dublê")

    async def sem_rosto(*a, **k):
        # O que o tracker devolve quando não acha rosto: o recorte central.
        return {"method": "static", "center_x": 0.5, "center_y": 0.5,
                "confidence": 1.0, "keyframes": []}

    monkeypatch.setattr(clipper, "track_faces", sem_rosto)

    # Fora do `executar`, para um teste poder trocar os dois e ver o que receberam.
    monkeypatch.setattr(clipper, "generate_banner", lambda *a, **k: (1080, 226))
    monkeypatch.setattr(clipper, "generate_divider_bar", lambda *a, **k: None)

    def executar(*, marcas=None, watermark=None, banner="", bar_name="",
                 subtitle_mode="none", style=None, **kwargs):
        from app.clip_style import ClipStyle, HandleStyle

        style = style or ClipStyle(arroba=HandleStyle(texto=bar_name))
        monkeypatch.setattr(
            clipper, "detect_brand_regions",
            lambda *a, **k: {"qr": (marcas or {}).get("qr", []),
                             "static": (marcas or {}).get("static", [])},
        )
        monkeypatch.setattr(clipper, "user_watermark_path", lambda *a, **k: watermark)
        monkeypatch.setattr(clipper, "generate_ass_subtitles", lambda **k: None)

        asyncio.run(
            clipper.cut_and_crop(
                job_id="job", clip_id="clip", video_path="/fonte.mp4",
                start_time=10.0, end_time=40.0,
                words=[{"text": "oi", "start": 10.0, "end": 10.4, "confidence": 0.9}],
                subtitle_mode=subtitle_mode, banner_text=banner, style=style, **kwargs,
            )
        )
        args = capturado["args"]
        chain = args[args.index("-filter_complex") + 1]
        return args, chain

    return executar


def test_corte_simples_sem_nada_extra(render):
    """Crop centralizado, capa por cima, sem banner, sem faixa, sem legenda."""
    args, chain = render()

    # O crop NÃO é 9:16: o painel de vídeo é 1080x1152 (o resto do canvas é
    # capa), então a proporção do recorte é 0,9375 — daí 1012 de largura numa
    # fonte 1920x1080, centralizado em x=454.
    assert chain == (
        "[0:v]crop=1012:1080:454:0,scale=1080:1152:flags=lanczos,"
        "pad=1080:1920:0:768:black[base];"
        "[base][1:v]overlay=0:0[withcover];"
        "[withcover]setsar=1[outv]"
    )
    # O seek é ANTES do -i: é o que torna o corte exato e zera o timestamp
    # do filtergraph.
    assert args[:4] == ["-ss", "10.0", "-i", "/fonte.mp4"]
    assert args[args.index("-t") + 1] == "30.0"


def test_legenda_entra_no_fim_da_cadeia(render):
    _, chain = render(subtitle_mode="word_highlight")
    assert chain.endswith("setsar=1[outv]")
    assert ",ass=" in chain or "]ass=" in chain


def test_banner_vira_uma_sobreposicao(render):
    _, chain = render(banner="Um gancho")
    assert "[withcover][2:v]overlay=(main_w-overlay_w)/2:" in chain
    assert "[withbanner]" in chain


def test_marca_de_terceiro_e_borrada_antes_do_crop(render):
    """
    A ordem importa: delogo nas coordenadas da FONTE, antes de cortar.

    Invertido, a região borrada não corresponderia ao que está na tela.
    """
    _, chain = render(marcas={"static": [(100, 50, 200, 80)]})
    assert chain.index("delogo") < chain.index("crop=")
    assert chain.startswith("[0:v]delogo=")
    assert "[clean]" in chain


def test_qr_recebe_a_logo_do_usuario_por_cima(render, tmp_path):
    from PIL import Image

    logo = tmp_path / "logo.png"
    Image.new("RGBA", (100, 100), "#fff").save(logo)

    _, chain = render(marcas={"qr": [(10, 20, 120, 120)]}, watermark=str(logo))
    assert "[ws0]overlay=" in chain
    assert "[qr0]" in chain


def test_faixa_da_conta_so_sai_com_nome_configurado(render):
    _, sem = render(bar_name="")
    assert "withbar" not in sem

    _, com = render(bar_name="@minhaconta")
    assert "[withbar]" in com


def test_titulo_e_arroba_desligados_no_estilo_tiram_banner_e_faixa(render):
    from app.clip_style import ClipStyle, HandleStyle, TitleStyle

    estilo = ClipStyle(
        titulo=TitleStyle(ligado=False),
        arroba=HandleStyle(texto="@minhaconta", ligado=False),
    )
    _, chain = render(banner="Um gancho", style=estilo)
    assert "withbanner" not in chain
    assert "withbar" not in chain


def test_banner_e_faixa_usam_as_cores_do_estilo(render, monkeypatch):
    from app.clip_style import ClipStyle, HandleStyle, TitleStyle

    chamadas = {}
    monkeypatch.setattr(
        clipper, "generate_banner",
        lambda *a, **k: chamadas.setdefault("banner", a) and (1080, 226),
    )
    monkeypatch.setattr(
        clipper, "generate_divider_bar", lambda *a, **k: chamadas.setdefault("faixa", a)
    )
    estilo = ClipStyle(
        marca="#FFD23F",
        titulo=TitleStyle(fundo="#022DA5", texto="#FFFFFF"),
        arroba=HandleStyle(texto="@hzpodclips"),
        fonte="condensed",
    )
    render(banner="Um gancho", style=estilo)
    assert chamadas["banner"][2:5] == ("#022DA5", "#FFFFFF", "condensed")
    assert chamadas["faixa"][4:8] == ("@hzpodclips", "#022DA5", "#FFD23F", "condensed")


def test_marca_dagua_ligada_no_layout_entra_antes_da_legenda(render, monkeypatch, tmp_path):
    from app.clip_style import ClipStyle, WatermarkPlacement

    arte = tmp_path / "arte.png"
    arte.write_bytes(b"x")
    monkeypatch.setattr(clipper, "clip_watermark_path", lambda *a, **k: str(arte))
    estilo = ClipStyle()
    estilo.marca_dagua["cover"] = WatermarkPlacement(ligado=True, x=0.5, y=0.25)

    args, chain = render(style=estilo, subtitle_mode="word_highlight")
    assert str(arte) in args
    assert "overlay=540-overlay_w/2:480-overlay_h/2[withwm]" in chain
    assert chain.index("[withwm]") < chain.index("ass=")


def test_marca_dagua_desligada_no_layout_nao_entra(render, monkeypatch, tmp_path):
    arte = tmp_path / "arte.png"
    arte.write_bytes(b"x")
    monkeypatch.setattr(clipper, "clip_watermark_path", lambda *a, **k: str(arte))

    args, chain = render()
    assert str(arte) not in args
    assert "withwm" not in chain
