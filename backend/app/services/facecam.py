"""
Detecção da caixa da facecam em lives de streamer.

Numa live de jogo o layout é fixo: a webcam é um retângulo estático sobre o
gameplay, quase sempre encostado em um canto. Este módulo descobre onde esse
retângulo está, em coordenadas relativas (0–1) da fonte, para o clipper cortar
os dois painéis do mesmo vídeo.

Estratégia em duas etapas:

  1. Aglomerado de rostos — amostra frames ao longo do trecho e roda MediaPipe.
     O rosto do streamer fica sempre na MESMA região (a cam não se move), então
     a mediana das detecções é estável; detecções longe da mediana (rostos do
     jogo, thumbnails, plateia) são descartadas como outliers.

  2. Encaixe nas bordas — a caixa derivada do rosto é só um palpite grosseiro
     (sai do tamanho do rosto), e sobra de gameplay no painel é justamente o que
     estraga o clipe. As bordas reais da cam são LINHAS RETAS que atravessam a
     caixa inteira, então a busca varre o frame mediano a partir do rosto para
     fora e pontua cada coluna/linha pela fração da extensão com gradiente forte
     — não pela média do gradiente, que se perde em conteúdo ruidoso. A busca é
     do rosto até a borda do frame (não uma janela estreita em volta do palpite),
     porque o palpite erra fácil por 30%+.

     Em empate, vence a borda mais PRÓXIMA do rosto: cortar um filete da cam é
     invisível, deixar vazar gameplay é o defeito visível.

Sem rosto estável no trecho, retorna None — o clipper cai para um recorte
padrão no canto e o usuário pode corrigir manualmente pelo job.
"""

import glob
import logging
import math
import os
import subprocess
import tempfile
from dataclasses import dataclass, asdict
from typing import Optional

logger = logging.getLogger(__name__)

# Amostragem
_MAX_SAMPLES = 24          # frames analisados no trecho
_DETECT_WIDTH = 960        # largura de trabalho (detecção não precisa de 4K)

# Aglomeração
_STABLE_RADIUS = 0.12      # distância máx. do centro mediano para contar como a cam
_MIN_CONFIDENCE = 0.35     # fração mínima de frames com rosto estável

# Enquadramento derivado do rosto
_BOX_FROM_FACE = 2.6       # altura da caixa ≈ 2.6x a altura do rosto (cabeça + ombros)
_FACE_ABOVE_CENTER = 0.10  # rosto um pouco acima do centro da caixa
_DEFAULT_BOX_ASPECT = 16 / 9

# Encaixe nas bordas da cam
_LINE_STRONG = 0.8         # gradiente mínimo absoluto (0–255) para o pixel contar
_LINE_LOCAL_RATIO = 2.0    # ...ou o dobro do gradiente típico ALI, o que for maior

# Candidatas a borda: picos locais do gradiente médio
_PEAK_WINDOW = 0.05        # vizinhança da linha de base, em fração da dimensão
_PEAK_MIN_RATIO = 2.0      # pico precisa dobrar a vizinhança
_PEAK_MIN_GRAD = 1.0       # ...e ter gradiente médio mínimo (0–255)
_PEAK_MIN_MARGIN = 1.0     # ...e superar a vizinhança por esta margem absoluta.
                           # A margem é o que separa borda fraca de verdade
                           # (2.05 sobre 0.53 numa live real) de banding de
                           # quantização num fundo liso, que é um degrau de 1
                           # unidade atravessando a tela inteira — com limiar
                           # local, banding imita uma borda perfeita.
_PEAK_MIN_GAP = 0.01       # picos mais próximos que isso são o mesmo (fica o maior)
_CANDIDATES_PER_SIDE = 8
_EDGE_QUALITY = 0.45       # qualidade atribuída à borda do frame como candidata

