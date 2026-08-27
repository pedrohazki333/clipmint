"""
Marca d'água do usuário + neutralização de QR codes / marcas de terceiros.

- A logo do usuário fica em storage/branding/watermark.png (upload via API).
- QR codes são detectados no vídeo FONTE (coordenadas originais, antes do
  crop): amostramos frames do trecho, rodamos o detector do OpenCV e
  agrupamos as detecções em regiões estáveis. O clipper neutraliza cada
  região com delogo (borrão) e sobrepõe a logo do usuário por cima — como
  isso acontece antes do crop, a cobertura acompanha o face tracking.
"""

import glob
import logging
import math
import os
import subprocess
import tempfile
from typing import Optional

from app.config import settings
from app.services.branding import CLIP_WATERMARK_FILE, WATERMARK_FILE, preset_path

logger = logging.getLogger(__name__)

_QR_SAMPLES = 12          # frames amostrados por trecho
_MIN_HITS = 2             # detecções mínimas para considerar a região estável
_CLUSTER_DIST = 0.06      # distância máx. entre centros (fração da diagonal)
_PAD = 0.10               # folga ao redor da região detectada
_MIN_AREA = 0.0005        # ignora detecções minúsculas (ruído)
_MAX_AREA = 0.20          # ignora detecções gigantes (falso positivo)

# Detecção de marcas estáticas (logos de canal sobrepostas)
_EDGE_PERSISTENCE = 0.70  # fração dos frames DA CENA em que a borda persiste
_STATIC_BAND = 0.35       # marcas de canal ficam nas faixas superior/inferior
_STATIC_MIN_AREA = 0.0004
_STATIC_MAX_AREA = 0.15
_SCENE_CUT_DIFF = 22      # diff médio de luminância entre amostras = corte de cena
_MIN_SCENES = 2           # a marca precisa persistir em TODAS as cenas; com uma
                          # cena só, o cenário inteiro também persistiria →
                          # detecção não é confiável e fica desligada
# Nos cortes de cena, os traços internos de um overlay queimado ficam
# pixel-idênticos enquanto o fundo muda com a câmera. Medido no PODPAH TV:
# overlay real ~0.5 dos pixels de borda estáveis; cenário ~0.15.
_OVERLAY_STABLE_FRAC = 0.35   # fração mínima de pixels estáveis nos cortes
_OVERLAY_STABLE_DIFF = 12     # |diff| máximo para um pixel contar como estável


def user_watermark_path(source_type: Optional[str] = None, profile_id: str | None = None) -> Optional[str]:
    """Caminho da logo do nicho, ou None se não configurada."""
    path = preset_path(source_type, WATERMARK_FILE, profile_id)
    return str(path) if path.exists() else None


def clip_watermark_path(source_type: Optional[str] = None, profile_id: str | None = None) -> Optional[str]:
    """
    Caminho da arte queimada no clipe, ou None se a conta não configurou uma.

    None é o estado normal, não um erro: só as contas em que o usuário subiu a
    arte ganham a marca, e é isso que impede uma conta de sair assinada com a
    logo que outra escolheu.
    """
    path = preset_path(source_type, CLIP_WATERMARK_FILE, profile_id)
    return str(path) if path.exists() else None


