"""
Testes da geometria do modo streamer (facecam + gameplay).

Cobrem só as partes determinísticas — o que depende de MediaPipe/OpenCV
(detecção em si) não entra aqui.
"""

import numpy as np
import pytest

from app.services.facecam import (
    FacecamRect,
    _box_from_face,
    _fit_cam_rect,
    default_rect,
    dodge_margin,
    gameplay_crop_x,
    rect_from_dict,
)
from app.services.clipper import _gameplay_crop_size
from app.services.layout import StreamerGeometry


# ─── Encaixe nas bordas da cam ────────────────────────────────────────────────

def _fake_frame(cam: tuple[int, int, int, int], w: int = 480, h: int = 270, shelf: int = 0):
    """
    Frame sintético: fundo liso (gameplay) com o retângulo da cam por cima,
    claro e com textura interna. `shelf` desenha uma faixa clara dentro da cam
    — uma prateleira atrás do streamer, o distrator que mais engana o encaixe.
    """
    rng = np.random.default_rng(7)
    # Fundo liso com um respingo de ruído. Uma rampa suave pareceria mais
    # realista, mas o banding de 1 unidade do uint8 vira uma "linha" perfeita
    # atravessando a tela — artefato do frame de teste, não do vídeo.
    frame = 80 + rng.normal(0, 1.5, (h, w)).astype("float32")

    x, y, cw, ch = cam
    frame[y:y + ch, x:x + cw] = 200 + rng.normal(0, 12, (ch, cw))
    if shelf:
        frame[shelf:shelf + 3, x:x + cw] = 30
    return np.clip(frame, 0, 255).astype("uint8")


def _maps(frame):
    """(gx, gy) como _edge_maps devolve — com um frame só, é o próprio gradiente."""
    f = frame.astype("float32")
    return np.abs(np.diff(f, axis=1)), np.abs(np.diff(f, axis=0))


def _pixels(rect: FacecamRect, w: int = 480, h: int = 270) -> tuple[int, int, int, int]:
    return (
        round(rect.x * w), round(rect.y * h),
        round((rect.x + rect.w) * w), round((rect.y + rect.h) * h),
    )


def test_fit_cam_rect_locks_onto_a_corner_cam():
    """Cam encostada no canto: as duas bordas internas são achadas, as outras
    duas são as bordas do frame."""
    gx, gy = _maps(_fake_frame((0, 0, 200, 140)))

    rect = _fit_cam_rect(gx, gy, 100 / 480, 60 / 270, 30 / 480, 40 / 270, np)

    assert rect is not None
    x0, y0, x1, y1 = _pixels(rect)
    assert 0 <= x0 <= 6 and 0 <= y0 <= 6           # borda do frame + recuo
    assert 193 <= x1 <= 200 and 133 <= y1 <= 140   # borda real - recuo


def test_fit_cam_rect_locks_onto_a_floating_cam():
    """Cam sem encostar em borda nenhuma: as quatro bordas vêm do gradiente."""
    gx, gy = _maps(_fake_frame((120, 60, 180, 120)))

    rect = _fit_cam_rect(gx, gy, 210 / 480, 120 / 270, 26 / 480, 34 / 270, np)

    assert rect is not None
    x0, y0, x1, y1 = _pixels(rect)
    assert 120 <= x0 <= 126 and 60 <= y0 <= 66
    assert 294 <= x1 <= 300 and 174 <= y1 <= 180


def test_fit_cam_rect_never_bleeds_outside_the_cam():
    """A caixa devolvida cabe inteira dentro da cam real — a garantia que
    importa: nenhum pixel de gameplay no painel."""
    cam = (60, 40, 220, 150)
    gx, gy = _maps(_fake_frame(cam))

    rect = _fit_cam_rect(gx, gy, 170 / 480, 115 / 270, 30 / 480, 40 / 270, np)

    assert rect is not None
    x0, y0, x1, y1 = _pixels(rect)
    assert x0 >= cam[0] and y0 >= cam[1]
    assert x1 <= cam[0] + cam[2] and y1 <= cam[1] + cam[3]


