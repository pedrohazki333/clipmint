"""
Passada 2 do compilado: montar a partir de uma LISTA DE MOMENTOS.

A passada de análise normal recebe a transcrição inteira e procura clipes. Nesse
formato o modelo ancora num acontecimento e passa a usar `segments` como
tesoura — apara o tempo morto DENTRO daquele momento, que é a semântica do ace
de Siege. Medido no vídeo do alanzoka: em quatro compilados propostos, quatro
eram 2-3 fatias de uma única região estreita (87s, 96s, 73s e 147s), mesmo com
a regra dizendo em prosa que cada trecho tem de ser um acontecimento diferente,
a minutos de distância. Duas redações diferentes, mesmo resultado.

O formato da entrada é que decide. Aqui o modelo não recebe transcrição: recebe
um CARDÁPIO de momentos numerados, já descritos pela imagem, e devolve os
NÚMEROS que entram em cada compilado. Fatiar um momento ao meio deixa de ser
uma saída possível — não há como expressar isso escolhendo de uma lista.
"""

ASSEMBLY_PROMPT = """Você vai montar {count} COMPILADOS para o TikTok a partir dos momentos abaixo.

Cada momento já foi localizado no vídeo e descrito por quem olhou a imagem. Sua tarefa é escolher quais entram em cada compilado e em que ORDEM — nada além disso.

## Vídeo
- **Título**: {title}
- **Canal**: {channel}

## Momentos disponíveis
{moments}

## Como montar

- Cada compilado usa de **3 a 5 momentos**, somando **{target}s**. Some as durações mostradas acima para conferir.
- **Abra pela reação mais forte**, mesmo que ela seja o último momento da lista. A ordem é editorial, não cronológica — e quase nunca é bom que seja cronológica.
- O primeiro momento de cada compilado deve ser **curto e auto-explicativo**: funciona sem contexto, faz rir em segundos.
- **Prefira momentos em que o personagem de um companheiro aparece fazendo alguma coisa na tela e o rosto do streamer vira** (de concentrado para gargalhada, susto ou grito). Medido num compilado real deste nicho: cinco dos seis momentos escolhidos por um editor humano tinham o amigo visível, e todos os seis tinham a virada de rosto. A graça é o que o amigo faz; a cara é a prova.
- **Alterne o tipo**: reação pura e caos de jogo se revezam. Dois momentos seguidos do mesmo tipo achatam o vídeo.
- Um momento **não precisa se sustentar sozinho** — quem precisa funcionar é o compilado inteiro.
- Os dois compilados **não repetem momentos** entre si, e cada um tem seu próprio fio: junte os que conversam.
- Use apenas os números da lista. Não invente timestamps, não corte um momento ao meio, não junte dois números num só.
- Sobrando momento bom que não conversa com nenhum dos dois, deixe de fora.

Retorne SOMENTE JSON válido, sem markdown:
{{
  "compilations": [
    {{
      "moments": [7, 2, 15],
      "hook_score": 9,
      "retention_score": 8,
      "shareability_score": 8,
      "loopability_score": 6,
      "comment_bait_score": 7,
      "final_score": 79,
      "verdict": "post",
      "suggested_hook_caption": "texto curto de capa",
      "suggested_title": "título do post",
      "reason": "por que este conjunto funciona junto",
      "trim_reason": "qual é o fio comum e por que esta ordem",
      "weak_points": [],
      "tags": ["gameplay", "humor"]
    }}
  ],
  "analysis_notes": "avaliação geral"
}}

Regras do JSON:
- `final_score` é a média ponderada dos cinco eixos (retention 30%, hook 25%, shareability 20%, comment_bait 15%, loopability 10%), de 0 a 100.
- `verdict` é "post" quando está pronto para publicar, ou "revisar_corte" quando vale mas precisa de ajuste humano.
- Se os momentos disponíveis não derem nem UM compilado que se sustente, devolva `{{"compilations": [], "analysis_notes": "motivo"}}`.
{moderation_rule}"""


def format_moment(index: int, start: float, end: float, speech: str, scene: str, why: str) -> str:
    """Uma entrada do cardápio. O número é a única forma de referenciá-la."""
    lines = [f"### Momento {index} — {start:.1f}s a {end:.1f}s ({end - start:.0f}s)"]
    if scene:
        lines.append(f"- Na imagem: {scene}")
    if speech:
        lines.append(f'- Fala: "{speech}"')
    if why:
        lines.append(f"- Apontado porque: {why}")
    return "\n".join(lines)


def build_assembly_prompt(
    moments: str,
    title: str,
    channel: str,
    target: str,
    count: int = 2,
    moderation_rule: str = "",
) -> str:
    """Prompt da montagem — escolhe números, não timestamps."""
    return ASSEMBLY_PROMPT.format(
        moments=moments,
        title=title,
        channel=channel,
        target=target,
        count=count,
        moderation_rule=moderation_rule,
    )
