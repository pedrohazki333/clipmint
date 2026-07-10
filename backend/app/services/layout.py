"""
Layout dos clips — capa estática + banner de título.

Formato final (1080x1920):
  ┌──────────────────┐
  │  CAPA (estática) │  ← print de uma expressão marcante do vídeo (0–768px)
  │   ╭─ BANNER ─╮   │  ← pílula vermelha com o título, sobre a emenda
  │  VÍDEO (rodando) │  ← crop com face tracking + legendas (768–1920px)
  └──────────────────┘

- Capa: MediaPipe escolhe o frame com a expressão mais forte (boca aberta =
  risada/espanto), com desempate por tamanho/confiança do rosto. Crop
  centralizado no rosto.
- Banner: pílula vermelha com "lábio" inferior escuro (efeito 3D), texto
  branco em caixa alta, quebra de linha e tamanho de fonte automáticos.
"""

import glob
import logging
import math
import os
import re
import subprocess
import tempfile
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

CANVAS_W = 1080
COVER_W, COVER_H = 1080, 768

# ─── Banner ───────────────────────────────────────────────────────────────────

_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]

_BANNER_RED = (237, 40, 40, 255)
_BANNER_RED_DARK = (163, 18, 18, 255)
_BANNER_MAX_TEXT_W = 840   # largura máxima de uma linha de texto
_BANNER_PAD_X = 60
_BANNER_PAD_Y = 34
_BANNER_LIP = 10           # deslocamento do "lábio" 3D inferior
_LINE_SPACING = 1.08

# Remove emojis/símbolos que a fonte não renderiza
_EMOJI_RE = re.compile(r"[\U0001F000-\U0001FAFF←-⯿️‍]")


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in _FONT_CANDIDATES:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


def _balanced_wrap(
    words: list[str], font: ImageFont.FreeTypeFont, max_w: int, n_lines: int
) -> Optional[list[str]]:
    """
    Divide as palavras em exatamente n_lines com larguras equilibradas
    (minimiza a linha mais larga — visual de pílula simétrica, sem linha órfã).
    None se não couber em max_w.
    """
    from itertools import combinations

    if n_lines == 1:
        line = " ".join(words)
        return [line] if font.getlength(line) <= max_w else None

    if len(words) < n_lines:
        return None

    best: Optional[list[str]] = None
    best_width = float("inf")
    for splits in combinations(range(1, len(words)), n_lines - 1):
        bounds = [0, *splits, len(words)]
        lines = [" ".join(words[a:b]) for a, b in zip(bounds, bounds[1:])]
        widest = max(font.getlength(l) for l in lines)
        if widest <= max_w and widest < best_width:
            best, best_width = lines, widest
    return best


