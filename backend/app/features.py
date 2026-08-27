"""
Quais features existem NESTE build.

O ClipMint tem duas versões saindo do mesmo código:

  - **pessoal** (`PUBLIC_BUILD=false`, o default): tudo ligado, inclusive o
    nicho Siege X e a aba Melhorar vídeo, que continuam evoluindo aqui;
  - **público** (`PUBLIC_BUILD=true`): o produto que vai para o ar, sem essas
    duas.

A escolha por flag em vez de branch é deliberada. As duas features não tocam o
miolo do pipeline (clipper, facecam, layout, subtitler): Siege X é um VALOR de
`source_type` mais um branch de HUD, e Melhorar vídeo é uma vertical isolada com
router, model e worker próprios. Um branch `public` teria que rebasear
continuamente em cima dos arquivos compartilhados — que é justamente onde o
trabalho acontece — em troca de uma proteção que este módulo já dá.

Nada é apagado aqui: as features ficam inteiras no código e são apenas
desligadas. Voltar para a versão pessoal é uma variável de ambiente.

Regra de uso: NUNCA compare `settings.public_build` diretamente por aí. Toda
decisão passa por uma função deste módulo, para existir um lugar só onde a
resposta pode mudar — e para os testes conseguirem trocar a resposta.
"""

from typing import Annotated

from pydantic import AfterValidator

from app.config import settings

#: Nichos que o build público oferece.
PUBLIC_SOURCE_TYPES: tuple[str, ...] = ("podcast", "gameplay")

#: Nichos da versão pessoal. Siege X só existe aqui.
PERSONAL_SOURCE_TYPES: tuple[str, ...] = ("podcast", "gameplay", "siege")


def public_build() -> bool:
    """Este processo é o build público?

    Lido a cada chamada, e não uma vez no import: é o que permite um teste
    ligar o modo público sem subir outro processo.
    """
    return bool(settings.public_build)


def allowed_source_types() -> tuple[str, ...]:
    """Nichos que este build aceita, em ordem de exibição."""
    return PUBLIC_SOURCE_TYPES if public_build() else PERSONAL_SOURCE_TYPES


def source_type_allowed(value: str | None) -> bool:
    """O nicho existe neste build?"""
    return (value or "").lower() in allowed_source_types()


def video_enhance_enabled() -> bool:
    """A aba Melhorar vídeo existe neste build?

    Falso no público: o router não é registrado, então o endpoint não existe e
    o worker é inalcançável — não há caminho para chamá-lo.
    """
    return not public_build()


def billing_enabled() -> bool:
    """Comprar crédito existe neste build?

    Só no público. Na versão pessoal quem paga a conta de API é o dono, direto
    no provedor — não há o que cobrar, e um endpoint de cobrança registrado ali
    seria superfície sem função. O saldo em si (o ledger) continua existindo nas
    duas: é o mesmo schema, e é o que permite o pipeline ser um só.
    """
    return public_build()


def learning_enabled() -> bool:
    """O sistema de aprendizado existe neste build?

    Cobre três coisas que são a mesma: aprender com clipe viral de outro criador
    (`/api/references/*`), os padrões minerados deles (`/api/patterns/*`) e
    validar um clipe próprio como exemplo (`POST /api/clips/{id}/validate`).

    Falso no público, e não é só uma questão de "feature interna": os exemplos
    validados vão todos para `prompt_engine/examples/validated/`, uma pasta
    ÚNICA que o PromptBuilder injeta na análise de todo mundo. Liberado no
    público, o exemplo de um usuário passaria a influenciar o corte dos outros —
    o mesmo vazamento de estado compartilhado que os presets de marca tinham
    antes de virarem por perfil.
    """
    return not public_build()


def schedule_enabled() -> bool:
    """A fila de postagem existe neste build?

    A grade é fixa e pessoal: 12 horários por dia, cada um escolhendo o clipe
    que lidera um eixo da rubrica, distribuídos entre as contas do dono desta
    instalação (ver routers/schedule.py). Ela não descreve o dia de ninguém
    além dele — para um usuário público seria uma tabela de horários que ele
    não escolheu, apontando para contas que não são dele.

    Uma fila de postagem de verdade, por usuário, é outro produto: precisaria de
    horários configuráveis e de saber onde publicar. Não é o que existe hoje.
    """
    return not public_build()


def _ensure_allowed_source_type(value: str) -> str:
    """Valida um nicho vindo de fora (query, form ou corpo do request)."""
    if not source_type_allowed(value):
        permitidos = ", ".join(allowed_source_types())
        raise ValueError(f"Nicho inválido: escolha um de {permitidos}")
    return value


#: Tipo para parâmetros de nicho. É `str` com validação em tempo de request, e
#: não um `Literal`, porque a lista permitida depende do build — um Literal é
#: fixado no import e não teria como encolher no público.
SourceTypeField = Annotated[str, AfterValidator(_ensure_allowed_source_type)]
