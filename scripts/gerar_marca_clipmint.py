"""
Gera a marca d'água padrão do ClipMint.

É um espaço reservado: mostra onde a marca aparece e some assim que a pessoa
subir a dela. Desenhada em código, e não commitada como binário opaco, para
quem vier depois poder ver de onde saiu cada pixel.
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

MINT = (0x34, 0xD3, 0x99, 255)
BASE = (0x0B, 0x0F, 0x0D, 255)
W, H = 420, 120

def fonte(tamanho: int):
    for caminho in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
    ):
        if Path(caminho).exists():
            return ImageFont.truetype(caminho, tamanho)
    return ImageFont.load_default()

img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# Pílula escura com o verde do produto — legível sobre vídeo claro ou escuro.
raio = H // 2
d.rounded_rectangle([0, 0, W - 1, H - 1], radius=raio, fill=(0x12, 0x17, 0x14, 235))
d.rounded_rectangle([0, 0, W - 1, H - 1], radius=raio, outline=MINT, width=3)

# Marca de "play" à esquerda: o triângulo é o vocabulário do assunto (vídeo).
cx, cy, r = 66, H // 2, 26
d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=MINT)
d.polygon([(cx - 8, cy - 13), (cx - 8, cy + 13), (cx + 14, cy)], fill=BASE)

f = fonte(46)
texto = "ClipMint"
caixa = d.textbbox((0, 0), texto, font=f)
d.text((110, cy - (caixa[3] - caixa[1]) / 2 - caixa[1]), texto, font=f, fill=MINT)

destino = Path(__file__).resolve().parents[1] / "frontend/public/marca-clipmint.png"
destino.parent.mkdir(parents=True, exist_ok=True)
img.save(destino, format="PNG")
print(f"{destino} — {img.size[0]}x{img.size[1]}")
