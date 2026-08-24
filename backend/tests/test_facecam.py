"""
Testes da geometria do modo streamer (facecam + gameplay).

Cobrem só as partes determinísticas — o que depende de MediaPipe/OpenCV
(detecção em si) não entra aqui.
"""

import numpy as np
import pytest

from app.services.facecam import (
    _absorb_floating_boxes,
    _absorb_size_outliers,
    _best_box,
    _merge_equivalent_phases,
    CamPhase,
    FacecamRect,
    _Obs,
    _TILE_SPAN,
    _cam_track,
    _dedupe,
    _edge_gap,
    _tiles,
    _group_spans,
    _box_from_face,
    _fit_cam_rect,
    default_rect,
    dodge_margin,
    gameplay_crop_x,
    rect_from_dict,
)
from app.services.clipper import _cam_phases, _gameplay_crop_size
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


# ─── Quem é a facecam (persistência vs. rostos concorrentes) ──────────────────

def _obs(cx, cy, size=0.1, score=0.9):
    return _Obs(cx=cx, cy=cy, w=size, h=size * 1.4, score=score)


def test_sub_popup_does_not_steal_the_cam():
    """
    O alerta de inscrito entra por alguns segundos com um rosto maior e mais
    confiante que o do streamer. Quem vence é a presença, não a confiança.
    """
    per_frame = []
    for i in range(24):
        frame = [_obs(0.85, 0.15)]
        if 8 <= i <= 13:
            frame.append(_obs(0.35, 0.55, size=0.18, score=0.99))
        per_frame.append(frame)

    track, confidence, _ = _cam_track(per_frame, 24)

    assert {round(o.cx, 2) for o in track if o} == {0.85}
    assert confidence == pytest.approx(1.0)


def test_cam_that_changes_corner_keeps_both_positions():
    """Duas posições em janelas de tempo distintas são a mesma cam se movendo."""
    per_frame = [[_obs(0.85, 0.15)] for _ in range(12)]
    per_frame += [[_obs(0.12, 0.15)] for _ in range(12)]

    track, _, _ = _cam_track(per_frame, 24)

    assert {round(o.cx, 2) for o in track if o} == {0.85, 0.12}


def test_no_persistent_face_gives_up():
    """Só o popup e mais nada: sem cam, o chamador cai no palpite de canto."""
    per_frame = [[] for _ in range(24)]
    for i in range(8, 13):
        per_frame[i] = [_obs(0.35, 0.55, size=0.18, score=0.99)]

    track, confidence, _ = _cam_track(per_frame, 24)

    assert track is None and confidence == 0.0


# ─── Fases (a cam muda de lugar ou dá zoom no meio do clip) ───────────────────

def _spans(track):
    """
    Trechos por cam, no formato (i0, i1) para comparação.

    Passa pelo _cam_track de propósito: é ele que decide quais aglomerados são
    cam de verdade, e os trechos herdam essa identidade.
    """
    per_frame = [[obs] if obs is not None else [] for obs in track]
    real_track, _, groups = _cam_track(per_frame, len(track))
    return [(a, b) for a, b, _ in _group_spans(real_track, groups)]


def test_cam_parada_e_uma_fase_so():
    assert _spans([_obs(0.8, 0.2) for _ in range(10)]) == [(0, 9)]


def test_cam_que_muda_de_canto_vira_duas_fases():
    track = [_obs(0.8, 0.2) for _ in range(6)] + [_obs(0.1, 0.2) for _ in range(6)]
    assert _spans(track) == [(0, 5), (6, 11)]


def test_frame_sem_rosto_nao_quebra_a_fase():
    """A cam continua lá; quem piscou foi o detector."""
    track = [_obs(0.8, 0.2), None, _obs(0.8, 0.2), None, _obs(0.8, 0.2), _obs(0.8, 0.2)]
    track += [_obs(0.1, 0.2) for _ in range(6)]
    assert _spans(track) == [(0, 5), (6, 11)]