def test_fit_cam_rect_ignores_a_shelf_crossing_the_face():
    """
    Regressão de live real: uma prateleira atrás do streamer pontua MAIS que a
    borda de cima da cam (que caía num trecho escuro). Como ela cruza a altura
    do rosto, fica fora da disputa — nenhuma borda da cam corta a cara dele.
    """
    cam = (0, 0, 200, 140)
    gx, gy = _maps(_fake_frame(cam, shelf=55))

    # Rosto entre as linhas 45 e 95: a prateleira em 55 cai dentro dele
    rect = _fit_cam_rect(gx, gy, 100 / 480, 70 / 270, 30 / 480, 50 / 270, np)

    assert rect is not None
    _, y0, _, y1 = _pixels(rect)
    assert y0 <= 6, "topo travou na prateleira em vez da borda da cam"
    assert 133 <= y1 <= 140


def test_edge_maps_keep_static_borders_and_dilute_moving_content(tmp_path):
    """
    O mapa de bordas é a média do gradiente de cada frame, e é isso que faz o
    encaixe funcionar: a borda da cam está no mesmo pixel em todo frame e
    sobrevive inteira; o que se move espalha o gradiente e se dilui. (Com o
    gradiente do frame MEDIANO, que era a versão anterior, a borda chegava
    fraca porque a mediana borra o conteúdo dos dois lados dela.)
    """
    import cv2

    from app.services.facecam import _edge_maps

    paths = []
    for i in range(6):
        frame = np.full((120, 200), 40, dtype="uint8")
        frame[:, 100:] = 200                       # borda estática na coluna 99
        frame[:, 20 + i * 8:28 + i * 8] = 255      # barra que anda a cada frame
        path = tmp_path / f"f_{i:02d}.png"
        cv2.imwrite(str(path), frame)
        paths.append(str(path))

    gx, _ = _edge_maps(paths, cv2, np)

    static_border = float(gx[:, 99].mean())
    moving_content = float(gx[:, 20:90].max())
    assert static_border > 100
    assert moving_content < static_border / 2


def test_fit_cam_rect_finds_a_low_contrast_border_over_a_bright_hud():
    """
    Regressão de live real (jogo escuro): a borda de baixo da cam era o ombro
    preto do streamer contra cenário preto — gradiente médio 2.0 — enquanto o
    HUD do jogo lá embaixo marcava 56. Com limiar global a borda da cam tinha
    suporte 0.00 e o encaixe travava no HUD, esticando a cam até o rodapé.

    O limiar local enxerga a borda fraca e o prior de proporção rejeita a caixa
    que iria até o HUD (ela não tem cara de webcam).
    """
    rng = np.random.default_rng(3)
    frame = 20 + rng.normal(0, 1.5, (270, 480)).astype("float32")
    frame[0:143, 0:210] = 90 + rng.normal(0, 8, (143, 210))     # cam
    # Ombro escuro com contorno curvo: escurece a base da cam sem criar uma
    # linha reta atravessando ela (ombro reto seria um distrator artificial).
    for col in range(210):
        top = 100 + int(14 * np.sin(col / 210 * np.pi))
        frame[top:143, col] = 25 + rng.normal(0, 1.5, 143 - top)
    frame[239:242, 40:200] = 200                                # HUD do jogo
    gx, gy = _maps(np.clip(frame, 0, 255).astype("uint8"))

    rect = _fit_cam_rect(gx, gy, 100 / 480, 60 / 270, 30 / 480, 50 / 270, np)

    assert rect is not None
    _, y0, _, y1 = _pixels(rect)
    assert y0 <= 6
    assert 130 <= y1 <= 143, f"base foi para {y1} — travou no HUD do jogo"


def test_aspect_weight_prefers_a_webcam_shaped_box():
    """Uma caixa que vai do topo da tela até o rodapé não é uma webcam."""
    from app.services.facecam import _aspect_weight

    assert _aspect_weight(200, 140) > 0.9     # ~4:3
    assert _aspect_weight(200, 112) > 0.9     # ~16:9
    assert _aspect_weight(200, 480) < 0.2     # esticada até o rodapé
    assert _aspect_weight(200, 40) < 0.3      # tira horizontal