def detect_brand_regions(
    video_path: str,
    start_time: float,
    end_time: float,
) -> dict:
    """
    Detecta elementos de marca de terceiros no trecho, em pixels do vídeo FONTE:

    - "qr": QR codes estáveis (detector do OpenCV em frames amostrados).
    - "static": sobreposições estáticas (logos de canal) — bordas que persistem
      em TODAS as cenas do trecho (uma sobreposição fica no mesmo lugar
      independente da câmera; o cenário atrás muda a cada corte), restritas às
      faixas superior/inferior do frame (onde marcas de canal ficam).

    Returns:
        {"qr": [(x,y,w,h), ...], "static": [(x,y,w,h), ...]}
    """
    import cv2
    import numpy as np

    duration = max(end_time - start_time, 1.0)
    sample_fps = _QR_SAMPLES / duration

    qr_boxes: list[tuple[float, float, float, float]] = []
    face_boxes: list[tuple[int, int, int, int]] = []
    scene_edge_maps: list = []   # máscara de bordas persistentes de cada cena
    cut_pairs: list = []         # (frame antes, frame depois) de cada corte
    scene_acc = None             # acumulador de bordas da cena atual
    scene_len = 0
    prev_gray = None
    scene_cuts = 0
    src_w = src_h = 0
    n_frames = 0

    def _finalize_scene() -> None:
        """Fecha a cena atual: borda 'da cena' = presente em >=70% dos frames dela."""
        nonlocal scene_acc, scene_len
        if scene_acc is not None and scene_len > 0:
            needed = max(1, math.ceil(_EDGE_PERSISTENCE * scene_len))
            scene_edge_maps.append(scene_acc >= needed)
        scene_acc = None
        scene_len = 0

    with tempfile.TemporaryDirectory() as tmpdir:
        pattern = os.path.join(tmpdir, "q_%04d.jpg")
        subprocess.run(
            ["ffmpeg", "-y", "-ss", str(start_time), "-i", video_path,
             "-t", str(duration), "-vf", f"fps={sample_fps}", "-q:v", "2", pattern],
            capture_output=True, timeout=300,
        )
        frames = sorted(glob.glob(os.path.join(tmpdir, "q_*.jpg")))
        if not frames:
            return {"qr": [], "static": []}
        n_frames = len(frames)

        detector = cv2.QRCodeDetector()
        for path in frames:
            img = cv2.imread(path)
            if img is None:
                continue
            src_h, src_w = img.shape[:2]

            # QR codes
            try:
                found, points = detector.detectMulti(img)
            except cv2.error:
                found, points = False, None
            if found and points is not None:
                for quad in points:
                    xs, ys = quad[:, 0], quad[:, 1]
                    x, y = float(xs.min()), float(ys.min())
                    w, h = float(xs.max() - x), float(ys.max() - y)
                    area_frac = (w * h) / (src_w * src_h)
                    if _MIN_AREA <= area_frac <= _MAX_AREA:
                        qr_boxes.append((x, y, w, h))

            # Rostos viram zona de exclusão: nunca borrar pessoas
            face_boxes.extend(_detect_faces(img, src_w, src_h))

            # Bordas do frame (dilate 3x3 tolera jitter de 1px da compressão)
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            edges = cv2.dilate(
                cv2.Canny(gray, 60, 140), np.ones((3, 3), np.uint8)
            )

            # Corte de cena (troca de câmera muda a luminância global) fecha a
            # cena atual — as bordas são acumuladas POR CENA. O par de frames
            # ao redor do corte é guardado para validar candidatos depois.
            if prev_gray is not None and prev_gray.shape == gray.shape:
                if float(np.abs(gray.astype(np.int16) - prev_gray).mean()) > _SCENE_CUT_DIFF:
                    scene_cuts += 1
                    cut_pairs.append((prev_gray, gray.astype(np.int16)))
                    _finalize_scene()
            prev_gray = gray.astype(np.int16)

            if scene_acc is None:
                scene_acc = np.zeros(edges.shape, dtype=np.uint16)
            scene_acc += (edges > 0).astype(np.uint16)
            scene_len += 1

    _finalize_scene()

    if not src_w:
        return {"qr": [], "static": []}

    qr_regions = _cluster_boxes(qr_boxes, src_w, src_h, n_frames) if qr_boxes else []

    # Uma sobreposição de canal fica no MESMO lugar em todas as câmeras; o
    # cenário atrás muda a cada corte. Então a borda só é "marca" se persistir
    # em TODAS as cenas. Com menos de 2 cenas não há como distinguir marca de
    # cenário parado — detecção desligada.
    if len(scene_edge_maps) >= _MIN_SCENES:
        import numpy as np

        persistent_mask = scene_edge_maps[0]
        for m in scene_edge_maps[1:]:
            persistent_mask = np.logical_and(persistent_mask, m)
        static_regions = _detect_static_overlays(
            persistent_mask, n_frames, src_w, src_h, qr_regions, face_boxes,
            cut_pairs,
        )
    else:
        static_regions = []
        logger.info("Static-mark detection skipped: fewer than 2 scenes in segment")

    logger.info(
        f"Brand detection: {len(qr_regions)} QR region(s), "
        f"{len(static_regions)} static overlay(s), {scene_cuts} scene cut(s)"
    )
    return {"qr": qr_regions, "static": static_regions}


