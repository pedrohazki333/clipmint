"""
Leitura do HUD de Rainbow Six Siege.

A análise de viralidade só enxerga a transcrição, e em partida competitiva isso
não basta: a call é tática ("puxa a câmera", "espera abrir o alçapão"), a jogada
acontece na tela e a fala frequentemente comenta algo que o espectador não vê.
Foi assim que um clipe virou 52s do streamer MORTO olhando o placar enquanto
falava de uma troca que já tinha acontecido.

O jogo, porém, escreve o estado na tela. Este módulo lê o pedaço do HUD que
resolve o pior erro: quando o streamer está morto, o R6 mostra "OBSERVANDO
<nome do companheiro>" num canto fixo. Achar essa palavra é suficiente para
saber que aquele trecho não é jogada dele.

Por que template matching e não OCR: a fonte, o tamanho e a posição do HUD são
fixos, então comparar com um recorte de referência separa os casos com folga
enorme (medido numa live real: 0.28 de score sem o texto contra 1.00 com ele) —
sem instalar motor de OCR nem depender de reconhecer letra por letra.
"""

import glob
import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.utils.ffmpeg import run_ffmpeg

logger = logging.getLogger(__name__)

_TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "assets" / "r6_observando.png"

# Recorte onde o HUD escreve "OBSERVANDO", em fração do frame. O jogo desenha
# o HUD em posição fixa; a janela é folgada para absorver variação de escala
# entre streamers, já que o custo de olhar alguns pixels a mais é zero.
_ROI = (0.042, 0.787, 0.208, 0.074)  # x, y, w, h

# Separação medida entre "sem texto" e "com texto" é de 0.28 para 1.00 — 0.75
# fica no meio do vazio, longe dos dois grupos.
_MATCH_THRESHOLD = 0.75

# Uma amostra a cada 2s: morte em Siege dura dezenas de segundos, então não há
# o que ganhar amostrando mais denso, e o custo cresce com a duração do vídeo.
_SAMPLE_INTERVAL = 2.0

# Buraco menor que isto entre duas detecções é a mesma morte (o texto some por
# um frame em transição de câmera).
_GAP_TOLERANCE = 6.0


@dataclass
class DeadWindow:
    """Intervalo, em segundos do vídeo, em que o streamer está morto."""

    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start

    def overlap(self, start: float, end: float) -> float:
        """Segundos desta janela que caem dentro de [start, end]."""
        return max(0.0, min(self.end, end) - max(self.start, start))


def template_available() -> bool:
    """False quando o recorte de referência não está instalado."""
    return _TEMPLATE_PATH.is_file()


def dead_overlap(windows: list[DeadWindow], start: float, end: float) -> float:
    """Fração de [start, end] em que o streamer está morto (0.0–1.0)."""
    span = end - start
    if span <= 0:
        return 0.0
    return min(1.0, sum(w.overlap(start, end) for w in windows) / span)


def _windows_from_hits(hits: list[float], interval: float) -> list[DeadWindow]:
    """Agrupa amostras positivas em intervalos contínuos."""
    windows: list[DeadWindow] = []
    for t in hits:
        if windows and t - windows[-1].end <= _GAP_TOLERANCE:
            windows[-1].end = t + interval
        else:
            windows.append(DeadWindow(start=t, end=t + interval))
    return windows


async def find_dead_windows(
    video_path: str,
    duration: float,
    start_time: float = 0.0,
    interval: float = _SAMPLE_INTERVAL,
) -> list[DeadWindow]:
    """
    Intervalos em que o streamer está morto (assistindo um companheiro).

    Bloqueante em CPU na parte do OpenCV — chamar via to_thread quando estiver
    num caminho async quente. Lista vazia significa "não deu para saber": sem
    template, sem frames ou biblioteca ausente, o pipeline segue como antes em
    vez de descartar clipe por engano.
    """
    if not template_available():
        logger.warning("R6 HUD: template ausente — detecção de morte desligada")
        return []

    try:
        import cv2
    except ImportError:  # pragma: no cover - ambiente sem OpenCV
        logger.warning("R6 HUD: OpenCV ausente — detecção de morte desligada")
        return []

    x, y, w, h = _ROI
    with tempfile.TemporaryDirectory() as tmpdir:
        pattern = os.path.join(tmpdir, "hud_%05d.png")
        await run_ffmpeg(
            "-ss", f"{start_time:.3f}", "-t", f"{duration:.3f}", "-i", video_path,
            "-vf",
            f"fps=1/{interval:.3f},crop=iw*{w}:ih*{h}:iw*{x}:ih*{y}",
            pattern,
            description=f"Amostra do HUD de R6 ({duration:.0f}s)",
        )
        frames = sorted(glob.glob(os.path.join(tmpdir, "hud_*.png")))
        if not frames:
            logger.warning("R6 HUD: nenhum frame extraído")
            return []

        template = cv2.imread(str(_TEMPLATE_PATH), cv2.IMREAD_GRAYSCALE)
        hits: list[float] = []
        for index, path in enumerate(frames):
            frame = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
            if frame is None or frame.shape[0] < template.shape[0]:
                continue
            score = cv2.matchTemplate(frame, template, cv2.TM_CCOEFF_NORMED).max()
            if score >= _MATCH_THRESHOLD:
                hits.append(start_time + index * interval)

    windows = _windows_from_hits(hits, interval)
    total = sum(win.duration for win in windows)
    logger.info(
        f"R6 HUD: streamer morto em {len(windows)} janela(s), "
        f"{total:.0f}s de {duration:.0f}s ({100 * total / max(duration, 1):.0f}%)"
    )
    return windows
