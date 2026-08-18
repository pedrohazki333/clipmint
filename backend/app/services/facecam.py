"""
Detecção da caixa da facecam em lives de streamer.

Numa live de jogo o layout é fixo: a webcam é um retângulo estático sobre o
gameplay, quase sempre encostado em um canto. Este módulo descobre onde esse
retângulo está, em coordenadas relativas (0–1) da fonte, para o clipper cortar
os dois painéis do mesmo vídeo.

O layout, porém, só é fixo por trechos: o streamer troca de cena, dá zoom na
cam, joga ela para o outro canto no meio da live. Por isso a saída é uma LINHA
DO TEMPO (`CamPhase`) — uma fase por caixa, com o intervalo em que ela vale — e
o clipper troca o recorte na hora certa. Cam parada devolve uma fase só.

Estratégia em três etapas:

  1. Aglomerado de rostos — amostra frames ao longo do trecho e roda MediaPipe,
     guardando TODOS os rostos de cada frame. Cada aglomerado é um rosto
     recorrente numa região da tela. Quem vence não é o rosto mais confiante nem
     o maior, e sim o mais PERSISTENTE: a cam do streamer está em quase todo
     frame, enquanto um popup de inscrito dura alguns segundos — era exatamente
     assim que o alerta de sub roubava a cam do detector.

  2. Fases — a cam não aparece em dois lugares ao mesmo tempo, então dois
     aglomerados que dividem os mesmos frames são rostos concorrentes (o menor
     cai fora); dois em janelas de tempo distintas são a mesma cam depois de se
     mexer. A trilha resultante é quebrada onde a posição ou o tamanho do rosto
     muda e se mantém mudada.

  3. Encaixe nas bordas — a caixa derivada do rosto é só um palpite grosseiro
     (sai do tamanho do rosto), e sobra de gameplay no painel é justamente o que
     estraga o clipe. As bordas reais da cam são LINHAS RETAS que atravessam a
     caixa inteira, então a busca varre o frame mediano a partir do rosto para
     fora e pontua cada coluna/linha pela fração da extensão com gradiente forte
     — não pela média do gradiente, que se perde em conteúdo ruidoso. A busca é
     do rosto até a borda do frame (não uma janela estreita em volta do palpite),
     porque o palpite erra fácil por 30%+.

     Em empate, vence a borda mais PRÓXIMA do rosto: cortar um filete da cam é
     invisível, deixar vazar gameplay é o defeito visível.

Sem rosto estável no trecho, a lista volta vazia — o clipper cai para um recorte
padrão no canto e o usuário pode corrigir manualmente pelo job.
"""

import copy
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
# Frames analisados no trecho. Eram 24, que num clipe de 80s dá uma amostra a
# cada 3,4s — mais lento que o ritmo de corte de um vídeo EDITADO, em que a
# edição alterna entre os POVs de vários streamers. Medido num clipe do
# Bahiaqz: com 24 amostras o detector colocou a cam à direita num trecho em que
# o rosto estava à esquerda, e o painel saiu mostrando tela vazia. Com 48 o
# intervalo cai para ~1,7s e as trocas são acompanhadas.
_MAX_SAMPLES = 48
_DETECT_WIDTH = 1920       # teto da largura de trabalho (4K inteiro não compensa)

# Ladrilhos de detecção. O rosto dentro de uma facecam pequena ocupa ~3% da
# largura do frame, e nessa escala o MediaPipe não acha NADA — medido nesta
# base: zero detecções no frame inteiro mesmo em resolução nativa e confiança
# 0.15, contra 5/5 frames no mesmo trecho quando a busca é feita no quadrante.
# Por isso a varredura é por quadrantes sobrepostos, cada um ampliado para
# _TILE_WIDTH: é a diferença entre enxergar a cam e cair no palpite de canto.
# A sobreposição existe para um rosto na divisa não ficar partido em dois.
_TILE_SPAN = 0.6           # lado do ladrilho, em fração do frame
_TILE_WIDTH = 960          # largura de trabalho de cada ladrilho
_DEDUPE_RADIUS = 0.02      # detecções do frame inteiro e do ladrilho, mesma cara

