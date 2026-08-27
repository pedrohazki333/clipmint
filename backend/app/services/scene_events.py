"""
Descrever o que aconteceu nos momentos que o áudio encontrou.

O áudio (services/audio_events.py) resolveu metade do problema: ele diz que
entre 50:30 e 50:51 há 21 segundos sem uma palavra transcrita e 13 dB acima do
nível de fala — ou seja, que ali aconteceu alguma coisa. Ele não diz o quê, e o
modelo que decide o corte recebe só o número.

Aqui a imagem completa a frase. A visão olha SOMENTE as janelas que o áudio já
marcou como evento forte, o que é a diferença entre US$ 0,13 e US$ 0,85 por
vídeo: varrer os 56 minutos às cegas custaria 61s de CPU e 284k tokens, contra
12s e 44k olhando as ~14 janelas que interessam.

A ordem importa e é deliberada: o áudio é determinístico, barato e roda no
vídeo inteiro; a visão é cara, probabilística e roda onde o áudio apontou. Duas
tentativas de descoberta visual barata foram medidas e descartadas antes desta
— densidade de keyframes e diferença de pixels entre keyframes —, ambas cegas
justamente no evento que motivou o módulo.
"""

import logging

from app.config import settings
from app.services import vision
from app.services.audio_events import Gap

logger = logging.getLogger(__name__)

# Alguns segundos antes e depois do buraco: o que causou o barulho costuma
# começar um pouco antes de a fala parar.
_MARGIN = 4.0

# Perguntar "o que se vê" traz o CENÁRIO; o clipe está no que MUDA. Medido no
# vídeo do alanzoka (Grain Rot), janela [3840-3850], mesmos 10 quadros e mesmo
# modelo, só a pergunta trocada: com "descreva o que se vê" a resposta foi
# "exploração rotineira, sem evento marcante visível"; com esta, "aparece à
# esquerda a figura de outro jogador (pequena, junto a um banco)" — e a ligação
# entre a aparição e a risada. O gag era o personagem de outro jogador passando
# pela tela, e a primeira pergunta o classificou como nada.
_QUESTION = (
    "Estes quadros cobrem um trecho em que o áudio está alto — riso, grito ou "
    "reação. Alguma coisa aconteceu NA TELA. Compare os quadros entre si e diga "
    "o que MUDA: algo ou alguém que aparece, atravessa, some, se move de um "
    "jeito estranho ou está fora de lugar. Personagens de outros jogadores "
    "contam, mesmo pequenos, escuros ou no canto do quadro. Descreva também o "
    "rosto de quem aparece na facecam. Se de fato nada muda, diga isso "
    "explicitamente em vez de descrever o cenário parado.\n"
    + vision.JSON_RULES
)


async def describe_events(job_id: str, video_path: str, gaps: list[Gap]) -> None:
    """
    Preenche `gap.scene` nos eventos fortes, no lugar.

    Modifica os gaps recebidos em vez de devolver uma cópia porque quem os
    consome — a anotação da transcrição — já tem a lista na mão.

    Nunca levanta: sem descrição, a anotação volta a ser só a medição de áudio,
    que é o comportamento de ontem e funciona.
    """
    if not settings.vision_enabled or not gaps:
        return

    # Numa live longa há muito mais evento forte do que orçamento de visão, e
    # aqui a escolha entre eles é que decide o que o modelo enxerga. A fatia
    # cronológica que existia neste lugar pegava os PRIMEIROS eventos: medido
    # no vídeo do alanzoka (110 min, 74 eventos fortes), as 20 janelas cobriam
    # de 0:30 a 52:30 — a metade de trás do vídeo não era olhada por ninguém, e
    # dois dos seis momentos que um editor humano escolheu para o compilado
    # estavam justamente lá (71min e 94min). Ordenar por intensidade escolhe os
    # momentos mais barulhentos do vídeo INTEIRO em vez dos mais cedo.
    strongest = sorted(
        (g for g in gaps if g.is_strong_event),
        key=lambda g: -g.above_speech,
    )[: settings.vision_max_windows]

    targets = sorted(strongest, key=lambda g: g.start)
    if not targets:
        logger.info(f"[{job_id}] Nenhum evento forte de áudio para a visão olhar")
        return

    windows = [(g.start - _MARGIN, g.end + _MARGIN) for g in targets]
    questions = [_QUESTION] * len(targets)

    logger.info(
        f"[{job_id}] Visão olhando {len(targets)} evento(s) de áudio "
        f"(os mais fortes de {sum(1 for g in gaps if g.is_strong_event)})"
    )
    scenes = await vision.look_many(job_id, video_path, windows, questions)

    described = 0
    for gap, scene in zip(targets, scenes):
        if scene is None:
            continue
        gap.scene = scene.summary()
        described += 1
        logger.info(
            f"[{job_id}]   [{gap.start:.1f}-{gap.end:.1f}] {gap.scene[:160]}"
        )

    logger.info(f"[{job_id}] {described}/{len(targets)} evento(s) descritos pela imagem")
