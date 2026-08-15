"""
Presets de marca por nicho.

Cada conta (podcast e gameplay) tem a própria logo, cores de banner e estilo de
faixa. Antes tudo isso era global e trocar de nicho exigia reconfigurar a marca
a cada geração — o que, na prática, significa postar com a identidade errada
quando alguém esquece.

Os arquivos ficam em `storage/branding/<source_type>/`. O layout antigo, com os
arquivos soltos em `storage/branding/`, é migrado para os dois nichos na
primeira execução: a marca que já estava configurada continua valendo nos dois
lados até o usuário diferenciá-los.
"""

import logging
import shutil
from pathlib import Path

from app.config import settings
from app.prompts.viral_analysis import DEFAULT_SOURCE_TYPE, SOURCE_TYPES

logger = logging.getLogger(__name__)

# Nome dos arquivos de preset, iguais dentro de cada nicho.
WATERMARK_FILE = "watermark.png"
# Arte queimada no clipe inteiro. É um arquivo separado do WATERMARK_FILE de
# propósito: aquele cobre QR code detectado na fonte e é escolhido para tapar
# uma área, este é a assinatura da conta e é escolhido para ser visto. Quem
# quiser a mesma imagem nos dois sobe duas vezes; quem não subir esta não ganha
# marca nenhuma no clipe, que é o que mantém as outras contas intactas.
CLIP_WATERMARK_FILE = "clip_watermark.png"
BANNER_COLORS_FILE = "banner_colors.json"
BAR_STYLE_FILE = "bar_style.json"

# Só o que existia no layout global antigo — a marca do clipe nasceu já por
# nicho, então não há nada dela para migrar.
_PRESET_FILES = (WATERMARK_FILE, BANNER_COLORS_FILE, BAR_STYLE_FILE)


def normalize_source(source_type: str | None) -> str:
    """Nicho válido, caindo no default quando vier vazio ou desconhecido."""
    value = (source_type or DEFAULT_SOURCE_TYPE).lower()
    return value if value in SOURCE_TYPES else DEFAULT_SOURCE_TYPE


def branding_dir(source_type: str | None) -> Path:
    """Pasta de presets do nicho, criada sob demanda."""
    path = settings.branding_dir / normalize_source(source_type)
    path.mkdir(parents=True, exist_ok=True)
    return path


def preset_path(source_type: str | None, filename: str) -> Path:
    return branding_dir(source_type) / filename


def migrate_legacy_branding() -> None:
    """
    Copia a marca global antiga para dentro dos dois nichos.

    Idempotente e não-destrutiva: só copia quando o arquivo do nicho ainda não
    existe, e o arquivo antigo é preservado (nunca movido) para não perder a
    configuração se a versão antiga voltar a rodar.
    """
    legacy_dir = settings.branding_dir
    if not legacy_dir.exists():
        return

    for filename in _PRESET_FILES:
        legacy_file = legacy_dir / filename
        if not legacy_file.is_file():
            continue
        for source in SOURCE_TYPES:
            target = branding_dir(source) / filename
            if target.exists():
                continue
            shutil.copy2(legacy_file, target)
            logger.info(f"Branding migrado: {filename} → {source}/")