# Aglomeração
_STABLE_RADIUS = 0.12      # distância máx. do centro mediano para contar como a cam
_MIN_CONFIDENCE = 0.35     # fração mínima de frames com rosto estável

# Rostos concorrentes (popup de inscrito, plateia, personagem do jogo)
_CLUSTER_MIN_COVERAGE = 0.15  # presença mínima para um 2º aglomerado ser considerado
_CLUSTER_OVERLAP = 0.25    # acima disso os dois dividem os mesmos frames: são rostos
                           # diferentes convivendo na tela, não a cam que se moveu
_CLUSTER_SIZE_RATIO = 2.5  # ...e o rosto tem que ter tamanho comparável ao principal

# Mudanças de layout ao longo do clip (cam muda de canto, cena com zoom)
_PHASE_MOVE = 0.06         # deslocamento do centro do rosto que denuncia outra caixa
_PHASE_ZOOM = 1.45         # razão de área do rosto que denuncia zoom (e o inverso)
_PHASE_CONFIRM = 2         # amostras seguidas para a mudança valer (anti-ruído)
# Não há mais teto de fases nem mínimo de amostras por fase. Os dois existiam
# porque cada fase custava um recorte no filtergraph, e fundir as sobrantes era
# o preço — só que fundir fases de POSIÇÕES diferentes é exatamente o que
# quebrava o enquadramento em vídeo editado: o encaixe passava a procurar
# bordas comuns entre planos que não têm nenhuma, e achava a moldura da UI do
# jogo. Agora o custo do render é por CAIXA ÚNICA (ver clipper), então a
# quantidade de trocas deixou de importar.
# Fases vizinhas dentro destas margens enquadram a mesma cam e viram uma só —
# trocar o recorte à toa no meio do clipe aparece como pulinho de zoom.
_SAME_BOX_CENTER = 0.02    # deslocamento do centro, em fração do frame
_SAME_BOX_SIZE = 0.12      # diferença de lado, em fração do maior
# Quanto uma fase pode destoar de tamanho das outras DO MESMO clip antes de ser
# tratada como trava errada. Mais folgado que a tolerância do job porque num
# vídeo editado streamers diferentes têm cams de tamanhos diferentes — mas não
# de 2x. Medido no caso do Bahiaqz: cam real ~0.17-0.20 de largura, card do
# jogo 0.46 (2.7x).
_CLIP_SIZE_TOLERANCE = 1.6

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

# Teto de tamanho da cam. O prior de proporção sozinho é cego para o pior erro:
# uma caixa encostada nas bordas do frame tem a proporção DO FRAME (16:9) e sai
# com peso máximo, então "o frame inteiro" competia de igual para igual com a
# cam de verdade — e ganhava quando as bordas do gameplay eram mais fortes que
# a moldura da cam. Medido nas lives deste projeto: as cams reais ficam entre
# 0.05 e 0.15 de área, e os erros observados entre 0.41 e 0.82. O teto separa
# os dois grupos com folga dos dois lados.
_MAX_CAM_W = 0.55          # fração máxima da largura do frame
_MAX_CAM_H = 0.60          # ...e da altura
_MAX_CAM_AREA = 0.30       # ...e da área, que é o que pega a caixa quase-cheia
_EDGE_REACH = 4.0          # sem linha e a até 4 alturas de rosto da borda = a cam encosta nela
_CAM_INSET = 0.01          # recuo para dentro da caixa, em fração do lado
_CAM_INSET_MIN = 3         # ...com piso em pixels da RESOLUÇÃO DE DETECÇÃO: cada
                           # pixel aqui vale 4 na fonte 4K, e a borda tem ±1 de
                           # incerteza. Perder 3px da cam é invisível depois da
                           # ampliação; deixar 3px de gameplay é uma listra.
_EDGE_SNAP = 0.05          # só no fallback sem encaixe: quase colada na borda, encosta


