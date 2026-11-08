"""
Qual quadro vira a capa do layout B.

A capa é uma prévia: promete o momento de reação mais forte que acontece DENTRO do
clipe. A regra antiga pegava o rosto mais expressivo falando, o que num podcast dá quem
já está na tela embaixo, de boca aberta porque está no meio de uma palavra.

Três coisas não existiam prontas, e foram medidas num podcast real:

  - **Momento alto.** `audio_events` marca buracos de 3s ou mais sem fala, e o vídeo não
    tinha nenhum: a risada acontece com alguém falando por cima. Por isso aqui são picos
    de 1s acima do nível de fala, onde a risada de 198s medida dá +8 dB.
  - **Quem é quem.** O MediaPipe acha rosto, mas não reconhece pessoa. Só que num podcast
    cada um tem a própria câmera fixa, e o fundo identifica a câmera: fita amarela, cortina
    azul, parede. "Rosto diferente" vira "câmera diferente da que mais aparece no clipe",
    sem API nenhuma e com o mesmo resultado em toda execução.
  - **Expressão.** Boca aberta sozinha não serve: o microfone cobre a boca de quem fala
    perto dele. A nota soma abertura e largura do sorriso, medidas contra o tamanho do rosto.

A escolha em si (`choose_cover`) não abre vídeo nenhum, e é o que dá para testar a sério.
"""

import logging
import math
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from app.services.layout import _brand_cover, _crop_to_cover, _transform_regions

logger = logging.getLogger(__name__)

# Amostragem: dois quadros por segundo acham a reação sem pagar o vídeo inteiro.
_SAMPLE_FPS = 2
_SAMPLE_WIDTH = 640
# Só as melhores vão para o FaceMesh, que custa bem mais que a detecção de rosto.
_MAX_MESH_FRAMES = 24
_SCENE_THRESHOLD = 0.35

# Dois planos são da mesma câmera se o histograma de cor do fundo bater a este ponto.
_SAME_CAMERA = 0.75

# Pico de 1s acima do nível de fala que conta como momento alto, e quanto em volta dele
# olhar: a reação aparece logo depois do barulho, e às vezes logo antes.
LOUD_MIN_DB = 4.0
_LOUD_BEFORE, _LOUD_AFTER = 1.0, 2.0

# Abaixo disto é um quadro neutro de fala, que a regra manda nunca usar se houver outro.
MIN_EXPRESSION = 0.32

_RMS_STEP = 0.05


@dataclass
class FrameInfo:
    """O que se sabe sobre um quadro amostrado."""

    time: float
    camera: int
    has_face: bool = False
    cx: float = 0.5
    cy: float = 0.45
    area: float = 0.0
    expression: float = 0.0
    loud: bool = False
    path: Optional[str] = field(default=None, compare=False)


@dataclass
class CoverChoice:
    frame: FrameInfo
    rule: str


#: As regras, na ordem em que valem. O nome é o que vai para o log.
RULE_OTHER_LOUD = "reacao de outra pessoa em momento alto"
RULE_OTHER = "reacao de outra pessoa"
RULE_SPEAKER = "expressao mais forte de quem fala"
RULE_NEUTRAL = "sem reacao no clipe: o rosto mais expressivo que havia"
RULE_NO_FACE = "sem rosto no clipe: quadro do meio"


def main_camera(frames: list[FrameInfo]) -> Optional[int]:
    """A câmera que mais aparece no clipe, tratada como a de quem fala embaixo."""
    contagem: dict[int, int] = {}
    for frame in frames:
        contagem[frame.camera] = contagem.get(frame.camera, 0) + 1
    return max(contagem, key=contagem.get) if contagem else None