def test_streamer_se_mexendo_na_cadeira_nao_abre_fase():
    """
    Deslocamento pequeno é o streamer se mexendo, não a cam mudando de lugar:
    fica no mesmo grupo e o enquadramento não troca.
    """
    track = [_obs(0.80, 0.2) for _ in range(5)] + [_obs(0.83, 0.2)] + [_obs(0.80, 0.2) for _ in range(5)]
    assert _spans(track) == [(0, 10)]


def test_plano_curto_mas_recorrente_troca_o_enquadramento():
    """
    O caso do vídeo editado: cada aparição do outro POV dura 1-2 amostras, mas
    ela se repete. A troca vale já na primeira amostra — exigir confirmação era
    o que mantinha o defeito, porque com plano de ~4s e amostra a cada 1,7s a
    contagem nunca fechava e o trecho inteiro herdava o enquadramento do outro
    streamer.
    """
    track = ([_obs(0.80, 0.2)] * 4 + [_obs(0.10, 0.2)]) * 3

    assert _spans(track) == [(0, 3), (4, 4), (5, 8), (9, 9), (10, 13), (14, 14)]


def test_deteccao_isolada_e_ruido_e_nao_troca_nada():
    """
    Um rosto que aparece uma vez só não é cam: pode ser personagem do jogo,
    plateia, um popup. O filtro de persistência derruba antes de virar fase.
    """
    track = [_obs(0.80, 0.2) for _ in range(5)] + [_obs(0.10, 0.2)] + [_obs(0.80, 0.2) for _ in range(5)]

    assert _spans(track) == [(0, 10)]


def test_cam_que_volta_para_o_canto_anterior_reusa_o_grupo():
    """
    O caso do vídeo editado: a edição alterna entre POVs e volta. As idas e
    vindas ao MESMO canto têm que cair no mesmo grupo, senão cada plano é
    encaixado sozinho com 2 amostras e o mapa de bordas não fecha caixa.
    """
    track = ([_obs(0.05, 0.2)] * 3 + [_obs(0.85, 0.2)] * 3) * 3
    per_frame = [[o] for o in track]
    real_track, _, groups = _cam_track(per_frame, len(track))

    assert len(groups) == 2, "as idas e vindas ao mesmo canto viraram grupos demais"
    assert sorted(len(v) for v in groups.values()) == [9, 9]
    assert len(_group_spans(real_track, groups)) == 6   # seis trechos, duas caixas


def test_spans_cobrem_todos_os_frames_sem_buraco():
    track = ([_obs(0.05, 0.2)] * 3 + [_obs(0.85, 0.2)] * 3) * 3
    spans = _spans(track)

    assert spans[0][0] == 0 and spans[-1][1] == len(track) - 1
    assert all(a[1] + 1 == b[0] for a, b in zip(spans, spans[1:]))


# ─── Fatia de gameplay com a cam em vários lugares ────────────────────────────

def test_gameplay_slice_dodges_every_phase_box():
    """Cam nos dois cantos: a fatia tem que escapar das duas, não da união."""
    cams = [(60, 700, 520, 340), (1520, 40, 360, 260)]

    x = gameplay_crop_x(1920, 700, cams)

    for bx, _, bw, _ in cams:
        assert x >= bx + bw or x + 700 <= bx


def test_gameplay_slice_centers_when_no_position_clears_all_boxes():
    """Vão livre entre as caixas menor que a fatia: não há desvio possível."""
    cams = [(0, 0, 900, 500), (1020, 0, 900, 500)]  # sobram 120px entre elas

    assert gameplay_crop_x(1920, 920, cams) == (1920 - 920) // 2


# ─── Linha do tempo entregue ao filtergraph ───────────────────────────────────

def test_single_rect_becomes_one_phase_covering_the_clip():
    """Caixa manual (ou cam parada) vale o clip inteiro."""
    rect = FacecamRect(x=0.8, y=0.0, w=0.2, h=0.3)

    phases = _cam_phases(rect, duration=30.0)

    assert len(phases) == 1
    assert (phases[0].start, phases[0].end) == (0.0, 30.0)


