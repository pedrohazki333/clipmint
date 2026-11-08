"""
O estilo do clipe: um esquema só, validado aqui, guardado no perfil.

O visual estava espalhado em `banner_colors.json`, `bar_style.json`, nos defaults
do perfil e em constantes do render. Agora a resposta para "como este clipe deve
parecer?" tem um lugar só. Layout e modo de legenda continuam nas colunas que já
existiam no perfil, porque a criação de job depende delas, e a API os apresenta
junto do resto: cada dado fica em um lugar, e quem pergunta vê tudo.

O job guarda uma CÓPIA na criação. É a mesma regra do `source_type` em `Profile`:
mudar o perfil afeta os próximos jobs, nunca reescreve o passado.

Contraste é regra, e não sugestão: um título ilegível é um clipe perdido, e a cor
livre deixa alguém escolher um. Mede-se contra o fundo que o perfil usa de verdade,
e não contra um preto fixo. O azul com letra amarela de uma página é a identidade
dela, e passa. Azul sobre preto não passa.
"""

import json
import logging
import re
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.services.branding import BANNER_COLORS_FILE, BAR_STYLE_FILE, preset_path
from app.services.layout import BAR_FONTS

logger = logging.getLogger(__name__)

DEFAULT_BRAND = "#FD375C"
#: Fundo do título e cor do texto dentro da caixa da legenda.
INK = "#0B0B0C"
#: Contorno da legenda no estilo "cor".
OUTLINE = "#000000"
WHITE = "#FFFFFF"
#: A paleta oferecida; qualquer outra cor continua valendo se passar no contraste.
PALETTE = {
    "rosa": "#FD375C",
    "amarelo": "#FFD23F",
    "ciano": "#3EC8FF",
    "verde": "#9DFF4F",
}
MIN_CONTRAST = 4.5