def choose_cover(frames: list[FrameInfo]) -> Optional[CoverChoice]:
    """Aplica as regras, na ordem da especificação. None só sem quadro nenhum."""
    if not frames:
        return None

    com_rosto = [f for f in frames if f.has_face]
    if not com_rosto:
        return CoverChoice(frames[len(frames) // 2], RULE_NO_FACE)

    principal = main_camera(frames)
    fortes = [f for f in com_rosto if f.expression >= MIN_EXPRESSION]

    def melhor(candidatos: list[FrameInfo]) -> FrameInfo:
        return max(candidatos, key=lambda f: (f.expression, f.area))

    outros = [f for f in fortes if f.camera != principal]
    outros_altos = [f for f in outros if f.loud]
    if outros_altos:
        return CoverChoice(melhor(outros_altos), RULE_OTHER_LOUD)
    if outros:
        return CoverChoice(melhor(outros), RULE_OTHER)
    if fortes:
        # Momento alto vence quando empata, mas não troca uma reação clara por um pico
        # de voz com cara neutra.
        altos = [f for f in fortes if f.loud]
        return CoverChoice(melhor(altos or fortes), RULE_SPEAKER)
    return CoverChoice(melhor(com_rosto), RULE_NEUTRAL)


# ─── Momentos altos ────────────────────────────────────────────────────────────

def loud_moments(levels: np.ndarray, step: float = _RMS_STEP, top: int = 6) -> list[float]:
    """Os instantes dos picos de 1s acima do nível de fala, do mais alto ao mais baixo."""
    janela = int(1 / step)
    if len(levels) < janela:
        return []
    audiveis = levels[levels > -70]
    if not len(audiveis):
        return []
    fala = float(np.median(audiveis))
    media = np.convolve(levels, np.ones(janela) / janela, mode="valid")

    picos: list[float] = []
    for indice in np.argsort(media)[::-1]:
        if media[indice] - fala < LOUD_MIN_DB or len(picos) >= top:
            break
        t = (int(indice) + janela / 2) * step
        if all(abs(t - p) > 2.0 for p in picos):
            picos.append(t)
    return picos


def _audio_levels(video_path: str, start: float, duration: float) -> np.ndarray:
    """RMS em blocos de 50ms do trecho. Vazio sem áudio: a capa segue só pelo rosto."""
    rate = 16000
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", video_path,
         "-vn", "-ac", "1", "-ar", str(rate), "-f", "s16le", "-"],
        capture_output=True, timeout=300,
    )
    if proc.returncode != 0 or not proc.stdout:
        return np.empty(0)
    amostras = np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32) / 32768.0
    bloco = int(rate * _RMS_STEP)
    inteiros = len(amostras) // bloco
    if not inteiros:
        return np.empty(0)
    blocos = amostras[: inteiros * bloco].reshape(-1, bloco)
    return 20 * np.log10(np.maximum(np.sqrt((blocos**2).mean(axis=1)), 1e-6))


# ─── Câmeras ───────────────────────────────────────────────────────────────────

def color_signature(image_bgr) -> np.ndarray:
    """
    O histograma de matiz e saturação das laterais do quadro.

    Laterais, e não o quadro inteiro: quem fala ocupa o centro e muda de posição e de
    gesto a cada segundo, e o que identifica a câmera é o cenário atrás.
    """
    import cv2

    largura = image_bgr.shape[1]
    margem = max(1, largura // 4)
    laterais = np.hstack((image_bgr[:, :margem], image_bgr[:, -margem:]))
    hsv = cv2.cvtColor(laterais, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, [18, 8], [0, 180, 0, 256])
    cv2.normalize(hist, hist)
    return hist


def camera_references(signatures: list[np.ndarray]) -> list[np.ndarray]:
    """Uma assinatura por câmera, tiradas dos planos: cada plano parecido com um já visto
    é a mesma câmera, e o primeiro de cada uma vira a referência."""
    import cv2

    referencias: list[np.ndarray] = []
    for assinatura in signatures:
        if not any(
            cv2.compareHist(ref, assinatura, cv2.HISTCMP_CORREL) >= _SAME_CAMERA
            for ref in referencias
        ):
            referencias.append(assinatura)
    return referencias


def nearest_camera(signature: np.ndarray, references: list[np.ndarray]) -> int:
    """
    A câmera deste quadro, olhando o próprio quadro.

    Herdar do plano errava perto da emenda: a troca cai entre duas amostras, e o quadro
    de uma pessoa saía rotulado com a câmera da outra. Foi o que apareceu nos clipes
    reais, e aqui isso significaria chamar de "outra pessoa" quem já está embaixo.
    """
    import cv2

    return max(
        range(len(references)),
        key=lambda i: cv2.compareHist(references[i], signature, cv2.HISTCMP_CORREL),
    )


# ─── Expressão ─────────────────────────────────────────────────────────────────

def expression_score(landmarks) -> float:
    """
    Abertura da boca mais largura do sorriso, as duas relativas ao rosto.

    A largura entre os cantos da boca é medida contra a distância entre os olhos, que não
    muda com a expressão: num sorriso ela cresce mesmo de boca fechada, e é o que pega uma
    reação com o microfone na frente.
    """

    def ponto(i: int) -> tuple[float, float]:
        return landmarks[i].x, landmarks[i].y

    # 13/14 lábios internos, 61/291 cantos da boca, 33/263 cantos externos dos olhos.
    boca = math.dist(ponto(61), ponto(291))
    if boca <= 0:
        return 0.0
    abertura = math.dist(ponto(13), ponto(14)) / boca
    olhos = math.dist(ponto(33), ponto(263))
    sorriso = max(0.0, boca / olhos - 0.55) if olhos > 0 else 0.0
    return abertura + sorriso


def _sample_frames(video_path: str, start: float, duration: float, pasta: str) -> list[tuple[float, str]]:
    padrao = os.path.join(pasta, "c_%05d.jpg")
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", video_path,
         "-vf", f"fps={_SAMPLE_FPS},scale={_SAMPLE_WIDTH}:-2", "-q:v", "3", padrao],
        capture_output=True, timeout=300,
    )
    arquivos = sorted(f for f in os.listdir(pasta) if f.startswith("c_"))
    return [(indice / _SAMPLE_FPS, os.path.join(pasta, nome)) for indice, nome in enumerate(arquivos)]


