"""
Onde a interface do TikTok cobre o vídeo, no quadro de 1080x1920.

Topo: nome da aba. Coluna direita: curtir, comentar, compartilhar. Base: descrição do
vídeo. Texto do clipe caindo em uma dessas áreas fica escondido justo onde mais precisa
ser lido. Isto é conferido em teste e registrado no render: um título longo não vira
erro, mas não pode passar sem ninguém saber.
"""

from typing import NamedTuple

CANVAS_W, CANVAS_H = 1080, 1920
TOP = 150
BOTTOM = 400
RIGHT_COLUMN_W = 150
RIGHT_COLUMN_Y = (800, 1500)

#: A borda direita de quem cruza a coluna da direita.
RIGHT_LIMIT_X = CANVAS_W - RIGHT_COLUMN_W


class Rect(NamedTuple):
    x: float
    y: float
    w: float
    h: float


def unsafe_areas(rect: Rect) -> list[str]:
    """Quais áreas seguras este retângulo invade. Lista vazia = está tudo certo."""
    x, y, w, h = rect
    areas = []
    if y < TOP:
        areas.append("topo")
    if y + h > CANVAS_H - BOTTOM:
        areas.append("base")
    cruza_a_faixa = y < RIGHT_COLUMN_Y[1] and y + h > RIGHT_COLUMN_Y[0]
    if cruza_a_faixa and x + w > RIGHT_LIMIT_X:
        areas.append("coluna da direita")
    return areas