DEFAULT_FONT = "archivo"
FONT_KEYS: tuple[str, ...] = (DEFAULT_FONT, *BAR_FONTS)

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def contrast_ratio(a: str, b: str) -> float:
    """Razão de contraste do WCAG entre duas cores #RRGGBB."""

    def luminance(color: str) -> float:
        channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        r, g, bl = (
            c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels
        )
        return 0.2126 * r + 0.7152 * g + 0.0722 * bl

    light, dark = sorted((luminance(a), luminance(b)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def _hex(value: str) -> str:
    value = (value or "").strip()
    if not _HEX.match(value):
        raise ValueError(f"Cor inválida: {value!r}. Use o formato #RRGGBB.")
    return value.upper()


class CaptionStyle(BaseModel):
    cor: str = DEFAULT_BRAND
    estilo: Literal["caixa", "cor"] = "caixa"
    tamanho: Literal["P", "M", "G"] = "M"

    _cor = field_validator("cor")(_hex)

    @model_validator(mode="after")
    def legivel(self) -> "CaptionStyle":
        # Na "caixa" o texto escuro fica sobre a cor. Na "cor" é a cor que fica sobre
        # o contorno preto. As duas contas são a mesma pergunta com fundos diferentes.
        fundo = INK if self.estilo == "caixa" else OUTLINE
        if contrast_ratio(self.cor, fundo) < MIN_CONTRAST:
            raise ValueError(
                f"A cor {self.cor} fica ilegível na legenda: o contraste precisa ser "
                f"de pelo menos {MIN_CONTRAST}:1. Escolha uma cor mais clara."
            )
        return self


class TitleStyle(BaseModel):
    ligado: bool = True
    fundo: str = INK
    texto: str = WHITE

    _cores = field_validator("fundo", "texto")(_hex)

    @model_validator(mode="after")
    def legivel(self) -> "TitleStyle":
        if contrast_ratio(self.texto, self.fundo) < MIN_CONTRAST:
            raise ValueError(
                f"O texto {self.texto} fica ilegível sobre o fundo {self.fundo}: o "
                f"contraste precisa ser de pelo menos {MIN_CONTRAST}:1."
            )
        return self


class HandleStyle(BaseModel):
    texto: str = Field(default="", max_length=40)
    ligado: bool = True

    @field_validator("texto")
    @classmethod
    def limpa(cls, value: str) -> str:
        return (value or "").strip()


class ClipStyle(BaseModel):
    """O que um perfil diz sobre o visual dos clipes. Medidas ficam no render."""

    marca: str = DEFAULT_BRAND
    legenda: CaptionStyle = Field(default_factory=CaptionStyle)
    titulo: TitleStyle = Field(default_factory=TitleStyle)
    arroba: HandleStyle = Field(default_factory=HandleStyle)
    fonte: str = DEFAULT_FONT

    _marca = field_validator("marca")(_hex)

    @field_validator("fonte")
    @classmethod
    def fonte_conhecida(cls, value: str) -> str:
        if value not in FONT_KEYS:
            raise ValueError(f"Fonte inválida: escolha uma de {', '.join(FONT_KEYS)}.")
        return value

    @model_validator(mode="after")
    def marca_legivel(self) -> "ClipStyle":
        # A marca é a cor da palavra-chave, escrita sobre o fundo do título.
        if contrast_ratio(self.marca, self.titulo.fundo) < MIN_CONTRAST:
            raise ValueError(
                f"A cor da marca {self.marca} fica ilegível sobre o fundo do título "
                f"{self.titulo.fundo}: o contraste precisa ser de pelo menos "
                f"{MIN_CONTRAST}:1."
            )
        return self


#: Destaque de quem já gerava clipes antes deste esquema, que não escolheu nada: o
#: visual dele era uma palavra amarela, e é isso que continua.
_LEGACY_CAPTION = "#FFD23F"


def _read_legacy(path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning(f"Não consegui ler {path}: o estilo segue sem ele")
        return {}
    return data if isinstance(data, dict) else {}


def legacy_style(source_type: Optional[str], profile_id: Optional[str]) -> ClipStyle:
    """
    O estilo de quem já existia antes deste esquema, lido do que ele configurou.

    Lê e não grava: os JSONs continuam sendo do modo streamer, e voltar a versão
    antiga do sistema não encontra nada mudado. O estilo só passa a existir no banco
    quando a pessoa salvar um.

    Uma cor que não passa no contraste é trocada aqui em vez de recusada: ela foi
    escolhida antes de a regra existir, e recusar deixaria o perfil sem estilo
    nenhum. O caso comum é o oposto, identidades como azul com letra amarela, que
    passam inteiras: fundo e texto do banner viram fundo e texto do título.
    """
    banner = _read_legacy(preset_path(source_type, BANNER_COLORS_FILE, profile_id))
    bar = _read_legacy(preset_path(source_type, BAR_STYLE_FILE, profile_id))

    texto = banner.get("text_color")
    fundo = banner.get("bg_color")
    style = ClipStyle(legenda=CaptionStyle(estilo="cor", cor=_LEGACY_CAPTION))

    if bar.get("name"):
        style.arroba = HandleStyle(texto=bar["name"])
    if banner.get("font") in FONT_KEYS:
        style.fonte = banner["font"]

    try:
        if texto and fundo:
            titulo = TitleStyle(fundo=fundo, texto=texto)
            # O destaque de sempre, no amarelo da própria página. Aqui a marca é a cor
            # do texto, porque ela é a que está escrita sobre aquele fundo.
            style = ClipStyle(
                marca=titulo.texto,
                legenda=CaptionStyle(estilo="cor", cor=titulo.texto),
                titulo=titulo,
                arroba=style.arroba,
                fonte=style.fonte,
            )
    except ValueError as exc:
        logger.warning(f"Banner antigo do perfil {profile_id} fora da regra ({exc}): usando o padrão")
    return style


def parse_style(raw: Optional[str]) -> Optional[ClipStyle]:
    """O estilo gravado, ou None se não houver ou não fizer mais sentido."""
    if not raw:
        return None
    try:
        return ClipStyle.model_validate_json(raw)
    except ValueError as exc:
        logger.warning(f"Estilo gravado inválido, ignorado: {exc}")
        return None


def style_for_profile(profile) -> ClipStyle:
    """O estilo em vigor do perfil: o gravado ou, em perfil antigo, o que ele já tinha."""
    return parse_style(profile.style_json) or legacy_style(profile.source_type, profile.id)


def style_for_job(job, profile=None) -> ClipStyle:
    """
    O estilo com que este job renderiza.

    A cópia do próprio job vem primeiro. Job anterior a este esquema não tem cópia: ele
    usa o perfil, o que dá o mesmo visual que ele teria se fosse renderizado hoje.
    """
    gravado = parse_style(job.style_json)
    if gravado is not None:
        return gravado
    if profile is not None:
        return style_for_profile(profile)
    if job.profile_id is None and job.source_type:
        return legacy_style(job.source_type, None)
    return ClipStyle()