def _scene_cuts(video_path: str, start: float, duration: float) -> list[float]:
    import re

    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", video_path,
         "-vf", f"scale=320:-2,select='gt(scene,{_SCENE_THRESHOLD})',showinfo", "-an", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
    )
    return [float(t) for t in re.findall(r"pts_time:([\d.]+)", proc.stderr)]


def analyze_clip(video_path: str, start: float, end: float, pasta: str) -> list[FrameInfo]:
    """Olha o clipe: câmeras, rostos, momentos altos e, nos melhores quadros, expressão."""
    import cv2
    import mediapipe as mp

    duracao = max(end - start, 1.0)
    amostras = _sample_frames(video_path, start, duracao, pasta)
    if not amostras:
        return []

    # Uma câmera por plano, e não por quadro: dentro de um plano ela não muda, e assim o
    # gesto de alguém passando na frente do fundo não vira uma câmera nova.
    limites = [0.0, *_scene_cuts(video_path, start, duracao), duracao + 1]
    assinaturas = []
    for inicio, fim in zip(limites, limites[1:]):
        meio = (inicio + min(fim, duracao)) / 2
        indice = min(int(meio * _SAMPLE_FPS), len(amostras) - 1)
        imagem = cv2.imread(amostras[indice][1])
        assinaturas.append(color_signature(imagem) if imagem is not None else np.zeros((18, 8), np.float32))
    referencias = camera_references(assinaturas)

    picos = loud_moments(_audio_levels(video_path, start, duracao))

    quadros: list[FrameInfo] = []
    with mp.solutions.face_detection.FaceDetection(
        model_selection=1, min_detection_confidence=0.5
    ) as detector:
        for t, caminho in amostras:
            quadro = FrameInfo(
                time=t,
                camera=0,
                loud=any(p - _LOUD_BEFORE <= t <= p + _LOUD_AFTER for p in picos),
                path=caminho,
            )
            imagem = cv2.imread(caminho)
            if imagem is not None:
                quadro.camera = nearest_camera(color_signature(imagem), referencias)
                resultado = detector.process(cv2.cvtColor(imagem, cv2.COLOR_BGR2RGB))
                if resultado.detections:
                    melhor = max(resultado.detections, key=lambda d: d.score[0])
                    caixa = melhor.location_data.relative_bounding_box
                    quadro.has_face = True
                    quadro.cx = min(1.0, max(0.0, caixa.xmin + caixa.width / 2))
                    quadro.cy = min(1.0, max(0.0, caixa.ymin + caixa.height / 2))
                    quadro.area = max(0.0, caixa.width * caixa.height)
            quadros.append(quadro)

    com_rosto = [q for q in quadros if q.has_face]
    # O FaceMesh é o caro. Vão primeiro os quadros de momentos altos e de outras câmeras,
    # que são os que as regras preferem, depois os maiores rostos, sem deixar uma câmera
    # fora só porque aparece menos.
    principal = main_camera(quadros)
    fila = sorted(
        com_rosto,
        key=lambda q: (q.camera != principal, q.loud, q.area),
        reverse=True,
    )[:_MAX_MESH_FRAMES]
    with mp.solutions.face_mesh.FaceMesh(
        static_image_mode=True, max_num_faces=1, min_detection_confidence=0.5
    ) as malha:
        for quadro in fila:
            imagem = cv2.imread(quadro.path)
            if imagem is None:
                continue
            resultado = malha.process(cv2.cvtColor(imagem, cv2.COLOR_BGR2RGB))
            if resultado.multi_face_landmarks:
                quadro.expression = expression_score(resultado.multi_face_landmarks[0].landmark)
    return quadros


def generate_reaction_cover(
    video_path: str,
    start: float,
    end: float,
    output_path: str,
    width: int,
    height: int,
    watermark_path: Optional[str] = None,
    qr_regions: Optional[list] = None,
    static_regions: Optional[list] = None,
) -> str:
    """Escolhe o quadro, recorta no rosto e aplica a marca. Devolve a regra que decidiu."""
    with tempfile.TemporaryDirectory() as pasta:
        escolha = choose_cover(analyze_clip(video_path, start, end, pasta))
        if escolha is None:
            raise RuntimeError(f"Could not extract cover frames from {video_path}")

        # A análise olha quadros pequenos; a capa sai do quadro inteiro.
        quadro = os.path.join(pasta, "capa.png")
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-ss", f"{start + escolha.frame.time:.3f}", "-i", video_path,
             "-frames:v", "1", quadro],
            capture_output=True, timeout=120,
        )
        if not os.path.exists(quadro):
            raise RuntimeError(f"Could not extract cover frames from {video_path}")
        caixa = _crop_to_cover(quadro, escolha.frame.cx, escolha.frame.cy, width, height, output_path)

    _brand_cover(
        output_path,
        watermark_path,
        _transform_regions(qr_regions or [], caixa, width, height),
        _transform_regions(static_regions or [], caixa, width, height),
    )
    logger.info(
        f"Capa: {escolha.rule} (em {escolha.frame.time:.1f}s do clipe, câmera "
        f"{escolha.frame.camera}, expressão {escolha.frame.expression:.2f})"
    )
    return escolha.rule