def _detect_faces(img, src_w: int, src_h: int) -> list[tuple[int, int, int, int]]:
    """Bboxes de rosto expandidos para cobrir a pessoa (rosto + tronco)."""
    import cv2
    import mediapipe as mp

    boxes = []
    try:
        with mp.solutions.face_detection.FaceDetection(
            model_selection=1, min_detection_confidence=0.5
        ) as detector:
            res = detector.process(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    except Exception:
        return boxes
    if not res.detections:
        return boxes
    for det in res.detections:
        b = det.location_data.relative_bounding_box
        x, y = b.xmin * src_w, b.ymin * src_h
        w, h = b.width * src_w, b.height * src_h
        # Expande: 0.75x lateral, 0.5x acima (cabelo), 3x abaixo (tronco)
        ex0 = int(x - 0.75 * w)
        ey0 = int(y - 0.5 * h)
        ex1 = int(x + w + 0.75 * w)
        ey1 = int(y + h + 3.0 * h)
        boxes.append((
            max(0, ex0), max(0, ey0),
            min(src_w, ex1) - max(0, ex0), min(src_h, ey1) - max(0, ey0),
        ))
    return boxes


def _detect_static_overlays(
    persistent_mask,
    n_frames: int,
    src_w: int,
    src_h: int,
    qr_regions: list[tuple[int, int, int, int]],
    face_boxes: list[tuple[int, int, int, int]],
    cut_pairs: list,
) -> list[tuple[int, int, int, int]]:
    """
    Sobreposições estáticas via bordas persistentes ENTRE CENAS: o
    texto/contorno da marca aparece no mesmo lugar em todas as câmeras,
    enquanto o cenário muda a cada corte. Fragmentos próximos (letras da mesma
    marca) são fundidos e a caixa final ganha um pad generoso para cobrir o
    fundo/pílula da marca ao redor do texto detectado.
    """
    import cv2
    import numpy as np

    if persistent_mask is None or n_frames < 4:
        return []

    persistent = persistent_mask.astype(np.uint8) * 255

    # Restringe às faixas superior/inferior — marcas de canal ficam lá; o
    # conteúdo central (pessoa parada) não pode virar blob
    band = int(src_h * _STATIC_BAND)
    persistent[band:src_h - band, :] = 0

    # QRs já são tratados separadamente: não entram nos blobs
    for (x, y, w, h) in qr_regions:
        persistent[max(0, y):y + h, max(0, x):x + w] = 0

    # Pessoas nunca são borradas: rostos (expandidos p/ tronco) ficam fora
    for (x, y, w, h) in face_boxes:
        persistent[max(0, y):y + h, max(0, x):x + w] = 0

    # Fecha buracos (proporcional à resolução) para unir letras da mesma marca
    k = max(3, int(min(src_w, src_h) * 0.015))
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (k, k))
    blob = cv2.morphologyEx(persistent, cv2.MORPH_CLOSE, kernel, iterations=2)

    n_labels, _labels, stats, _ = cv2.connectedComponentsWithStats(blob)
    edge_margin = int(min(src_w, src_h) * 0.10)
    boxes: list[tuple[int, int, int, int]] = []
    for i in range(1, n_labels):
        x, y, w, h = stats[i, 0], stats[i, 1], stats[i, 2], stats[i, 3]
        area_frac = (w * h) / (src_w * src_h)
        if not (_STATIC_MIN_AREA <= area_frac <= _STATIC_MAX_AREA):
            continue
        if min(w, h) < 8:
            continue
        # Marcas de canal ficam coladas às bordas do frame
        dist_to_edge = min(x, y, src_w - (x + w), src_h - (y + h))
        if dist_to_edge > edge_margin:
            continue
        # Validação decisiva: nos cortes de cena, os traços de um overlay
        # queimado ficam pixel-idênticos (a câmera muda por baixo dele);
        # traços de cenário mudam junto com a câmera.
        if not _survives_cuts(persistent, (x, y, w, h), cut_pairs):
            continue
        boxes.append((x, y, w, h))

    # Funde fragmentos próximos (letras/partes da mesma marca)
    gap = int(src_w * 0.03)
    boxes = _merge_regions(
        [(max(0, x - gap), max(0, y - gap), w + 2 * gap, h + 2 * gap)
         for (x, y, w, h) in boxes]
    )
    # Desfaz a expansão do gap
    boxes = [
        (x + gap, y + gap, max(1, w - 2 * gap), max(1, h - 2 * gap))
        for (x, y, w, h) in boxes
    ]

    # Só as 3 maiores por área (falsos positivos tendem a ser pequenos)
    boxes.sort(key=lambda b: b[2] * b[3], reverse=True)
    boxes = boxes[:3]

    # Pad agressivo: as bordas detectadas são o TEXTO da marca; o fundo da
    # pílula ao redor não gera borda persistente e precisa entrar na caixa
    regions = []
    for (x, y, w, h) in boxes:
        pad_x, pad_y = int(w * 0.30), int(h * 0.60)
        rx, ry = max(0, x - pad_x), max(0, y - pad_y)
        regions.append((
            rx, ry,
            min(src_w - rx, w + 2 * pad_x),
            min(src_h - ry, h + 2 * pad_y),
        ))
    return _merge_regions(regions)


