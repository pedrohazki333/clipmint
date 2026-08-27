"""
Os padrões de marca, e a paridade entre quem desenha o preview e quem desenha
o vídeo.

Os defaults vivem em dois lugares: `app/services/layout.py` (o que o FFmpeg
queima no clipe) e `frontend/src/lib/branding.ts` (o que o painel de Marca
mostra antes de qualquer configuração). Divergirem não quebra nada — é pior:
a tela promete uma cor e o vídeo sai com outra, e ninguém descobre até assistir.
"""

import re
from pathlib import Path

from app.services.layout import (
    BANNER_DEFAULT_BG_HEX,
    BANNER_DEFAULT_TEXT_HEX,
    BAR_DEFAULT_BG_HEX,
    BAR_DEFAULT_NAME,
    BAR_DEFAULT_TEXT_HEX,
)

_TS = Path(__file__).resolve().parents[2] / "frontend/src/lib/branding.ts"


def _constantes_do_frontend() -> dict[str, str]:
    fonte = _TS.read_text(encoding="utf-8")
    return dict(re.findall(r'export const (\w+) = "([^"]+)";', fonte))


def test_frontend_e_backend_concordam():
    do_front = _constantes_do_frontend()
    assert do_front == {
        "BAR_DEFAULT_BG": BAR_DEFAULT_BG_HEX,
        "BAR_DEFAULT_TEXT": BAR_DEFAULT_TEXT_HEX,
        "BAR_DEFAULT_NAME": BAR_DEFAULT_NAME,
        "BANNER_DEFAULT_BG": BANNER_DEFAULT_BG_HEX,
        "BANNER_DEFAULT_TEXT": BANNER_DEFAULT_TEXT_HEX,
    }


def test_a_faixa_nunca_sai_sem_nome():
    """
    O padrão vazio é o bug que este nome existe para fechar.

    Com ele vazio, o modo streamer caía no canal do vídeo de ORIGEM e o clipe
    saía assinado por quem gravou — a conta errada, em todo clipe de quem nunca
    abriu o painel de Marca.
    """
    assert BAR_DEFAULT_NAME.strip()
    assert BAR_DEFAULT_NAME.startswith("@")


def test_as_cores_padrao_sao_hex_completo():
    """parse_hex_color só aceita #RRGGBB; um padrão inválido cairia no fallback."""
    for cor in (
        BAR_DEFAULT_BG_HEX,
        BAR_DEFAULT_TEXT_HEX,
        BANNER_DEFAULT_BG_HEX,
        BANNER_DEFAULT_TEXT_HEX,
    ):
        assert re.fullmatch(r"#[0-9A-F]{6}", cor.upper()), cor