def test_phases_are_clamped_to_the_clip_window():
    """
    A 1ª fase começa em 0 e a última vai até o fim: o `enable` do overlay
    compara com o relógio do filtergraph, que começa zerado pelo -ss.
    """
    rect = FacecamRect(x=0.8, y=0.0, w=0.2, h=0.3)
    phases = _cam_phases(
        [CamPhase(6.0, 12.0, rect), CamPhase(0.5, 6.0, rect), CamPhase(99.0, 120.0, rect)],
        duration=10.0,
    )

    assert [(p.start, p.end) for p in phases] == [(0.0, 6.0), (6.0, 10.0)]


# ─── Varredura por ladrilhos (facecam pequena) ────────────────────────────────

def test_tiles_cover_the_whole_frame_with_overlap():
    """
    Um rosto na divisa entre ladrilhos não pode escapar dos dois — por isso a
    varredura é sobreposta, e não um mosaico justo.
    """
    tiles = _tiles()
    span = _TILE_SPAN

    assert min(x for x, _ in tiles) == 0.0 and min(y for _, y in tiles) == 0.0
    assert max(x for x, _ in tiles) + span == pytest.approx(1.0)
    assert max(y for _, y in tiles) + span == pytest.approx(1.0)
    assert span > 0.5  # ladrilhos vizinhos se sobrepõem


def test_same_face_seen_by_frame_and_tile_counts_once():
    """O rosto achado no frame inteiro e no ladrilho é uma detecção só."""
    found = [
        _Obs(cx=0.15, cy=0.20, w=0.05, h=0.07, score=0.60),
        _Obs(cx=0.151, cy=0.201, w=0.05, h=0.07, score=0.88),  # o mesmo, do ladrilho
        _Obs(cx=0.80, cy=0.60, w=0.05, h=0.07, score=0.70),    # outro rosto
    ]

    unique = _dedupe(found)

    assert len(unique) == 2
    assert max(o.score for o in unique if o.cx < 0.5) == 0.88  # fica a melhor


# ─── Teto de tamanho da cam ───────────────────────────────────────────────────

def test_fit_cam_rect_rejects_a_frame_sized_box():
    """
    A moldura do cenário não pode virar "facecam".

    Caso real (job Photomaly, agosto/2026): o encaixe devolveu caixas de até
    94% da largura por 87% da altura, e o painel do clipe mostrou o gameplay
    inteiro no lugar do rosto. O prior de proporção não protege sozinho — uma
    caixa colada nas bordas do frame tem a proporção DO FRAME e tira nota
    máxima —, então o tamanho precisa ser restrição dura.
    """
    # Cam pequena no canto + um retângulo gigante de alto contraste (a "sala")
    frame = _fake_frame((10, 10, 90, 60))
    frame[6:250, 6:460] = np.clip(
        frame[6:250, 6:460].astype("float32") - 45, 0, 255
    ).astype("uint8")
    frame[10:70, 10:100] = 200  # a cam continua sendo o bloco claro
    gx, gy = _maps(frame)

    rect = _fit_cam_rect(gx, gy, 55 / 480, 40 / 270, 20 / 480, 26 / 270, np)

    assert rect is not None
    assert rect.w * rect.h <= 0.30, f"caixa de {rect.w * rect.h:.2f} de área não é uma cam"
    assert rect.w <= 0.55 and rect.h <= 0.60