# Prior de proporção: webcam de live é deitada, entre 4:3 e 16:9. É o que separa
# a borda certa de uma linha forte perdida no gameplay.
_CAM_ASPECTS = (4 / 3, 16 / 9)
_ASPECT_TOL = 0.30         # tolerância em log (~±35%). Largo de propósito: as
                           # cams reais medidas deram 1.36 e 1.47, entre 4:3 e
                           # 16:9. Um prior estreito vira desempate fino e passa
                           # a mandar mais que a qualidade das bordas.
_ASPECT_FLOOR = 0.15       # peso mínimo — proporção esquisita não zera a caixa
_SCORE_TIE = 0.05          # placares dentro de 5% empatam; desempata a menor caixa
_EDGE_REACH = 4.0          # sem linha e a até 4 alturas de rosto da borda = a cam encosta nela
_CAM_INSET = 0.01          # recuo para dentro da caixa, em fração do lado
_CAM_INSET_MIN = 3         # ...com piso em pixels da RESOLUÇÃO DE DETECÇÃO: cada
                           # pixel aqui vale 4 na fonte 4K, e a borda tem ±1 de
                           # incerteza. Perder 3px da cam é invisível depois da
                           # ampliação; deixar 3px de gameplay é uma listra.
_EDGE_SNAP = 0.05          # só no fallback sem encaixe: quase colada na borda, encosta


@dataclass
class FacecamRect:
    """Caixa da facecam em frações (0–1) da fonte — independente de resolução."""

    x: float
    y: float
    w: float
    h: float
    confidence: float = 0.0
    method: str = "faces"

    def to_pixels(self, src_w: int, src_h: int) -> tuple[int, int, int, int]:
        """
        Converte para pixels pares da fonte, garantindo a caixa dentro do frame.

        O arredondamento é sempre para DENTRO da caixa (origem para cima, borda
        oposta para baixo). Arredondar a origem para baixo, como antes, puxava
        até um pixel de gameplay para dentro do painel da cam — e o painel é
        ampliado ~2x, então esse pixel vira uma listra visível.
        """
        x = _clamp(_even_ceil(self.x * src_w), 0, max(0, src_w - 2))
        y = _clamp(_even_ceil(self.y * src_h), 0, max(0, src_h - 2))
        w = _clamp(_even_floor((self.x + self.w) * src_w) - x, 2, src_w - x)
        h = _clamp(_even_floor((self.y + self.h) * src_h) - y, 2, src_h - y)
        return x, y, w - w % 2, h - h % 2

    def as_dict(self) -> dict:
        return asdict(self)


def default_rect(box_aspect: float = _DEFAULT_BOX_ASPECT) -> FacecamRect:
    """
    Palpite quando não há detecção: canto inferior direito, posição mais comum
    de facecam. Serve para o render não falhar — o usuário ajusta depois.
    """
    w = 0.26
    h = min(0.9, w / box_aspect * (16 / 9))
    return FacecamRect(
        x=1.0 - w, y=1.0 - h, w=w, h=h, confidence=0.0, method="default_corner"
    )


def rect_from_dict(data: Optional[dict]) -> Optional[FacecamRect]:
    """Reconstrói a caixa a partir do JSON salvo no job (None se inválido)."""
    if not data:
        return None
    try:
        rect = FacecamRect(
            x=float(data["x"]),
            y=float(data["y"]),
            w=float(data["w"]),
            h=float(data["h"]),
            confidence=float(data.get("confidence", 1.0)),
            method=str(data.get("method", "manual")),
        )
    except (KeyError, TypeError, ValueError):
        logger.warning(f"Invalid facecam rect payload: {data!r}")
        return None
    if not (0 <= rect.x < 1 and 0 <= rect.y < 1 and 0 < rect.w <= 1 and 0 < rect.h <= 1):
        logger.warning(f"Facecam rect out of bounds: {rect}")
        return None
    return rect


