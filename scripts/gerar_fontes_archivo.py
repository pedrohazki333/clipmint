"""
Gera as versões fixas da Archivo que o render usa.

    python scripts/gerar_fontes_archivo.py <Archivo[wdth,wght].ttf>

A Archivo é variável, e o libass não escolhe eixos: usa a fonte como ela está no
arquivo. Por isso cada peso e largura da especificação (docs/LAYOUTS_V2.md) vira um
arquivo com um nome de família próprio, que é como o ASS pede a fonte.

A saída fica em `backend/app/assets/fonts/`, junto com a licença OFL, e o startup copia
para `storage/branding/fonts/`. O fonttools só é necessário para rodar isto, e não para
o sistema funcionar. A fonte original está em github.com/google/fonts (ofl/archivo).
"""

import sys
from pathlib import Path

from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

_DESTINO = Path(__file__).resolve().parents[1] / "backend" / "app" / "assets" / "fonts"

#: família → (peso, largura em %). Títulos: 900 a 75%. Legenda: 800 a 92%. @: 700 a 100%.
_VERSOES = {
    "Archivo ClipMint Titulo": (900, 75),
    "Archivo ClipMint Legenda": (800, 92),
    "Archivo ClipMint Arroba": (700, 100),
}


def _gerar(origem: str, familia: str, peso: int, largura: int) -> Path:
    fonte = instancer.instantiateVariableFont(TTFont(origem), {"wght": peso, "wdth": largura})
    for registro in fonte["name"].names:
        if registro.nameID in (1, 4, 16):
            registro.string = familia
        elif registro.nameID in (2, 17):
            registro.string = "Regular"
        elif registro.nameID == 6:
            registro.string = familia.replace(" ", "")
    # O peso já está desenhado nos contornos. Declarar "bold" faria o libass engordar
    # de novo o que já é 900.
    fonte["OS/2"].usWeightClass = 400
    fonte["OS/2"].fsSelection = (fonte["OS/2"].fsSelection & ~0x21) | 0x40
    fonte["head"].macStyle = 0

    destino = _DESTINO / f"{familia.replace(' ', '')}.ttf"
    fonte.save(destino)
    return destino


def main() -> None:
    if len(sys.argv) != 2:
        print(__doc__.strip(), file=sys.stderr)
        raise SystemExit(2)
    _DESTINO.mkdir(parents=True, exist_ok=True)
    for familia, (peso, largura) in _VERSOES.items():
        caminho = _gerar(sys.argv[1], familia, peso, largura)
        print(f"{caminho.name}: {caminho.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