@dataclass(eq=False)
class _Obs:
    """Um rosto detectado num frame amostrado, em frações do frame."""

    cx: float
    cy: float
    w: float
    h: float
    score: float


class _Cluster:
    """Rosto recorrente numa região da tela, ao longo dos frames amostrados."""

    def __init__(self) -> None:
        self.by_frame: dict[int, list[_Obs]] = {}
        self._sum_x = 0.0
        self._sum_y = 0.0
        self._n = 0

    def add(self, frame_idx: int, obs: _Obs) -> None:
        self.by_frame.setdefault(frame_idx, []).append(obs)
        self._sum_x += obs.cx
        self._sum_y += obs.cy
        self._n += 1

    @property
    def frames(self) -> set[int]:
        return set(self.by_frame)

    def center(self) -> tuple[float, float]:
        return self._sum_x / self._n, self._sum_y / self._n

    def median_area(self) -> float:
        return _median([o.w * o.h for seen in self.by_frame.values() for o in seen])


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


@dataclass
class CamPhase:
    """
    Trecho do clip em que a facecam fica na mesma caixa.

    Tempos em segundos relativos ao início do clip — é assim que o filtergraph
    liga cada recorte (o `-ss` antes do `-i` zera o relógio do FFmpeg).
    """

    start: float
    end: float
    rect: FacecamRect

    def as_dict(self) -> dict:
        return {"start": self.start, "end": self.end, "rect": self.rect.as_dict()}


def single_phase(rect: FacecamRect, duration: float) -> list[CamPhase]:
    """Linha do tempo de uma fase só — cam parada, ou caixa dada pelo usuário."""
    return [CamPhase(start=0.0, end=duration, rect=rect)]


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


