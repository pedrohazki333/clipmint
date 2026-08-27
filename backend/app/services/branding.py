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
import re
import shutil
from pathlib import Path

from app.config import settings
from app.features import allowed_source_types, public_build
from app.prompts.viral_analysis import DEFAULT_SOURCE_TYPE

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
    """Nicho válido, caindo no default quando vier vazio ou desconhecido.

    A lista de nichos válidos é a do build (ver app/features.py): o público não
    pode criar storage/branding/siege/ nem escrever nele.
    """
    value = (source_type or DEFAULT_SOURCE_TYPE).lower()
    return value if value in allowed_source_types() else DEFAULT_SOURCE_TYPE


def branding_dir(source_type: str | None) -> Path:
    """Pasta de presets do nicho, criada sob demanda."""
    path = settings.branding_dir / normalize_source(source_type)
    path.mkdir(parents=True, exist_ok=True)
    return path


#: Os padrões do PRODUTO — a marca do próprio ClipMint.
#: Começa com "_" para não colidir com nicho nenhum: os nichos ocupam este
#: mesmo nível do diretório e são validados contra `allowed_source_types()`,
#: que nunca devolve um nome começando com underscore.
_CLIPMINT_SUBDIR = "_clipmint"


def clipmint_defaults_dir() -> Path:
    """Pasta dos presets do próprio ClipMint, criada sob demanda.

    É o que um perfil sem marca própria usa no build público. Arquivo que não
    existir aqui simplesmente não vira preset — o clipe sai sem marca d'água,
    com as cores padrão de `layout.py`, e não com a marca de outra pessoa.
    """
    path = settings.branding_dir / _CLIPMINT_SUBDIR
    path.mkdir(parents=True, exist_ok=True)
    return path


#: Onde ficam os presets de cada perfil, separados dos do nicho.
_PROFILES_SUBDIR = "profiles"

#: Um id de perfil: 32 hexadecimais (uuid4 sem hífens). Validado antes de virar
#: caminho — este valor chega de um parâmetro de request, e um `../` ali sairia
#: do diretório de branding.
_ID_DE_PERFIL = re.compile(r"^[0-9a-f]{32}$")


def profile_dir(profile_id: str | None) -> Path | None:
    """Pasta de presets de um perfil, ou None se o id não for de um perfil.

    Não cria o diretório: quem cria é quem escreve (ver `ensure_profile_dir`).
    Ler não deve deixar pasta vazia para trás em todo clipe renderizado.
    """
    if not profile_id or not _ID_DE_PERFIL.match(profile_id):
        return None
    return settings.branding_dir / _PROFILES_SUBDIR / profile_id


def ensure_profile_dir(profile_id: str) -> Path:
    """Pasta de presets do perfil, criada sob demanda. Levanta se o id for inválido."""
    path = profile_dir(profile_id)
    if path is None:
        raise ValueError(f"Id de perfil inválido: {profile_id!r}")
    path.mkdir(parents=True, exist_ok=True)
    return path


def preset_path(
    source_type: str | None, filename: str, profile_id: str | None = None
) -> Path:
    """
    Onde está este preset, para este perfil.

    Precedência: o arquivo do PERFIL, se existir; senão o do NICHO. É essa
    queda que mantém tudo funcionando como antes — perfil sem logo própria usa
    a do nicho, e job antigo (sem perfil) nem chega a olhar a pasta de perfil.

    O motivo de existir: os presets eram gravados só por nicho, num diretório
    compartilhado. Num produto multiusuário isso faz a logo de um aparecer no
    clipe do outro — e dois perfis da MESMA rubrica ("HZ Pod Clips" e "Cortes de
    Entrevistas", ambos podcast) não teriam como ter marcas diferentes.
    """
    do_perfil = profile_dir(profile_id)
    if do_perfil is not None:
        candidato = do_perfil / filename
        if candidato.exists():
            return candidato
    if public_build():
        # No público a queda NÃO pode ser no nicho: aquela pasta é da instalação
        # inteira e guarda a marca de quem administra. Um perfil recém-criado
        # herdava a logo, as cores e o @ do dono — a pessoa gerava o primeiro
        # clipe assinado por outro. Aqui a queda é a marca do próprio produto.
        return clipmint_defaults_dir() / filename
    return branding_dir(source_type) / filename


#: Presets que o PRODUTO traz de fábrica. Ficam no repositório (storage/ é
#: ignorado pelo git), e são copiados para dentro do storage no startup.
_ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets" / "branding"


def seed_clipmint_defaults() -> None:
    """
    Põe os presets de fábrica no storage, se faltarem.

    Idempotente e não-destrutiva: arquivo que já existe não é tocado, então
    trocar a marca do produto é substituir o asset e apagar a cópia — e nunca
    sobrescreve o que alguém ajustou.

    Sem isto, `clipmint_defaults_dir()` fica vazia numa instalação nova e o
    perfil sem marca própria sai sem marca nenhuma. Que é melhor do que sair
    com a marca do dono da instalação (era o que acontecia), mas pior do que
    sair com a do ClipMint.
    """
    if not _ASSETS_DIR.is_dir():
        return
    destino = clipmint_defaults_dir()
    for arquivo in sorted(_ASSETS_DIR.iterdir()):
        if not arquivo.is_file():
            continue
        alvo = destino / arquivo.name
        if alvo.exists():
            continue
        shutil.copy2(arquivo, alvo)
        logger.info(f"Preset de fábrica instalado: {alvo.name}")


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
        for source in allowed_source_types():
            target = branding_dir(source) / filename
            if target.exists():
                continue
            shutil.copy2(legacy_file, target)
            logger.info(f"Branding migrado: {filename} → {source}/")