def test_best_box_discards_oversized_candidates():
    """O teto entra antes da pontuação: sobra a melhor caixa plausível."""
    # Bordas do frame (caixa enorme) com qualidade máxima, cam real com
    # qualidade menor — sem teto, a enorme ganharia.
    lefts = [(-1, 1.0), (100, 0.5)]
    rights = [(479, 1.0), (200, 0.5)]
    tops = [(-1, 1.0), (60, 0.5)]
    bottoms = [(269, 1.0), (130, 0.5)]

    box = _best_box(lefts, rights, tops, bottoms, 480, 270)

    assert box is not None
    x0, y0, x1, y1 = box[0], box[1], box[2], box[3]
    assert (x1 - x0) <= 0.55 * 480
    assert (y1 - y0) <= 0.60 * 270


def test_best_box_returns_none_when_everything_is_oversized():
    """Sem candidata plausível, o encaixe desiste e o chamador cai no rosto."""
    box = _best_box([(-1, 1.0)], [(479, 1.0)], [(-1, 1.0)], [(269, 1.0)], 480, 270)

    assert box is None


# ─── Fases equivalentes ───────────────────────────────────────────────────────

def _phase(start, end, x, y, w, h):
    return CamPhase(start=start, end=end, rect=FacecamRect(x=x, y=y, w=w, h=h))


def test_merges_phases_that_describe_the_same_cam():
    """
    Cam parada não pode trocar de recorte no meio do clipe.

    Duas fases quase idênticas vêm do rosto oscilando, não da cam se movendo —
    e cada troca aparece como um pulinho de zoom no vídeo final.
    """
    phases = [
        _phase(0.0, 4.0, 0.790, 0.013, 0.189, 0.244),
        _phase(4.0, 31.6, 0.791, 0.013, 0.203, 0.244),
    ]

    merged = _merge_equivalent_phases(phases)

    assert len(merged) == 1
    assert merged[0].start == 0.0 and merged[0].end == 31.6
    # Fica a caixa da fase mais longa, que teve mais frames para encaixar
    assert merged[0].rect.w == 0.203


def test_keeps_phases_when_the_cam_actually_moves():
    """Cam que muda de canto continua sendo duas fases."""
    phases = [
        _phase(0.0, 10.0, 0.79, 0.01, 0.20, 0.24),
        _phase(10.0, 20.0, 0.02, 0.70, 0.20, 0.24),
    ]

    assert len(_merge_equivalent_phases(phases)) == 2


def test_keeps_phases_when_the_cam_changes_size():
    """Zoom na cam é mudança real de enquadramento — não pode ser absorvido."""
    phases = [
        _phase(0.0, 10.0, 0.75, 0.01, 0.20, 0.24),
        _phase(10.0, 20.0, 0.70, 0.01, 0.30, 0.36),
    ]

    assert len(_merge_equivalent_phases(phases)) == 2


def test_merge_is_a_noop_for_a_single_phase():
    phases = [_phase(0.0, 30.0, 0.79, 0.01, 0.20, 0.24)]

    assert _merge_equivalent_phases(phases) == phases


# ─── Coerência de tamanho dentro do job ───────────────────────────────────────

def _ref(w=0.193, h=0.253):
    return FacecamRect(x=0.804, y=0.006, w=w, h=h, confidence=1.0, method="borders")


def test_absorve_moldura_da_ui_do_jogo():
    """A fase fora de escala herda a caixa da vizinha boa mais próxima."""
    phases = [
        _phase(0.0, 11.6, 0.096, 0.087, 0.119, 0.122),
        _phase(11.6, 18.5, 0.221, 0.088, 0.463, 0.444),   # o card do jogo
        _phase(18.5, 43.9, 0.003, 0.003, 0.170, 0.220),   # a cam de verdade
        _phase(43.9, 55.5, 0.010, 0.003, 0.204, 0.206),
    ]
    out = _absorb_size_outliers(phases)

    assert all(p.rect.w < 0.3 for p in out), "sobrou caixa do tamanho do card"
    assert len(out) < 4, "as fases iguais deveriam ter sido fundidas"