def test_fit_cam_rect_gives_up_without_borders():
    """Frame liso (sem cam nenhuma): sem linha, o encaixe falha e a detecção
    cai para a caixa derivada do rosto."""
    gx, gy = _maps((np.ones((270, 480)) * 120).astype("uint8"))

    assert _fit_cam_rect(gx, gy, 0.5, 0.5, 0.1, 0.15, np) is None


def test_to_pixels_rounds_inward_so_no_gameplay_leaks_in():
    """Origem arredonda para cima e o tamanho para baixo: a caixa em pixels
    nunca ultrapassa a caixa detectada."""
    rect = FacecamRect(x=0.1005, y=0.2005, w=0.3009, h=0.2009)

    x, y, w, h = rect.to_pixels(1000, 1000)

    assert x >= 0.1005 * 1000
    assert y >= 0.2005 * 1000
    assert x + w <= (0.1005 + 0.3009) * 1000
    assert y + h <= (0.2005 + 0.2009) * 1000
    assert (x % 2, y % 2, w % 2, h % 2) == (0, 0, 0, 0)


# ─── Geometria dos painéis ────────────────────────────────────────────────────

def test_geometry_4k_panes_fill_canvas_exactly():
    geo = StreamerGeometry(2160, 0.35, 0.029)

    assert (geo.canvas_w, geo.canvas_h) == (2160, 3840)
    assert geo.facecam_h + geo.bar_h + geo.game_h == geo.canvas_h
    assert geo.game_y == geo.facecam_h + geo.bar_h


@pytest.mark.parametrize("width", [1080, 1440, 2160, 3840])
def test_geometry_panes_are_even_at_any_width(width):
    """x264 em yuv420p exige dimensões pares — cada painel é escalado sozinho."""
    geo = StreamerGeometry(width, 0.35, 0.029)

    assert geo.canvas_w % 2 == 0
    assert geo.canvas_h % 2 == 0
    assert geo.facecam_h % 2 == 0
    assert geo.game_h % 2 == 0
    assert geo.facecam_h + geo.bar_h + geo.game_h == geo.canvas_h


def test_geometry_facecam_pane_is_landscape_and_game_is_portrait():
    geo = StreamerGeometry(2160, 0.35, 0.029)

    assert geo.facecam_aspect > 1.0   # painel da cam é deitado
    assert geo.game_aspect < 1.0      # fatia de gameplay é em pé


# ─── Caixa da facecam ─────────────────────────────────────────────────────────

def test_to_pixels_produces_even_box_inside_frame():
    rect = FacecamRect(x=0.7, y=0.6, w=0.3, h=0.4)

    x, y, w, h = rect.to_pixels(1920, 1080)

    assert (x % 2, y % 2, w % 2, h % 2) == (0, 0, 0, 0)
    assert x + w <= 1920 and y + h <= 1080


def test_to_pixels_clamps_box_that_would_spill_out():
    rect = FacecamRect(x=0.95, y=0.95, w=0.5, h=0.5)

    x, y, w, h = rect.to_pixels(1920, 1080)

    assert x + w <= 1920
    assert y + h <= 1080


def test_box_from_face_matches_requested_pane_aspect():
    geo = StreamerGeometry(2160, 0.35, 0.029)

    rect = _box_from_face(0.5, 0.5, face_h=0.2, box_aspect=geo.facecam_aspect)

    # A caixa é fração da fonte: converter para pixels de um frame 16:9
    # deve devolver a proporção do painel.
    pixel_aspect = (rect.w * 1920) / (rect.h * 1080)
    assert pixel_aspect == pytest.approx(geo.facecam_aspect, rel=0.02)