def _survives_cuts(
    persistent,
    box: tuple[int, int, int, int],
    cut_pairs: list,
) -> bool:
    """
    True se uma fração relevante dos pixels de borda persistente dentro do box
    fica pixel-idêntica através dos cortes de cena (comportamento de overlay
    queimado: o interior dos traços não muda; só a franja anti-aliased com o
    fundo muda). Cenário reprovado: quase nada fica estável quando a câmera
    troca. A mediana entre os cortes tolera um corte atípico (fade, flash).
    """
    import numpy as np

    if not cut_pairs:
        return True   # sem cortes registrados não há como validar; mantém

    x, y, w, h = box
    mask = persistent[y:y + h, x:x + w] > 0
    if not mask.any():
        return False

    stable_fracs = []
    for before, after in cut_pairs:
        region_diff = np.abs(after[y:y + h, x:x + w] - before[y:y + h, x:x + w])
        stable_fracs.append(float((region_diff[mask] <= _OVERLAY_STABLE_DIFF).mean()))
    frac = float(np.median(stable_fracs))
    logger.debug(f"cut-survival box={box}: median stable_frac={frac:.2f}")
    return frac >= _OVERLAY_STABLE_FRAC


def _merge_regions(
    regions: list[tuple[int, int, int, int]],
) -> list[tuple[int, int, int, int]]:
    """Une regiões que se intersectam em uma única caixa."""
    merged = list(regions)
    changed = True
    while changed:
        changed = False
        for i in range(len(merged)):
            for j in range(i + 1, len(merged)):
                ax, ay, aw, ah = merged[i]
                bx, by, bw, bh = merged[j]
                if not (ax + aw < bx or bx + bw < ax or ay + ah < by or by + bh < ay):
                    x0, y0 = min(ax, bx), min(ay, by)
                    x1, y1 = max(ax + aw, bx + bw), max(ay + ah, by + bh)
                    merged[i] = (x0, y0, x1 - x0, y1 - y0)
                    merged.pop(j)
                    changed = True
                    break
            if changed:
                break
    return merged


def _cluster_boxes(
    boxes: list[tuple[float, float, float, float]],
    src_w: int,
    src_h: int,
    n_samples: int,
) -> list[tuple[int, int, int, int]]:
    """Agrupa caixas próximas; mantém grupos vistos em >= _MIN_HITS frames."""
    import math

    diag = math.hypot(src_w, src_h)
    clusters: list[list[tuple[float, float, float, float]]] = []

    for box in boxes:
        cx, cy = box[0] + box[2] / 2, box[1] + box[3] / 2
        placed = False
        for cluster in clusters:
            rx, ry, rw, rh = cluster[0]
            rcx, rcy = rx + rw / 2, ry + rh / 2
            if math.hypot(cx - rcx, cy - rcy) <= _CLUSTER_DIST * diag:
                cluster.append(box)
                placed = True
                break
        if not placed:
            clusters.append([box])

    min_hits = _MIN_HITS if n_samples >= 4 else 1
    regions = []
    for cluster in clusters:
        if len(cluster) < min_hits:
            continue
        x0 = min(b[0] for b in cluster)
        y0 = min(b[1] for b in cluster)
        x1 = max(b[0] + b[2] for b in cluster)
        y1 = max(b[1] + b[3] for b in cluster)
        pad_x, pad_y = (x1 - x0) * _PAD, (y1 - y0) * _PAD
        x = max(0, int(x0 - pad_x))
        y = max(0, int(y0 - pad_y))
        w = min(src_w - x, int((x1 - x0) + 2 * pad_x))
        h = min(src_h - y, int((y1 - y0) + 2 * pad_y))
        regions.append((x, y, w, h))
    return regions