def detect_facecam_phases(
    video_path: str,
    start_time: float,
    end_time: float,
    box_aspect: float = _DEFAULT_BOX_ASPECT,
) -> list[CamPhase]:
    """
    Linha do tempo da facecam no trecho. Bloqueante — rodar via to_thread.

    O layout da live não é sagrado: o streamer troca de cena, dá zoom na cam,
    joga ela para o outro canto. Por isso o retorno é uma LISTA de fases, cada
    uma com a caixa que vale no seu intervalo (em segundos relativos ao início
    do trecho). Uma cam parada devolve uma fase só.

    Args:
        box_aspect: proporção largura/altura desejada da caixa (a do painel do
            clipe final), usada para completar a caixa a partir do rosto.

    Returns:
        Fases em ordem cronológica cobrindo o trecho inteiro; lista vazia se
        não houver cam estável (o chamador decide o fallback).
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
             # min(iw) para não AMPLIAR fonte menor que o teto: inventar pixel
             # não devolve rosto nenhum e só deixa o encaixe de borda mais lento.
             "-vf", f"fps=1/{interval:.3f},scale='min({_DETECT_WIDTH},iw)':-2",
             "-q:v", "3", pattern],
            capture_output=True, timeout=600,
        )
        frames = sorted(glob.glob(os.path.join(tmpdir, "f_*.jpg")))
        if not frames:
            logger.warning(f"Facecam: no frames extracted from {video_path}")
            return []

        per_frame = _detect_faces_per_frame(frames, cv2, mp)
        track, confidence, groups = _cam_track(per_frame, len(frames))
        if track is None:
            return []

        # Uma caixa por POSIÇÃO da cam, encaixada com TODOS os frames em que
        # ela aparece — não por trecho contíguo. Num vídeo editado cada plano
        # dura 2-3 amostras, o que é pouco demais para o mapa de bordas fechar
        # uma caixa; juntando os frames do clipe inteiro que compartilham o
        # mesmo enquadramento, o encaixe volta a ter material de sobra.
        rect_by_group: dict[int, FacecamRect] = {}
        for gid, indexes in groups.items():
            rect_by_group[gid] = _fit_phase(
                [frames[i] for i in indexes],
                [track[i] for i in indexes],
                box_aspect, confidence, cv2, np,
            )

        rect_by_group = _consolidate_boxes(rect_by_group, groups)

        spans = _group_spans(track, groups)
        phases = [
            CamPhase(start=i0 * interval, end=(i1 + 1) * interval,
                     rect=copy.copy(rect_by_group[gid]))
            for i0, i1, gid in spans
        ]

    phases = _merge_equivalent_phases(phases)
    phases = _absorb_size_outliers(phases)

    # As bordas da linha do tempo são das amostras, não do vídeo: estica para
    # cobrir o trecho inteiro (senão sobra um buraco antes da 1ª/depois da última).
    phases[0].start = 0.0
    phases[-1].end = duration

    logger.info(
        f"Facecam: {len(phases)} fase(s) em {duration:.1f}s (confiança {confidence:.0%})"
    )
    for phase in phases:
        r = phase.rect
        logger.info(
            f"  [{phase.start:5.1f}s–{phase.end:5.1f}s] {r.method}: "
            f"x={r.x:.3f} y={r.y:.3f} w={r.w:.3f} h={r.h:.3f}"
        )
    return phases


def _absorb_size_outliers(phases: list[CamPhase]) -> list[CamPhase]:
    """
    Descarta as fases cuja caixa destoa de tamanho das outras DO MESMO clip.

    O detector de bordas procura retângulos com moldura forte, e a UI do jogo
    também é isso. Num vídeo do Bahiaqz ele travou no card "RELATÓRIO"
    desenhado no meio da tela: 46% da largura por 44% da altura, contra ~17%
    das fases vizinhas, que eram a cam de verdade no canto.

    A referência é o próprio clipe: a fase mais LONGA. Uma trava errada costuma
    durar poucos segundos, enquanto o enquadramento certo domina o trecho. A
    fase fora de escala herda a caixa da vizinha boa mais próxima no tempo, que
    num vídeo editado é quase sempre o mesmo layout de câmera.

    Só o tamanho é comparado. Cam que troca de canto mantendo o tamanho é
    mudança real de layout e passa intacta.
    """
    if len(phases) < 2:
        return phases

    reference = max(phases, key=lambda p: p.end - p.start).rect

    def _off(rect: FacecamRect) -> float:
        w_ratio = rect.w / reference.w if reference.w else 1.0
        h_ratio = rect.h / reference.h if reference.h else 1.0
        return max(w_ratio, 1 / w_ratio, h_ratio, 1 / h_ratio)

    good = [i for i, p in enumerate(phases) if _off(p.rect) <= _CLIP_SIZE_TOLERANCE]
    if not good or len(good) == len(phases):
        return phases

    for i, phase in enumerate(phases):
        if i in good:
            continue
        nearest = min(good, key=lambda g: abs(g - i))
        source = phases[nearest].rect
        logger.warning(
            f"Facecam: fase [{phase.start:.1f}s–{phase.end:.1f}s] com caixa "
            f"{phase.rect.w:.3f}x{phase.rect.h:.3f} destoa {_off(phase.rect):.1f}x "
            f"das outras do clip — provável moldura da UI do jogo; "
            f"usando a caixa de [{phases[nearest].start:.1f}s–{phases[nearest].end:.1f}s]"
        )
        phase.rect = FacecamRect(
            x=source.x, y=source.y, w=source.w, h=source.h,
            confidence=source.confidence, method="phase_fix",
        )

    return _merge_equivalent_phases(phases)


def _merge_equivalent_phases(phases: list[CamPhase]) -> list[CamPhase]:
    """
    Junta fases vizinhas que descrevem a MESMA caixa.

    A divisão em fases existe para a cam que se move. Quando duas fases vizinhas
    caem na mesma caixa, a cam não mudou — foi o rosto que oscilou — e manter a
    divisão troca o recorte no meio do clipe, o que aparece como um pulinho de
    zoom. Fica a caixa da fase mais longa, que teve mais frames para encaixar.
    """
    if not phases:
        return phases

    merged = [phases[0]]
    for phase in phases[1:]:
        last = merged[-1]
        if _same_box(last.rect, phase.rect):
            if (phase.end - phase.start) > (last.end - last.start):
                last.rect = phase.rect
            last.end = phase.end
            continue
        merged.append(phase)
    return merged


def _consolidate_boxes(
    rect_by_group: dict[int, FacecamRect], groups: dict[int, list[int]]
) -> dict[int, FacecamRect]:
    """
    Faz grupos que enquadram a MESMA cam compartilharem uma caixa só.

    O rosto oscila dentro da cam — o streamer se inclina, chega perto —, então
    o mesmo enquadramento vira vários grupos e cada um encaixa uma caixa
    ligeiramente diferente. Num clipe do Bahiaqz eram 10 caixas para 2 cams. Se
    isso chega ao render, cada volta ao mesmo canto recorta alguns pixels
    diferente da anterior, e o painel dá um pulinho a cada troca de plano.

    Vence a caixa do grupo com MAIS frames: foi a que teve mais material para o
    encaixe nas bordas.

    A consolidação também é o que mantém o filtergraph pequeno, já que o render
    cria um ramo por caixa única e não por fase.
    """
    order = sorted(rect_by_group, key=lambda g: len(groups[g]), reverse=True)
    canon: list[int] = []
    for gid in order:
        match = next(
            (c for c in canon if _same_box(rect_by_group[c], rect_by_group[gid])),
            None,
        )
        if match is None:
            canon.append(gid)
        else:
            rect_by_group[gid] = rect_by_group[match]
    return rect_by_group


def _same_box(a: FacecamRect, b: FacecamRect) -> bool:
    """Duas caixas que enquadram a mesma cam, dentro da incerteza do encaixe."""
    center_shift = max(
        abs((a.x + a.w / 2) - (b.x + b.w / 2)),
        abs((a.y + a.h / 2) - (b.y + b.h / 2)),
    )
    size_shift = max(abs(a.w - b.w) / max(a.w, b.w), abs(a.h - b.h) / max(a.h, b.h))
    return center_shift <= _SAME_BOX_CENTER and size_shift <= _SAME_BOX_SIZE


def detect_facecam(
    video_path: str,
    start_time: float,
    end_time: float,
    box_aspect: float = _DEFAULT_BOX_ASPECT,
) -> Optional[FacecamRect]:
    """
    Caixa única da facecam no trecho — a da fase mais longa.

    Usada onde só cabe um retângulo (o que a UI mostra e o usuário edita); o
    render usa detect_facecam_phases e acompanha as mudanças.
    """
    phases = detect_facecam_phases(video_path, start_time, end_time, box_aspect)
    if not phases:
        return None
    return max(phases, key=lambda p: p.end - p.start).rect


def _tiles() -> list[tuple[float, float]]:
    """Cantos dos ladrilhos (x0, y0) em frações do frame, com sobreposição."""
    step = 1.0 - _TILE_SPAN
    return [(x, y) for y in (0.0, step) for x in (0.0, step)]


def _detect_faces_per_frame(frames: list[str], cv2, mp) -> list[list[_Obs]]:
    """
    TODOS os rostos de cada frame amostrado, no frame inteiro e por ladrilho.

    Duas correções em relação a guardar só o rosto de maior confiança do frame
    inteiro, que era o que esta função fazia:

    - todos os rostos, porque ficar com o melhor de cada frame entregava a cam
      ao popup de inscrito — enquanto o alerta está na tela o rosto dele ganha
      o frame e o do streamer é jogado fora. Quem decide agora é a persistência
      (ver _cam_track);
    - por ladrilho, porque uma facecam pequena tem um rosto pequeno demais para
      o detector achar no frame inteiro, em qualquer resolução ou confiança.

    Coordenadas voltam sempre em frações do FRAME, não do ladrilho.
    """
    per_frame: list[list[_Obs]] = []
    regions = [(0.0, 0.0, 1.0)] + [(x, y, _TILE_SPAN) for x, y in _tiles()]

    with mp.solutions.face_detection.FaceDetection(
        model_selection=1, min_detection_confidence=0.5
    ) as detector:
        for path in frames:
            img = cv2.imread(path)
            if img is None:
                per_frame.append([])
                continue
            height, width = img.shape[:2]
            found: list[_Obs] = []

            for x0, y0, span in regions:
                px0, py0 = int(x0 * width), int(y0 * height)
                px1, py1 = int((x0 + span) * width), int((y0 + span) * height)
                patch = img[py0:py1, px0:px1]
                if patch.size == 0:
                    continue
                target = _TILE_WIDTH if span < 1.0 else min(_TILE_WIDTH, patch.shape[1])
                if patch.shape[1] != target:
                    scaled_h = max(2, int(patch.shape[0] * target / patch.shape[1]))
                    patch = cv2.resize(patch, (target, scaled_h))

                res = detector.process(cv2.cvtColor(patch, cv2.COLOR_BGR2RGB))
                for det in res.detections or []:
                    b = det.location_data.relative_bounding_box
                    found.append(_Obs(
                        cx=x0 + (b.xmin + b.width / 2) * span,
                        cy=y0 + (b.ymin + b.height / 2) * span,
                        w=max(b.width * span, 1e-3),
                        h=max(b.height * span, 1e-3),
                        score=float(det.score[0]),
                    ))

            per_frame.append(_dedupe(found))
    return per_frame


def _dedupe(found: list[_Obs]) -> list[_Obs]:
    """
    O mesmo rosto visto pelo frame inteiro e por um (ou dois) ladrilhos vira uma
    detecção só — fica a de maior confiança.
    """
    unique: list[_Obs] = []
    for obs in sorted(found, key=lambda o: o.score, reverse=True):
        if all(
            math.dist((obs.cx, obs.cy), (kept.cx, kept.cy)) > _DEDUPE_RADIUS
            for kept in unique
        ):
            unique.append(obs)
    return unique


def _cluster_observations(per_frame: list[list[_Obs]]) -> list[_Cluster]:
    """
    Agrupa os rostos por posição na tela. Cada aglomerado é um rosto recorrente:
    o do streamer na cam, o do popup de inscrito, um personagem do jogo.
    """
    clusters: list[_Cluster] = []
    ordered = sorted(
        ((i, obs) for i, frame in enumerate(per_frame) for obs in frame),
        key=lambda item: item[1].score,
        reverse=True,
    )
    for frame_idx, obs in ordered:
        for cluster in clusters:
            if math.dist((obs.cx, obs.cy), cluster.center()) <= _STABLE_RADIUS:
                cluster.add(frame_idx, obs)
                break
        else:
            new = _Cluster()
            new.add(frame_idx, obs)
            clusters.append(new)
    return clusters


def _cam_track(
    per_frame: list[list[_Obs]], n_frames: int
) -> tuple[Optional[list[Optional[_Obs]]], float, dict[int, list[int]]]:
    """
    Escolhe, em cada frame, qual rosto é a facecam — e devolve a trilha.

    O critério é PERSISTÊNCIA, não confiança nem tamanho: a cam do streamer está
    em quase todo frame do trecho, um popup de inscrito dura alguns segundos.

    Uma cam que MUDA de lugar vira dois aglomerados, e os dois são a cam. O que
    separa esse caso de um segundo rosto qualquer é a CO-OCORRÊNCIA: a cam não
    aparece em dois lugares ao mesmo tempo, então aglomerados que dividem os
    mesmos frames são rostos concorrentes (popup, plateia, jogo) e o menor é
    descartado; aglomerados em janelas de tempo distintas são a mesma cam depois
    de se mexer, e entram na trilha.

    Returns:
        (trilha por frame, confiança, {aglomerado: frames dele}).
        (None, 0.0, {}) se nenhum aglomerado tem presença suficiente.

    O terceiro item é o que permite encaixar UMA caixa por cam: quem já sabe a
    que aglomerado cada frame pertence é esta função, e redescobrir isso depois
    por proximidade de posição criava vários grupos para a mesma cam (o rosto
    oscila dentro dela), cada um com um encaixe ligeiramente diferente.
    """
    clusters = _cluster_observations(per_frame)
    if not clusters:
        logger.info("Facecam: no face detected in sampled frames")
        return None, 0.0, {}

    clusters.sort(key=lambda c: (len(c.frames), c.median_area()), reverse=True)
    primary = clusters[0]
    accepted = [primary]

    for cluster in clusters[1:]:
        if len(cluster.frames) < _CLUSTER_MIN_COVERAGE * n_frames:
            continue
        # Divide frames com uma fase já aceita → é outro rosto, não a cam
        if any(_frame_overlap(cluster, other) > _CLUSTER_OVERLAP for other in accepted):
            continue
        # Rosto de tamanho muito diferente não é o mesmo streamer mais perto
        ratio = cluster.median_area() / max(primary.median_area(), 1e-9)
        if not 1 / _CLUSTER_SIZE_RATIO <= ratio <= _CLUSTER_SIZE_RATIO:
            continue
        accepted.append(cluster)

    covered = set()
    for cluster in accepted:
        covered |= cluster.frames
    confidence = len(covered) / max(n_frames, 1)
    if confidence < _MIN_CONFIDENCE:
        logger.info(
            f"Facecam: face cluster too unstable "
            f"({len(covered)}/{n_frames} frames = {confidence:.0%})"
        )
        return None, 0.0, {}

    track: list[Optional[_Obs]] = [None] * n_frames
    owner: list[Optional[int]] = [None] * n_frames
    for gid, cluster in enumerate(accepted):
        for frame_idx, seen in cluster.by_frame.items():
            best = max(seen, key=lambda o: o.score)
            current = track[frame_idx]
            if current is None or best.score > current.score:
                track[frame_idx] = best
                owner[frame_idx] = gid

    groups: dict[int, list[int]] = {}
    for frame_idx, gid in enumerate(owner):
        if gid is not None:
            groups.setdefault(gid, []).append(frame_idx)

    if len(accepted) > 1:
        logger.info(
            f"Facecam: {len(accepted)} posições distintas da cam ao longo do trecho "
            f"(a cam se moveu); {len(clusters) - len(accepted)} rosto(s) concorrente(s) "
            f"descartado(s)"
        )
    return track, confidence, groups


def _frame_overlap(a: "_Cluster", b: "_Cluster") -> float:
    """Fração dos frames do menor aglomerado que o outro também ocupa."""
    smaller = min(len(a.frames), len(b.frames))
    if smaller == 0:
        return 0.0
    return len(a.frames & b.frames) / smaller


def _group_spans(
    track: list[Optional[_Obs]], groups: dict[int, list[int]]
) -> list[tuple[int, int, int]]:
    """
    Trechos contíguos de mesmo grupo, cobrindo todos os frames.

    A troca vale na primeira amostra do outro grupo, sem exigir confirmação.
    Confirmação faz sentido quando o risco é ruído de detecção — mas o ruído já
    foi filtrado em _cam_track, que só aceita aglomerados persistentes com
    tamanho de cam. Dentro do que sobrou, um frame no outro enquadramento é uma
    troca de plano de verdade.

    Exigir duas amostras seguidas aqui, aliás, era o que mantinha o defeito: com
    plano de ~4s e amostra a cada 1,7s, o POV alternativo aparece em 1 ou 2
    amostras e qualquer frame sem detecção no meio zerava a contagem — o trecho
    inteiro herdava o enquadramento do outro streamer.

    Frame sem rosto não abre trecho novo: a cam continua onde estava e quem
    piscou foi o detector.

    Returns:
        [(primeiro índice, último índice, id do grupo)].
    """
    if not groups:
        return []

    gid_of: list[Optional[int]] = [None] * len(track)
    for gid, indexes in groups.items():
        for i in indexes:
            gid_of[i] = gid

    spans: list[tuple[int, int, int]] = []
    current = next(g for g in gid_of if g is not None)
    start = 0

    for i, gid in enumerate(gid_of):
        if gid is None or gid == current:
            continue
        spans.append((start, i - 1, current))
        start, current = i, gid

    spans.append((start, len(track) - 1, current))
    return spans


def _same_placement(obs: _Obs, anchor: _Obs) -> bool:
    """Mesma posição e mesmo tamanho de rosto = a cam não mexeu."""
    if math.dist((obs.cx, obs.cy), (anchor.cx, anchor.cy)) > _PHASE_MOVE:
        return False
    ratio = (obs.w * obs.h) / max(anchor.w * anchor.h, 1e-9)
    return 1 / _PHASE_ZOOM <= ratio <= _PHASE_ZOOM


def _fit_phase(
    frames: list[str],
    track: list[Optional[_Obs]],
    box_aspect: float,
    confidence: float,
    cv2,
    np,
) -> FacecamRect:
    """Caixa da cam numa fase: encaixe nas bordas usando só os frames dela."""
    seen = [obs for obs in track if obs is not None]
    face_cx = _median([o.cx for o in seen])
    face_cy = _median([o.cy for o in seen])
    face_w = _median([o.w for o in seen])
    face_h = _median([o.h for o in seen])

    # Mapas de borda estática: o que fica igual em todo frame DA FASE é a moldura
    # da cam, não o conteúdo dela nem o do jogo.
    fitted = None
    maps = _edge_maps(frames, cv2, np)
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


def _best_box(lefts, rights, tops, bottoms, frame_w: int, frame_h: int) -> Optional[tuple]:
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

    Caixas grandes demais para ser uma cam são descartadas ANTES da pontuação,
    não depois: assim a melhor caixa plausível ainda é eleita, em vez de o
    encaixe inteiro falhar e cair no palpite pelo rosto.

    Returns:
        (x0, y0, x1, y1, score) em pixels, x1/y1 exclusivos. None se nenhuma
        combinação fecha uma caixa.
    """
    max_w = _MAX_CAM_W * frame_w
    max_h = _MAX_CAM_H * frame_h
    max_area = _MAX_CAM_AREA * frame_w * frame_h

    boxes = []
    for left, q_left in lefts:
        for right, q_right in rights:
            width = right - left
            if width < 16 or width > max_w:
                continue
            for top, q_top in tops:
                for bottom, q_bottom in bottoms:
                    height = bottom - top
                    if height < 16 or height > max_h:
                        continue
                    if width * height > max_area:
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

        found = _best_box(lefts, rights, tops, bottoms, w, h)
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