def detect_facecam(
    video_path: str,
    start_time: float,
    end_time: float,
    box_aspect: float = _DEFAULT_BOX_ASPECT,
) -> Optional[FacecamRect]:
    """
    Localiza a caixa da facecam no trecho. Bloqueante — rodar via to_thread.

    Args:
        box_aspect: proporção largura/altura desejada da caixa (a do painel do
            clipe final), usada para completar a caixa a partir do rosto.

    Returns:
        FacecamRect em frações da fonte, ou None se não houver rosto estável.
    """
    import cv2
    import mediapipe as mp
    import numpy as np

    duration = max(end_time - start_time, 1.0)
    interval = max(duration / _MAX_SAMPLES, 0.5)

    with tempfile.TemporaryDirectory() as tmpdir:
        pattern = os.path.join(tmpdir, "f_%04d.jpg")
        subprocess.run(
            ["ffmpeg", "-y", "-ss", str(start_time), "-i", video_path,
             "-t", str(duration),
             "-vf", f"fps=1/{interval:.3f},scale={_DETECT_WIDTH}:-2",
             "-q:v", "3", pattern],
            capture_output=True, timeout=600,
        )
        frames = sorted(glob.glob(os.path.join(tmpdir, "f_*.jpg")))
        if not frames:
            logger.warning(f"Facecam: no frames extracted from {video_path}")
            return None

        detections: list[tuple[float, float, float, float]] = []
        with mp.solutions.face_detection.FaceDetection(
            model_selection=1, min_detection_confidence=0.5
        ) as detector:
            for path in frames:
                img = cv2.imread(path)
                if img is None:
                    continue
                res = detector.process(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
                if not res.detections:
                    continue
                best = max(res.detections, key=lambda d: d.score[0])
                b = best.location_data.relative_bounding_box
                detections.append((
                    b.xmin + b.width / 2, b.ymin + b.height / 2,
                    max(b.width, 1e-3), max(b.height, 1e-3),
                ))

        if not detections:
            logger.info("Facecam: no face detected in sampled frames")
            return None

        # A cam é estática: o aglomerado em torno da mediana é o rosto do streamer
        med_cx = _median([d[0] for d in detections])
        med_cy = _median([d[1] for d in detections])
        stable = [
            d for d in detections
            if math.dist((d[0], d[1]), (med_cx, med_cy)) <= _STABLE_RADIUS
        ]
        confidence = len(stable) / len(frames)
        if confidence < _MIN_CONFIDENCE:
            logger.info(
                f"Facecam: face cluster too unstable "
                f"({len(stable)}/{len(frames)} frames = {confidence:.0%})"
            )
            return None

        face_cx = _median([d[0] for d in stable])
        face_cy = _median([d[1] for d in stable])
        face_w = _median([d[2] for d in stable])
        face_h = _median([d[3] for d in stable])

        # Mapas de borda estática: o que fica igual em todo frame é a moldura da
        # cam, não o conteúdo dela nem o do jogo.
        maps = _edge_maps(frames, cv2, np)
        fitted = None
        if maps is not None:
            fitted = _fit_cam_rect(*maps, face_cx, face_cy, face_w, face_h, np)

        if fitted is not None:
            rect, method = fitted, "borders"
        else:
            # Sem bordas confiáveis: caixa aproximada a partir do rosto. Aqui o
            # encosto nas bordas do frame ainda ajuda (a cam quase sempre está
            # num canto); com encaixe real ele só estragaria a precisão.
            rect = _snap_to_frame_edges(_box_from_face(face_cx, face_cy, face_h, box_aspect))
            method = "faces"

    rect.confidence = confidence
    rect.method = method
    logger.info(
        f"Facecam detected ({method}, {confidence:.0%}): "
        f"x={rect.x:.3f} y={rect.y:.3f} w={rect.w:.3f} h={rect.h:.3f}"
    )
    return rect


def _box_from_face(
    face_cx: float, face_cy: float, face_h: float, box_aspect: float
) -> FacecamRect:
    """Expande o rosto para a caixa da cam (cabeça + ombros, rosto no terço superior)."""
    h = min(1.0, face_h * _BOX_FROM_FACE)
    w = min(1.0, h * box_aspect * (9 / 16))  # box_aspect é em pixels do frame 16:9
    cy = face_cy + _FACE_ABOVE_CENTER * h
    x = _clampf(face_cx - w / 2, 0.0, 1.0 - w)
    y = _clampf(cy - h / 2, 0.0, 1.0 - h)
    return FacecamRect(x=x, y=y, w=w, h=h)


def _edge_maps(frames: list[str], cv2, np):
    """
    Mapas de borda estática: média do gradiente de CADA frame — não o gradiente
    do frame mediano.

    A diferença decide o encaixe. A mediana temporal borra tudo que se move, e
    numa live isso inclui o conteúdo dos dois lados da borda da cam (o streamer
    de um lado, o jogo do outro), então a borda chega fraca ao gradiente. Uma
    borda estática, ao contrário, aparece no MESMO pixel em todo frame: a média
    dos gradientes a mantém cheia, enquanto as bordas do conteúdo em movimento
    caem em lugares diferentes e se diluem.

    Medido numa live real (24 frames, 38s de jogo): a borda esquerda da cam
    pontuou 0.97 com a média dos gradientes contra 0.54 com o gradiente da
    mediana — de reprovada a inequívoca.

    Returns:
        (gx, gy) — gx[:, c] é o degrau entre as colunas c e c+1; gy idem para
        linhas. None se não houver frames suficientes.
    """
    gx_sum = gy_sum = None
    shape = None
    count = 0

    for path in frames[:_MAX_SAMPLES]:
        img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        if img is None:
            continue
        if shape is None:
            shape = img.shape
            gx_sum = np.zeros((shape[0], shape[1] - 1), "float32")
            gy_sum = np.zeros((shape[0] - 1, shape[1]), "float32")
        elif img.shape != shape:
            continue
        f = img.astype("float32")
        gx_sum += np.abs(np.diff(f, axis=1))
        gy_sum += np.abs(np.diff(f, axis=0))
        count += 1

    if count < 3:
        return None
    return gx_sum / count, gy_sum / count


def _line_scores(band, axis: int, np):
    """
    Placar de "linha reta" para cada posição da faixa.

    Para cada coluna (ou linha), a fração dos pixels da faixa em que o gradiente
    é forte. Uma borda de cam pontua perto de 1.0 porque o degrau atravessa a
    caixa inteira; textura pontua baixo mesmo tendo gradiente alto em alguns
    pontos — é a diferença entre "linha" e "ruído forte".

    O corte de "forte" é LOCAL: o dobro do gradiente típico naquela vizinhança.
    Um corte global (percentil da faixa inteira) é dominado pelo trecho mais
    contrastado da tela e fica cego para borda em região escura — medido numa
    live real, a borda de baixo da cam (preto contra preto, com o HUD do jogo
    30x mais forte na mesma tela) marcava suporte 0.00 com corte global e 0.81
    com corte local, que é a diferença entre achar e não achar a cam.
    """
    if band.size == 0:
        return None

    profile = band.mean(axis=axis)
    baseline = _local_baseline(profile, int(_PEAK_WINDOW * len(profile)), np)
    threshold = np.maximum(_LINE_STRONG, _LINE_LOCAL_RATIO * baseline)
    # axis=1 mede por linha (limiar varia na vertical); axis=0, por coluna
    strong = band > (threshold[:, None] if axis == 1 else threshold[None, :])
    return strong.mean(axis=axis)


def _line_profile(band, axis: int, np):
    """Gradiente médio por posição ao longo da faixa."""
    return None if band.size == 0 else band.mean(axis=axis)


def _best_box(lefts, rights, tops, bottoms) -> Optional[tuple]:
    """
    Melhor combinação de bordas entre as candidatas de cada lado.

    Decidir lado a lado não funciona: cada borda isolada escolhe a linha mais
    forte perto dela, e uma linha forte do gameplay ganha de uma borda fraca da
    cam. Avaliando a CAIXA inteira, a proporção entra na conta e desempata —
    quatro bordas que formam um retângulo de webcam valem mais que quatro linhas
    fortes que formam um retângulo impossível.

    Empate técnico fica com a MENOR caixa. O erro não é simétrico: apertar o
    corte come uma tira da cam que ninguém nota depois da ampliação, enquanto
    alargar traz gameplay para dentro do painel, que é o defeito visível. Sem
    esse desempate a escolha entre duas caixas quase idênticas vira sorteio.

    Returns:
        (x0, y0, x1, y1, score) em pixels, x1/y1 exclusivos. None se nenhuma
        combinação fecha uma caixa.
    """
    boxes = []
    for left, q_left in lefts:
        for right, q_right in rights:
            width = right - left
            if width < 16:
                continue
            for top, q_top in tops:
                for bottom, q_bottom in bottoms:
                    height = bottom - top
                    if height < 16:
                        continue
                    sides = (q_left, q_right, q_top, q_bottom)
                    # Média mais um peso para a PIOR borda: uma caixa com três
                    # bordas ótimas e uma duvidosa quase sempre é uma borda real
                    # trocada por uma linha do gameplay.
                    quality = 0.6 * sum(sides) / 4 + 0.4 * min(sides)
                    score = _aspect_weight(width, height) * quality
                    boxes.append((score, width * height, left + 1, top + 1, right + 1, bottom + 1))

    if not boxes:
        return None

    best_score = max(box[0] for box in boxes)
    tied = [box for box in boxes if box[0] >= best_score * (1 - _SCORE_TIE)]
    chosen = min(tied, key=lambda box: box[1])
    return (*chosen[2:], chosen[0])


def _local_baseline(profile, window: int, np):
    """Mediana móvel do perfil — o nível de gradiente "normal" em volta de cada
    posição, para medir o quanto um pico se destaca do que tem em volta."""
    window = max(3, window | 1)  # ímpar
    pad = window // 2
    padded = np.pad(profile, pad, mode="edge")
    return np.median(np.lib.stride_tricks.sliding_window_view(padded, window), axis=-1)


def _border_candidates(profile, support, lo: int, hi: int, np) -> list[tuple[int, float]]:
    """
    Posições entre lo e hi que podem ser uma borda da cam: picos locais do
    gradiente médio que se destacam da vizinhança.

    Só o suporte (fração da faixa com gradiente forte) não basta. Numa cena
    escura a borda da cam encosta no preto e some do suporte: medido numa live
    real, a borda de baixo tinha gradiente médio 2.0 e suporte 0.00, contra 56
    do HUD do jogo. Como PICO LOCAL ela continua nítida — 2.8x a vizinhança — e
    é assim que ela entra na disputa.

    A supressão de não-máximos evita que uma borda grossa ocupe todas as vagas
    com suas próprias linhas vizinhas.

    Returns:
        [(posição, qualidade)] — qualidade é o suporte, 0 numa borda fraca; a
        escolha final entre as candidatas é de _fit_cam_rect.
    """
    if profile is None or hi - lo < 3:
        return []

    baseline = _local_baseline(profile, int(_PEAK_WINDOW * len(profile)), np)
    peaks: list[tuple[int, float, float]] = []
    for i in range(max(lo, 1), min(hi, len(profile) - 1)):
        value = float(profile[i])
        if value < _PEAK_MIN_GRAD or value < profile[i - 1] or value < profile[i + 1]:
            continue
        base = max(float(baseline[i]), 0.2)
        if value - base >= _PEAK_MIN_MARGIN and value / base >= _PEAK_MIN_RATIO:
            peaks.append((i, value / base, float(support[i])))

    peaks.sort(key=lambda p: p[1], reverse=True)
    gap = max(3, int(_PEAK_MIN_GAP * len(profile)))
    chosen: list[tuple[int, float, float]] = []
    for peak in peaks:
        if all(abs(peak[0] - other[0]) >= gap for other in chosen):
            chosen.append(peak)
        if len(chosen) == _CANDIDATES_PER_SIDE:
            break

    return [(i, support_value) for i, _, support_value in chosen]


def _aspect_weight(width: int, height: int) -> float:
    """
    O quanto a caixa parece uma webcam. Webcam de live é deitada (4:3 a 16:9);
    uma caixa que vai do topo da tela até o HUD do jogo lá embaixo não é.
    """
    if width <= 0 or height <= 0:
        return 0.0
    aspect = width / height
    best = max(
        math.exp(-(math.log(aspect / target) ** 2) / (2 * _ASPECT_TOL ** 2))
        for target in _CAM_ASPECTS
    )
    return max(_ASPECT_FLOOR, best)


def _fit_cam_rect(
    gx, gy, face_cx: float, face_cy: float, face_w: float, face_h: float, np
) -> Optional[FacecamRect]:
    """
    Encontra as quatro bordas da cam nos mapas de borda, partindo do rosto.

    Cada borda é procurada FORA da caixa do rosto — nenhuma borda da cam corta a
    cara do streamer — e a escolha é feita pela CAIXA inteira, não lado a lado
    (ver _best_box). Duas passadas: a caixa da primeira vira a faixa em que a
    segunda mede, para cada borda ser pontuada ao longo da cam real e não de um
    palpite. A borda do frame entra como candidata quando o rosto está perto
    dela (cam encostada num canto).

    Returns:
        Caixa em frações da fonte, ou None se as bordas não fecharem uma caixa.
    """
    h, w = gx.shape[0], gx.shape[1] + 1

    fx, fy = int(face_cx * w), int(face_cy * h)
    face_px = max(face_h * h, 8.0)
    reach = _EDGE_REACH * face_px

    # Limites do rosto: a busca de cada borda começa daqui para fora
    face_l = _clamp(int((face_cx - face_w / 2) * w), 0, w - 1)
    face_r = _clamp(int((face_cx + face_w / 2) * w), 0, w - 1)
    face_t = _clamp(int((face_cy - face_h / 2) * h), 0, h - 1)
    face_b = _clamp(int((face_cy + face_h / 2) * h), 0, h - 1)

    # Faixa inicial: em volta do rosto — a cam certamente o contém
    y0, y1 = _clamp(int(fy - face_px), 0, h - 1), _clamp(int(fy + face_px), 1, h)
    x0, x1 = _clamp(int(fx - face_px), 0, w - 1), _clamp(int(fx + face_px), 1, w)

    box = None
    for _ in range(2):
        col_band, row_band = gx[y0:y1, :], gy[:, x0:x1]
        col_profile, row_profile = _line_profile(col_band, 0, np), _line_profile(row_band, 1, np)
        col_support, row_support = _line_scores(col_band, 0, np), _line_scores(row_band, 1, np)
        if col_profile is None or row_profile is None:
            break

        lefts = _border_candidates(col_profile, col_support, 0, face_l, np)
        rights = _border_candidates(col_profile, col_support, face_r, w - 1, np)
        tops = _border_candidates(row_profile, row_support, 0, face_t, np)
        bottoms = _border_candidates(row_profile, row_support, face_b, h - 1, np)

        # Índice -1 = "antes da primeira coluna/linha", ou seja, a borda do frame
        if fx <= reach:
            lefts.append((-1, _EDGE_QUALITY))
        if (w - fx) <= reach:
            rights.append((w - 1, _EDGE_QUALITY))
        if fy <= reach:
            tops.append((-1, _EDGE_QUALITY))
        if (h - fy) <= reach:
            bottoms.append((h - 1, _EDGE_QUALITY))

        found = _best_box(lefts, rights, tops, bottoms)
        if found is None:
            break

        box = found
        x0, y0, x1, y1 = box[0], box[1], box[2], box[3]

    if box is None:
        return None
    x0, y0, x1, y1 = box[0], box[1], box[2], box[3]

    # Recuo para dentro: a própria moldura da cam (bezel, sombra) fica de fora
    inset_x = max(_CAM_INSET_MIN, int(_CAM_INSET * (x1 - x0)))
    inset_y = max(_CAM_INSET_MIN, int(_CAM_INSET * (y1 - y0)))
    x0, x1 = x0 + inset_x, x1 - inset_x
    y0, y1 = y0 + inset_y, y1 - inset_y
    if x1 - x0 < 16 or y1 - y0 < 16:
        return None

    return FacecamRect(x=x0 / w, y=y0 / h, w=(x1 - x0) / w, h=(y1 - y0) / h)


def _snap_to_frame_edges(rect: FacecamRect) -> FacecamRect:
    """Facecam quase encostada na borda do frame encosta de vez (elimina a
    tirinha de gameplay que sobra na lateral do painel)."""
    if rect.x < _EDGE_SNAP:
        rect.w += rect.x
        rect.x = 0.0
    if rect.y < _EDGE_SNAP:
        rect.h += rect.y
        rect.y = 0.0
    if 1.0 - (rect.x + rect.w) < _EDGE_SNAP:
        rect.w = 1.0 - rect.x
    if 1.0 - (rect.y + rect.h) < _EDGE_SNAP:
        rect.h = 1.0 - rect.y
    return rect


def dodge_margin(src_w: int) -> int:
    """
    Folga que a fatia de gameplay mantém da caixa da facecam.

    A caixa detectada é recuada para DENTRO da cam (_CAM_INSET_MIN, em pixels da
    resolução de detecção), então a moldura real da cam fica um pouco fora do
    que a caixa diz. Encostar a fatia na caixa mostra exatamente essa moldura no
    painel de baixo — a folga converte o recuo de volta para pixels da fonte e
    ainda sobra um pouco.
    """
    inset_in_source = _CAM_INSET_MIN * src_w / _DETECT_WIDTH
    return int(math.ceil(inset_in_source * 1.5)) + 4


def gameplay_crop_x(src_w: int, crop_w: int, cam_px: Optional[tuple]) -> int:
    """
    x da fatia de gameplay: centralizada, mas desviando da facecam quando ela
    invade o centro (dá para deslizar até a fatia sair de cima da cam sem
    ultrapassar os limites do frame).

    O desvio é da caixa da cam MAIS a folga de dodge_margin().
    """
    centered = (src_w - crop_w) // 2
    if not cam_px:
        return _clamp(centered, 0, src_w - crop_w)

    margin = dodge_margin(src_w)
    box_x, _, box_w, _ = cam_px
    cam_x = max(0, box_x - margin)
    cam_x1 = min(src_w, box_x + box_w + margin)
    if cam_x1 <= centered or cam_x >= centered + crop_w:
        return _clamp(centered, 0, src_w - crop_w)  # sem sobreposição

    # Tenta os dois lados; fica com o menor deslocamento que couber no frame
    options = []
    if cam_x1 + crop_w <= src_w:
        options.append(cam_x1)                       # à direita da cam
    if cam_x - crop_w >= 0:
        options.append(cam_x - crop_w)               # à esquerda da cam
    if not options:
        return _clamp(centered, 0, src_w - crop_w)   # não cabe: mantém o centro
    return _clamp(min(options, key=lambda x: abs(x - centered)), 0, src_w - crop_w)


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    return ordered[mid] if n % 2 else (ordered[mid - 1] + ordered[mid]) / 2


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(v, hi))


def _even_ceil(v: float) -> int:
    """Menor inteiro par ≥ v (a tolerância absorve o erro de ponto flutuante)."""
    i = math.ceil(v - 1e-6)
    return i + (i % 2)


def _even_floor(v: float) -> int:
    """Maior inteiro par ≤ v."""
    i = math.floor(v + 1e-6)
    return i - (i % 2)


def _clampf(v: float, lo: float, hi: float) -> float:
    return max(lo, min(v, hi))