def test_default_rect_sits_in_bottom_right_corner():
    rect = default_rect(16 / 9)

    assert rect.x + rect.w == pytest.approx(1.0)
    assert rect.y + rect.h == pytest.approx(1.0)
    assert rect.method == "default_corner"


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"x": 0.1, "y": 0.1},                       # faltando w/h
        {"x": 0.1, "y": 0.1, "w": 0, "h": 0.2},     # largura zero
        {"x": 1.2, "y": 0.1, "w": 0.2, "h": 0.2},   # fora do frame
        {"x": "a", "y": 0.1, "w": 0.2, "h": 0.2},   # tipo inválido
    ],
)
def test_rect_from_dict_rejects_invalid_payloads(payload):
    assert rect_from_dict(payload) is None


def test_rect_from_dict_accepts_valid_payload():
    rect = rect_from_dict({"x": 0.72, "y": 0.6, "w": 0.28, "h": 0.4})

    assert rect is not None
    assert (rect.x, rect.w) == (0.72, 0.28)


# ─── Fatia de gameplay ────────────────────────────────────────────────────────

def test_gameplay_slice_is_centered_without_facecam():
    assert gameplay_crop_x(1920, 980, None) == (1920 - 980) // 2


def test_gameplay_slice_stays_centered_when_facecam_is_in_a_corner():
    # Cam no canto direito (x 1500–1920): não encosta na fatia central
    centered = (1920 - 980) // 2
    assert gameplay_crop_x(1920, 980, (1500, 700, 420, 300)) == centered


def test_gameplay_slice_moves_away_from_a_centered_facecam():
    """Cam sobre o centro: a fatia desliza para não cortar a webcam no meio."""
    cam = (800, 600, 400, 300)  # 800–1200, bem no meio de um frame 1920

    x = gameplay_crop_x(1920, 700, cam)

    assert x + 700 <= cam[0] or x >= cam[0] + cam[2]
    assert 0 <= x <= 1920 - 700


def test_gameplay_slice_keeps_a_margin_from_the_facecam_box():
    """
    Regressão: a caixa detectada é recuada para DENTRO da cam, então a fatia
    encostada nela mostrava a moldura da facecam no painel de baixo — uma
    listra vertical no canto. A fatia tem que parar antes da caixa.
    """
    src_w, crop_w = 3840, 2388
    cam = (3040, 32, 724, 520)   # caixa real detectada numa live

    x = gameplay_crop_x(src_w, crop_w, cam)

    assert x + crop_w <= cam[0] - dodge_margin(src_w)


def test_dodge_margin_grows_with_source_resolution():
    """A folga vem do recuo em pixels de detecção, então escala com a fonte."""
    assert dodge_margin(3840) > dodge_margin(1920) > 0


def test_gameplay_slice_falls_back_to_center_when_it_cannot_dodge():
    """Fatia larga demais para caber de qualquer lado da cam: mantém o centro."""
    cam = (800, 600, 400, 300)

    x = gameplay_crop_x(1920, 1400, cam)

    assert x == (1920 - 1400) // 2


# ─── Fatia de gameplay ────────────────────────────────────────────────────────

@pytest.mark.parametrize("src", [(1920, 1080), (2560, 1440), (3840, 2160), (1280, 720)])
def test_gameplay_crop_matches_pane_aspect(src):
    """
    A fatia recortada tem a proporção do painel de baixo.

    Se não tiver, o `scale` compensa gravando SAR anamórfico no arquivo e o
    clipe deixa de preencher a tela 9:16 no player.
    """
    geo = StreamerGeometry(1080, 0.35, 0.029)

    w, h = _gameplay_crop_size(*src, geo.game_aspect, zoom=1.06)

    assert w / h == pytest.approx(geo.game_aspect, rel=0.005)
    assert (w % 2, h % 2) == (0, 0)
    assert w <= src[0] and h <= src[1]


def test_gameplay_crop_limits_by_width_on_narrow_source():
    """Fonte estreita demais para a fatia: fecha pela largura, sem deformar."""
    geo = StreamerGeometry(1080, 0.35, 0.029)

    w, h = _gameplay_crop_size(800, 1080, geo.game_aspect, zoom=1.0)

    assert w == 800
    assert w / h == pytest.approx(geo.game_aspect, rel=0.005)