def gameplay_crop_x(src_w: int, crop_w: int, cam_px) -> int:
    """
    x da fatia de gameplay: centralizada, mas desviando da facecam quando ela
    invade o centro (dá para deslizar até a fatia sair de cima da cam sem
    ultrapassar os limites do frame).

    `cam_px` é uma caixa (x, y, w, h) ou a lista das caixas de todas as fases —
    a fatia é a mesma o clip inteiro, então precisa escapar de TODAS elas. Vale
    testar cada caixa em vez da união: com a cam pulando de um canto para o
    outro, a união cobre a tela toda e não sobraria desvio nenhum, quando na
    verdade o centro está livre nos dois momentos.

    O desvio é da caixa da cam MAIS a folga de dodge_margin().
    """
    limit = src_w - crop_w
    centered = _clamp((src_w - crop_w) // 2, 0, limit)
    if not cam_px:
        return centered

    boxes = [cam_px] if isinstance(cam_px, tuple) else list(cam_px)
    if not boxes:
        return centered

    margin = dodge_margin(src_w)
    spans = [
        (max(0, box[0] - margin), min(src_w, box[0] + box[2] + margin))
        for box in boxes
    ]

    def clears_all(x: int) -> bool:
        return all(x1 <= x or x0 >= x + crop_w for x0, x1 in spans)

    if clears_all(centered):
        return centered

    # Encostar de um lado ou do outro de cada caixa; fica o menor deslocamento
    # que couber no frame e escapar de todas as caixas ao mesmo tempo.
    options = [x for x0, x1 in spans for x in (x1, x0 - crop_w) if 0 <= x <= limit]
    viable = [x for x in options if clears_all(x)]
    if not viable:
        return centered  # não cabe em lugar nenhum: mantém o centro
    return min(viable, key=lambda x: abs(x - centered))


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