def generate_banner(text: str, output_path: str) -> tuple[int, int]:
    """
    Gera o PNG da pílula vermelha com o título em branco.

    Returns:
        (width, height) da imagem gerada — usado para posicionar o overlay.
    """
    text = _EMOJI_RE.sub("", text).strip().upper()
    if not text:
        text = "ASSISTA ATÉ O FINAL"

    # Preferência: até 2 linhas equilibradas com fonte grande;
    # 3 linhas só como último recurso para textos muito longos
    words = text.split()
    font, lines = None, None
    for max_lines in (2, 3):
        min_size = 44 if max_lines == 2 else 34
        for size in range(60, min_size - 1, -2):
            f = _load_font(size)
            for n in range(1, max_lines + 1):
                wrapped = _balanced_wrap(words, f, _BANNER_MAX_TEXT_W, n)
                if wrapped:
                    font, lines = f, wrapped
                    break
            if font:
                break
        if font:
            break
    if font is None:  # texto extremamente longo: trunca
        font = _load_font(34)
        lines = _balanced_wrap(words[:14], font, _BANNER_MAX_TEXT_W, 3) or [text[:30]]

    ascent, descent = font.getmetrics()
    line_h = math.ceil((ascent + descent) * _LINE_SPACING)
    text_w = max(int(font.getlength(l)) for l in lines)
    text_h = line_h * len(lines)

    pill_w = text_w + 2 * _BANNER_PAD_X
    pill_h = text_h + 2 * _BANNER_PAD_Y
    radius = pill_h // 2 if len(lines) == 1 else 40

    img = Image.new("RGBA", (pill_w, pill_h + _BANNER_LIP), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Lábio 3D (vermelho escuro, deslocado para baixo) + pílula principal
    draw.rounded_rectangle(
        [0, _BANNER_LIP, pill_w - 1, pill_h + _BANNER_LIP - 1],
        radius=radius, fill=_BANNER_RED_DARK,
    )
    draw.rounded_rectangle([0, 0, pill_w - 1, pill_h - 1], radius=radius, fill=_BANNER_RED)

    y = _BANNER_PAD_Y + (line_h - ascent - descent) // 2
    for line in lines:
        x = (pill_w - font.getlength(line)) / 2
        draw.text((x, y), line, font=font, fill=(255, 255, 255, 255))
        y += line_h

    img.save(output_path)
    logger.info(f"Banner generated: {output_path} ({pill_w}x{img.height}, {len(lines)} line(s))")
    return pill_w, img.height


# ─── Capa (frame expressivo) ──────────────────────────────────────────────────

def _mouth_openness(image_rgb) -> float:
    """Razão de abertura da boca via FaceMesh (0 = fechada; >0.5 = bem aberta)."""
    import mediapipe as mp

    with mp.solutions.face_mesh.FaceMesh(
        static_image_mode=True, max_num_faces=1, min_detection_confidence=0.5
    ) as mesh:
        result = mesh.process(image_rgb)
    if not result.multi_face_landmarks:
        return 0.0
    lm = result.multi_face_landmarks[0].landmark
    # 13/14 = lábios internos (cima/baixo); 61/291 = cantos da boca
    vertical = math.dist((lm[13].x, lm[13].y), (lm[14].x, lm[14].y))
    horizontal = math.dist((lm[61].x, lm[61].y), (lm[291].x, lm[291].y))
    return vertical / horizontal if horizontal > 0 else 0.0


def generate_cover(
    video_path: str,
    start_time: float,
    end_time: float,
    output_path: str,
    width: int = COVER_W,
    height: int = COVER_H,
    watermark_path: Optional[str] = None,
    qr_regions: Optional[list[tuple[int, int, int, int]]] = None,
    static_regions: Optional[list[tuple[int, int, int, int]]] = None,
) -> str:
    """
    Captura o frame mais expressivo do trecho e recorta como capa.

    Estratégia: amostra 1 frame/s, detecta rostos (MediaPipe), pré-seleciona os
    8 melhores por confiança × tamanho e escolhe o de boca mais aberta
    (risada/espanto = expressão forte). Crop centralizado no rosto.

    Returns:
        "expressive" | "biggest_face" | "center" (método usado, para logging).
    """
    import cv2
    import mediapipe as mp

    duration = max(end_time - start_time, 1.0)

    with tempfile.TemporaryDirectory() as tmpdir:
        pattern = os.path.join(tmpdir, "c_%04d.jpg")
        subprocess.run(
            ["ffmpeg", "-y", "-ss", str(start_time), "-i", video_path,
             "-t", str(duration), "-vf", "fps=1", "-q:v", "2", pattern],
            capture_output=True, timeout=300,
        )
        frames = sorted(glob.glob(os.path.join(tmpdir, "c_*.jpg")))
        if not frames:
            raise RuntimeError(f"Could not extract cover frames from {video_path}")

        # Detecta rostos em todos os frames amostrados
        candidates = []  # (frame_path, cx, cy, area, det_score)
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
                candidates.append((
                    path,
                    min(1.0, max(0.0, b.xmin + b.width / 2)),
                    min(1.0, max(0.0, b.ymin + b.height / 2)),
                    max(0.0, b.width * b.height),
                    float(best.score[0]),
                ))

        method = "expressive"
        if not candidates:
            # Sem rosto: frame do meio, crop central
            chosen = (frames[len(frames) // 2], 0.5, 0.45, 0.0, 0.0)
            method = "center"
        else:
            # Top 8 por confiança × tamanho → mais expressivo (boca aberta)
            candidates.sort(key=lambda c: c[3] * c[4], reverse=True)
            top = candidates[:8]
            max_area = max(c[3] for c in top) or 1.0
            scored = []
            for cand in top:
                try:
                    img = cv2.imread(cand[0])
                    mar = _mouth_openness(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
                except Exception:
                    mar = 0.0
                scored.append((mar + 0.3 * (cand[3] / max_area), cand))
            scored.sort(key=lambda s: s[0], reverse=True)
            chosen = scored[0][1]
            if all(s[0] <= 0.3 for s in scored):
                method = "biggest_face"

        frame_path, cx, cy = chosen[0], chosen[1], chosen[2]
        crop_box = _crop_to_cover(frame_path, cx, cy, width, height, output_path)

    # Regiões de marcas de terceiros (coordenadas da fonte) → coordenadas da capa
    qr_in_cover = _transform_regions(qr_regions or [], crop_box, width, height)
    static_in_cover = _transform_regions(static_regions or [], crop_box, width, height)

    _brand_cover(output_path, watermark_path, qr_in_cover, static_in_cover)
    logger.info(f"Cover generated ({method}): {output_path}")
    return method


def _transform_regions(
    regions: list[tuple[int, int, int, int]],
    crop_box: tuple[int, int, int, int],
    out_w: int,
    out_h: int,
) -> list[tuple[int, int, int, int]]:
    """Converte regiões da fonte para coordenadas da capa (descarta as que
    ficam quase totalmente fora do crop)."""
    cx, cy, cw, ch = crop_box
    sx, sy = out_w / cw, out_h / ch
    result = []
    for (x, y, w, h) in regions:
        # Interseção com o crop
        ix0, iy0 = max(x, cx), max(y, cy)
        ix1, iy1 = min(x + w, cx + cw), min(y + h, cy + ch)
        if ix1 - ix0 <= 0 or iy1 - iy0 <= 0:
            continue
        if (ix1 - ix0) * (iy1 - iy0) < 0.2 * w * h:
            continue  # sobra desprezível dentro do crop
        result.append((
            int((ix0 - cx) * sx), int((iy0 - cy) * sy),
            int((ix1 - ix0) * sx), int((iy1 - iy0) * sy),
        ))
    return result


def _brand_cover(
    cover_path: str,
    watermark_path: Optional[str],
    qr_regions: Optional[list[tuple[int, int, int, int]]] = None,
    static_regions: Optional[list[tuple[int, int, int, int]]] = None,
) -> None:
    """
    Neutraliza marcas de terceiros na capa e aplica a logo do usuário:
    - regiões estáticas (logos de canal): borrão;
    - QR codes (das regiões detectadas no trecho + detecção na própria capa):
      borrão + logo do usuário centralizada;
    - pin da logo no canto superior direito (posição padrão de marca de canal).
    """
    import cv2
    import numpy as np
    from PIL import ImageFilter

    cover = Image.open(cover_path).convert("RGBA")

    # Detecção de QR na própria capa (backup das regiões vindas do trecho)
    try:
        arr = cv2.cvtColor(np.array(cover.convert("RGB")), cv2.COLOR_RGB2BGR)
        found, points = cv2.QRCodeDetector().detectMulti(arr)
    except Exception:
        found, points = False, None

    qr_boxes = [tuple(r) for r in (qr_regions or [])]
    if found and points is not None:
        for quad in points:
            xs, ys = quad[:, 0], quad[:, 1]
            x, y = int(xs.min()), int(ys.min())
            w, h = int(xs.max() - x), int(ys.max() - y)
            area_frac = (w * h) / (cover.width * cover.height)
            if 0.0005 <= area_frac <= 0.20:
                pad_x, pad_y = int(w * 0.12), int(h * 0.12)
                box = (max(0, x - pad_x), max(0, y - pad_y), w + 2 * pad_x, h + 2 * pad_y)
                if not any(_boxes_overlap(box, q) for q in qr_boxes):
                    qr_boxes.append(box)

    def _blur(x: int, y: int, w: int, h: int) -> None:
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(cover.width, x + w), min(cover.height, y + h)
        if x1 - x0 > 2 and y1 - y0 > 2:
            patch = cover.crop((x0, y0, x1, y1)).filter(ImageFilter.GaussianBlur(24))
            cover.paste(patch, (x0, y0))

    for (x, y, w, h) in static_regions or []:
        _blur(x, y, w, h)
    for (x, y, w, h) in qr_boxes:
        _blur(x, y, w, h)

    if watermark_path and os.path.exists(watermark_path):
        logo = Image.open(watermark_path).convert("RGBA")

        # Logo sobre cada QR neutralizado
        for (x, y, w, h) in qr_boxes:
            scale = min(w * 0.9 / logo.width, h * 0.9 / logo.height)
            lw, lh = max(1, int(logo.width * scale)), max(1, int(logo.height * scale))
            resized = logo.resize((lw, lh), Image.LANCZOS)
            cover.alpha_composite(resized, (x + (w - lw) // 2, y + (h - lh) // 2))

        # Pin no canto superior direito (posição padrão de marca de canal)
        pin_w = int(cover.width * 0.18)
        pin_h = int(logo.height * pin_w / logo.width)
        pinned = logo.resize((pin_w, pin_h), Image.LANCZOS)
        cover.alpha_composite(pinned, (cover.width - pin_w - 28, 28))

    cover.convert("RGB").save(cover_path)


def _boxes_overlap(a: tuple, b: tuple) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return not (ax + aw <= bx or bx + bw <= ax or ay + ah <= by or by + bh <= ay)


def _crop_to_cover(
    frame_path: str, cx: float, cy: float, width: int, height: int, output_path: str
) -> tuple[int, int, int, int]:
    """Recorta o frame na proporção da capa, centralizado no rosto (com clamp)."""
    img = Image.open(frame_path)
    src_w, src_h = img.size
    target_ratio = width / height

    if src_w / src_h > target_ratio:
        crop_h = src_h
        crop_w = int(src_h * target_ratio)
    else:
        crop_w = src_w
        crop_h = int(src_w / target_ratio)

    x = max(0, min(int(src_w * cx - crop_w / 2), src_w - crop_w))
    y = max(0, min(int(src_h * cy - crop_h / 2), src_h - crop_h))

    img.crop((x, y, x + crop_w, y + crop_h)).resize(
        (width, height), Image.LANCZOS
    ).save(output_path)
    return (x, y, crop_w, crop_h)