def test_cam_que_troca_de_canto_passa_intacta():
    """Mudança de posição com tamanho igual é layout real, não erro."""
    phases = [
        _phase(0.0, 20.0, 0.02, 0.02, 0.20, 0.25),
        _phase(20.0, 40.0, 0.78, 0.02, 0.20, 0.25),
    ]
    out = _absorb_size_outliers(phases)

    assert len(out) == 2
    assert out[1].rect.x == 0.78
    assert all(p.rect.method != "phase_fix" for p in out), "trocou caixa boa"


def test_uma_fase_so_nao_tem_com_o_que_comparar():
    phases = [_phase(0.0, 30.0, 0.2, 0.1, 0.46, 0.44)]
    assert _absorb_size_outliers(phases) == phases


def test_todas_fora_de_escala_ficam_como_estao():
    """Sem maioria boa não há referência confiável: melhor não mexer."""
    phases = [
        _phase(0.0, 10.0, 0.1, 0.1, 0.46, 0.44),
        _phase(10.0, 20.0, 0.1, 0.1, 0.45, 0.43),
    ]
    out = _absorb_size_outliers(phases)
    assert all(p.rect.w > 0.4 for p in out)


# ─── Ancoragem na borda do frame ──────────────────────────────────────────────

def test_absorve_rosto_do_jogo_solto_no_meio_do_frame():
    """
    O caso do clipe e7fc97eb: os generais da cutscene de "Senhor presidente"
    persistem tanto quanto o streamer e passam por "a cam se moveu para cá".
    A caixa deles flutua no meio da tela — a da cam encosta no canto.
    """
    phases = [
        _phase(0.0, 11.0, 0.006, 0.003, 0.247, 0.250),    # a cam de verdade
        _phase(11.0, 13.2, 0.528, 0.173, 0.303, 0.283),   # os generais
        _phase(13.2, 81.6, 0.006, 0.003, 0.247, 0.250),
        _phase(81.6, 97.1, 0.528, 0.173, 0.303, 0.283),
        _phase(97.1, 105.9, 0.006, 0.003, 0.247, 0.250),
    ]
    out = _absorb_floating_boxes(phases)

    assert len(out) == 1, "sem caixa solta o clipe inteiro é uma fase só"
    assert out[0].rect.x == 0.006 and out[0].rect.y == 0.003
    assert (out[0].start, out[0].end) == (0.0, 105.9)


def test_cam_em_outro_canto_passa_intacta():
    """Troca de POV em vídeo editado: cada cam num canto, todas ancoradas."""
    phases = [
        _phase(0.0, 20.0, 0.01, 0.01, 0.20, 0.25),
        _phase(20.0, 40.0, 0.79, 0.74, 0.20, 0.25),
    ]
    out = _absorb_floating_boxes(phases)

    assert len(out) == 2
    assert out[1].rect.x == 0.79
    assert all(p.rect.method != "phase_fix" for p in out), "derrubou cam boa"


def test_cam_dominante_solta_no_meio_nao_e_derrubada():
    """
    Layout esquisito, com a cam de verdade longe das bordas: a regra só sabe
    derrubar deslocamento suspeito, nunca o enquadramento que domina o trecho.
    """
    phases = [
        _phase(0.0, 40.0, 0.40, 0.30, 0.20, 0.25),
        _phase(40.0, 50.0, 0.45, 0.35, 0.20, 0.25),
    ]
    out = _absorb_floating_boxes(phases)

    assert len(out) == 2
    assert all(p.rect.method != "phase_fix" for p in out)


def test_uma_fase_so_nao_e_avaliada():
    phases = [_phase(0.0, 30.0, 0.40, 0.30, 0.20, 0.25)]
    assert _absorb_floating_boxes(phases) == phases


def test_folga_medida_e_a_da_borda_mais_proxima():
    """Encostar num canto basta — o lado oposto fica longe por construção."""
    assert _edge_gap(FacecamRect(x=0.006, y=0.003, w=0.247, h=0.250)) == pytest.approx(0.003)
    assert _edge_gap(FacecamRect(x=0.528, y=0.173, w=0.303, h=0.283)) == pytest.approx(0.169)
