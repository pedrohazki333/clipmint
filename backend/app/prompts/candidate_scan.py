"""
Passada 1 do compilado: onde olhar, antes de decidir o que entra.

A escolha de janelas do pipeline nasce dos BURACOS da transcrição
(services/audio_events.py): silêncio alto = aconteceu alguma coisa. Isso
resolve o caso que motivou aquele módulo, mas assume que o momento mora no
silêncio — e num compilado de gameplay com amigos metade dos melhores momentos
é o contrário disso: todo mundo falando junto, gritando por cima, enquanto a
bagunça acontece na tela.

Medido no compilado real do alanzoka (Grain Rot), nos seis trechos que um
editor humano escolheu: três eram evento forte de áudio, um era buraco curto
demais para contar, e **dois não tinham buraco nenhum** — fala contínua do
começo ao fim. Esses dois somavam 62s dos 128s do compilado, quase metade. Como
a visão só olha buraco alto, eles nunca chegavam descritos ao modelo: ele
escolhia sem enxergar justamente os melhores pedaços.

Esta passada conserta a origem. Ela não julga nem monta nada: lê a transcrição
inteira e aponta os instantes que MERECEM UM OLHAR, incluindo de propósito os
que estão enterrados em fala. A visão descreve esses instantes e só então a
passada 2 monta o compilado, já sabendo o que aparece na tela em cada um.
"""

CANDIDATE_SCAN_PROMPT = """Você vai ajudar a montar um COMPILADO deste vídeo, mas ainda NÃO é hora de escolher.

Sua única tarefa agora é dizer ONDE VALE A PENA OLHAR. Outro sistema vai extrair quadros do vídeo nesses instantes e descrever o que aparece na tela; só depois disso o compilado é montado.

## Metadados
- **Título**: {title}
- **Canal**: {channel}
- **Duração total**: {duration_str}

## Transcrição (timestamps em segundos)
{gap_legend}
{transcript_with_timestamps}

## O que apontar
Liste até {max_candidates} momentos candidatos. Um candidato é um instante em que a transcrição sugere que ACONTECEU alguma coisa:

- reação forte — susto, grito, gargalhada, "que isso", "não acredito", xingamento;
- alguém narrando o que está vendo — "olha ele", "ele tá vindo", "corre";
- confusão coletiva: várias pessoas falando por cima, frases cortadas pela metade, repetição ("vai, vai, vai");
- alguém contando o que outro jogador fez — a graça costuma ser do amigo, não de quem fala;
- piada, apelido, provocação, trocadilho que gera risada em seguida.

**Inclua de propósito os momentos em que ninguém para de falar.** Não procure só silêncio: a bagunça mais engraçada normalmente acontece com todo mundo falando ao mesmo tempo, e é justamente ela que o resto do sistema não enxerga sozinho. Se o trecho tem muita fala mas parece caótico ou empolgado, ele É candidato.

## Regras
- Cada candidato tem entre {min_window}s e {max_window}s. Aponte o momento, não o assunto inteiro.
- Cubra o vídeo TODO. Um vídeo de horas não pode ter todos os candidatos na primeira meia hora — espalhe.
- Não repita o mesmo acontecimento em dois candidatos.
- Ordene por tempo.
- Na dúvida, aponte. Custa barato olhar e caro não olhar; quem descarta é a passada seguinte.

Retorne SOMENTE JSON válido, sem markdown:
{{
  "candidates": [
    {{"start": 3840.0, "end": 3852.0, "why": "risada seguida de 'que que isso cara' — alguém fez alguma coisa na tela"}}
  ]
}}"""


def build_candidate_prompt(
    transcript_with_timestamps: str,
    title: str,
    channel: str,
    duration_str: str,
    gap_legend: str = "",
    max_candidates: int = 18,
    min_window: int = 6,
    max_window: int = 30,
) -> str:
    """Prompt da passada 1 — aponta onde a visão deve olhar."""
    return CANDIDATE_SCAN_PROMPT.format(
        transcript_with_timestamps=transcript_with_timestamps,
        title=title,
        channel=channel,
        duration_str=duration_str,
        gap_legend=gap_legend,
        max_candidates=max_candidates,
        min_window=min_window,
        max_window=max_window,
    )
