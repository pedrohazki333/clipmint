"""
Quais layouts existem, e qual rubrica pode usar cada um.

Dois deles são feitos para um tipo de conteúdo e não fazem sentido no outro:

  - **cover** monta capa + banner sobre o vídeo, e a capa é escolhida pelo
    quadro mais expressivo de um ROSTO falando. Num gameplay ela pega um frame
    de tela de jogo, que não diz nada.
  - **streamer** empilha facecam sobre gameplay. Num podcast não há facecam
    separada para empilhar — o vídeo inteiro já é a câmera.

Os outros dois servem a qualquer conteúdo porque não presumem nada sobre ele:
recortar no centro e não recortar nada.

Esta lista é espelhada em `frontend/src/lib/layouts.ts`. Divergirem é bug, e
`tests/test_layouts.py` compara as duas.
"""

from typing import Annotated

from pydantic import AfterValidator

#: layout → rubricas que o aceitam. Vazio = serve a todas.
_LAYOUTS: dict[str, tuple[str, ...]] = {
    # Capa (rosto expressivo) + banner de título + vídeo com face tracking.
    "cover": ("podcast",),
    # Facecam empilhada sobre o gameplay, com faixa no meio.
    "streamer": ("gameplay", "siege"),
    # Recorte 9:16 centralizado, sem camada nenhuma.
    "crop": (),
    # Sem recorte: o enquadramento e a resolução da fonte, só cortado no tempo.
    "original": (),
}

ALL_LAYOUTS: tuple[str, ...] = tuple(_LAYOUTS)

#: O que cada modo faz, na linguagem de quem escolhe.
LAYOUT_LABELS: dict[str, tuple[str, str]] = {
    "cover": ("Capa + banner", "Capa com o rosto, título em destaque e o vídeo embaixo"),
    "streamer": ("Facecam + gameplay", "A câmera em cima, o jogo embaixo"),
    "crop": ("Crop vertical", "Recorte 9:16 no centro, sem camadas"),
    "original": (
        "Layout original",
        "Sem reenquadrar: o corte sai como está no vídeo de origem",
    ),
}


def layouts_for(source_type: str | None) -> tuple[str, ...]:
    """Layouts que esta rubrica aceita, na ordem de exibição."""
    nicho = (source_type or "").lower()
    return tuple(
        layout
        for layout, rubricas in _LAYOUTS.items()
        if not rubricas or nicho in rubricas
    )


def layout_allowed(layout: str | None, source_type: str | None) -> bool:
    return (layout or "") in layouts_for(source_type)


def _ensure_known_layout(value: str) -> str:
    if value not in _LAYOUTS:
        raise ValueError(
            f"Layout inválido: escolha um de {', '.join(ALL_LAYOUTS)}"
        )
    return value


#: Tipo para o campo de layout. Só valida que o modo EXISTE; a combinação com a
#: rubrica depende de dois campos e é conferida em quem os tem à mão.
LayoutField = Annotated[str, AfterValidator(_ensure_known_layout)]
