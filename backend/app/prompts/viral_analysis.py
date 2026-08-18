"""
Prompt de análise de viralidade — o coração do ClipMint.

Este módulo contém os templates de prompt usados para instruir o Claude API
a identificar trechos de vídeo com alto potencial viral. O prompt foi projetado
para ser iterado e melhorado com o tempo; evite acoplá-lo à lógica do analyzer.

A rubrica tem cinco eixos (0-10 cada), derivados de como o algoritmo pondera
os sinais: hook, retention, shareability, loopability e comment_bait. Eles são
guardados por clip no banco porque o cronograma de postagem escolhe o clipe de
cada horário por um eixo específico — não pela nota final.

O system prompt vive em `prompt_engine/core_prompt.txt` (montado pelo
PromptBuilder, que injeta exemplos validados). Aqui ficam os critérios que
mudam por tipo de fonte e o prompt de usuário com o formato de saída.
"""

# ─── Formato do transcript com timestamps ─────────────────────────────────────

TRANSCRIPT_FORMAT_NOTE = """
The transcript below uses the format: [START_TIME - END_TIME] Text
Times are in seconds (e.g., [12.4 - 15.1] Hello everyone).
"""

# Legenda das anotações de buraco. Sem ela o modelo trata «((...))» como texto
# transcrito e chega a citar a anotação dentro do trim_reason.
GAP_LEGEND = """
Linhas entre ((parênteses duplos)) não são fala: são trechos SEM palavra
transcrita, com a medição do áudio naquele intervalo em relação ao nível normal
de fala do vídeo. «ÁUDIO ALTO» = som bem acima da fala: gargalhada, grito,
ação, reação — o momento em si. «áudio baixo» = silêncio de verdade, tempo
morto. Sem rótulo = faixa intermediária, decida pelo contexto em volta.
"""

# ─── Critérios por tipo de fonte ───────────────────────────────────────────────
# Injetados no core_prompt via {source_criteria}. O que prende alguém num corte
# de podcast (frase-momento, arco de resolução) não é o que prende num corte de
# gameplay (pico visual, legibilidade sem som), então a rubrica troca junto.

PODCAST_CRITERIA = """## Critérios para PODCAST

- Gancho verbal nos primeiros 3s: existe uma afirmação contra-intuitiva, uma revelação, uma pergunta em aberto, ou um sinal de autoridade/credibilidade logo de cara? Introduções ("então hoje eu vim falar sobre...") são fracas — penalize.
- Arco de resolução: o trecho tem começo, meio e fim dentro de si mesmo (não depende de contexto anterior do podcast pra fazer sentido)?
- Densidade de informação/emoção: há silêncios longos DE ÁUDIO BAIXO, hesitação, ou divagação que quebram o ritmo? Isso derruba completion rate. Atenção: trecho sem fala mas com áudio alto é o oposto disso — é risada da mesa ou reação a algo acontecendo, e costuma ser o melhor pedaço do corte.
- Potencial de debate: a afirmação é polêmica ou opinativa o suficiente pra gerar comentários discordando ou concordando com força?
- Frase-momento (soundbite): existe uma frase isolada que funcionaria como legenda de destaque ou citação compartilhável?"""

GAMEPLAY_CRITERIA = """## Critérios para GAMEPLAY

- Pico visual nos primeiros 3s: o clipe abre já em tensão (quase morrendo, prestes a uma jogada) ou precisa de "aquecimento" antes do momento bom? Aquecimento é fraco — penalize.

  Aquecimento é tempo ocioso: caminhar, esperar, arrumar o inventário, conversa que não leva a nada. NÃO é aquecimento a tentativa que produz o desastre — o grupo combinando o plano, explicando um para o outro, executando com convicção. Isso é a montagem da piada, e sem ela a explosão é só barulho.

  A diferença prática: se o trecho anterior ao pico fosse cortado, quem assiste ainda entenderia por que aquilo é engraçado? Se sim, era aquecimento, corte. Se não, era a construção, e ela entra — mesmo que dure um minuto e leve o corte para perto do teto de duração.
- Reviravolta clara: há uma mudança de estado legível em poucos segundos (derrota virando vitória, erro virando acerto, reação de susto/comemoração)?
- Legibilidade sem áudio: o momento é compreensível só pelo visual (muita gente assiste sem som)? Isso importa mais que em podcast.
- Loop natural: a ação termina de um jeito que poderia reiniciar o clipe sem parecer cortado no meio?
- Reação humana: há reação de voz/call do jogador (grito, xingamento, comemoração) que reforça o pico visual?

Atenção: você não vê a tela. O pico visual é inferido por dois sinais — a reação falada (grito, "não acredito", xingamento, contagem regressiva) e as anotações de trecho sem fala com ÁUDIO ALTO, que marcam onde a ação aconteceu sem ninguém narrar. Quando nenhum dos dois aparece, seja conservador na nota em vez de supor a jogada; quando o áudio alto aparece, ele é a jogada e o corte tem que contê-lo."""

SIEGE_CRITERIA = """## Critérios para SIEGE (Rainbow Six Siege / Siege X)

O público de Siege é jogador: ele reconhece uma jogada boa em dois segundos e não precisa de explicação. Priorize, nesta ordem:

- Sequência de eliminações: dois ou mais abates no mesmo round. O que decide a nota é a QUALIDADE de cada abate, não a quantidade nem a velocidade. Um 4k em que os quatro são bonitos — reação rápida num inimigo que aparece de surpresa, ângulo difícil, tiro pela parede lendo o som, negar um push sozinho, vencer em desvantagem — vale mais que um triplo relâmpago em que dois foram sorte ou spray. Ace (5 abates) e clutch (1vX vencido) são o teto: material de nota alta quase automática.

  Espalhamento não derruba a nota da JOGADA, derruba o CORTE — e corte é você quem decide. Um 4k ou um ace distribuído pelo round inteiro continua sendo ótimo material; o que não pode é virar um clipe com um minuto de caminhada entre um abate e outro, porque tempo morto destrói retenção. Para esses casos use `segments` (ver abaixo): a jogada inteira entra num vídeo só, com o tempo morto removido.
- Abate rápido de um tiro só: headshot instantâneo, reação a um inimigo que aparece de surpresa, troca de duelo ganha no reflexo. O sinal na transcrição é a reação imediata — o próprio streamer ou a call comentando a velocidade ("que reflexo", "nem viu", "na cabeça", "instantâneo") — ou o silêncio tenso seguido de explosão.
- Clutch sob pressão: último vivo, bomba plantada, tempo acabando. O relógio faz o trabalho de tensão sozinho; o valor está em entrar já no aperto, não na preparação.
- Leitura e domínio: prefire acertado, ler o som e matar pela parede, drone que entrega a posição, spawnpeek. É o que o público de Siege comenta e discute nos comentários.
- Treta e zoeira na call: briga entre os jogadores, xingamento, acusação de teamkill, alguém culpando o outro pela derrota. Vale tanto quanto a jogada — muitas vezes mais, porque compartilha melhor.
- Fracasso cômico: teamkill, cair do mapa, gastar o round inteiro numa parede errada, whiff na cara do inimigo. O erro absurdo compartilha tão bem quanto o acerto.

Atenção — você recebe SOMENTE a transcrição, sem imagem: a jogada é inferida pela fala. Em partida competitiva a call é TÁTICA, não comemorativa ("puxa a câmera", "espera abrir o alçapão"), então não espere narração de abate: aprenda a ler os sinais que aparecem de verdade.

Sinais que CONFIRMAM abate, e devem ser tratados como confirmação, não como suposição:
- "peguei", "matei", "pegou", "matou", "tá down", "caiu" — cada um é um abate.
- Placar falado: "tá 3v2", "1v3", "somos 4 contra 5". A queda de um placar para o outro entre duas falas conta os abates que aconteceram no meio, mesmo sem ninguém narrar. É o sinal mais confiável em FPL.
- Vários desses sinais concentrados numa janela curta = sequência de eliminações, mesmo sem ninguém dizer "double" ou "triple".
- Reação súbita da call (grito, xingamento, "isso!", "boa!") logo após silêncio tenso normalmente marca o abate importante — e nesse caso o corte começa no silêncio tenso, não no grito.
- Trecho sem fala anotado como ÁUDIO ALTO: é tiroteio, explosão ou grito. A jogada está ali dentro, não depois dela.

Seja conservador só quando NENHUM desses sinais aparece — trecho de gameplay silencioso e sem reação não vira clipe. Mas não descarte um bom momento por falta de narração explícita: em Siege a jogada quase nunca é narrada, é confirmada por essas pistas.

Não confunda narração de rotina ("vou de Ash", "alguém dá drone") com momento: sem pico de reação, sem abate encadeado e sem treta, o trecho é enchimento por melhor que seja a partida."""

# Só Siege monta clipe com trechos costurados. Nos outros nichos o corte
# contínuo é o certo, e liberar segmentos lá só criaria clipe picotado.
SEGMENTS_RULE = """
## Trechos costurados (`segments`)

Quando a jogada é boa mas está espalhada — o caso típico é o ace com caminhada entre os abates —, devolva `segments`: uma lista de trechos do vídeo que serão emendados num clipe único, na ordem, com o tempo morto entre eles removido.

```
"segments": [[1820.4, 1834.0], [1851.2, 1863.5], [1879.0, 1892.4]]
```

Regras:
- Use `segments` só quando remover o meio melhora de verdade. Jogada que já acontece seguida NÃO precisa disso — nesse caso devolva apenas `start`/`end`, como sempre.
- Cada trecho tem no mínimo 3s. Trecho curtíssimo vira piscada e confunde.
- A soma dos trechos não passa de {max_segmented}s — o clipe final tem que ficar perto de um minuto, não do round inteiro. Se a jogada não couber, corte o começo dela e fique com os melhores abates.
- Os trechos vêm em ordem cronológica e não se sobrepõem.
- A emenda é corte seco, sem transição: termine cada trecho num ponto que não corte uma palavra ao meio quando der.
- `start` e `end` continuam obrigatórios: use o começo do primeiro trecho e o fim do último.
- Explique no `trim_reason` o que foi removido e por quê.
"""


SOURCE_CRITERIA = {
    "podcast": PODCAST_CRITERIA,
    "gameplay": GAMEPLAY_CRITERIA,
    "siege": SIEGE_CRITERIA,
}

DEFAULT_SOURCE_TYPE = "podcast"
SOURCE_TYPES = ("podcast", "gameplay", "siege")


def default_source_type(layout_mode: str | None) -> str:
    """
    Palpite do tipo de fonte a partir do layout escolhido.

    O layout 'streamer' (facecam + gameplay) é o de live/gameplay; 'cover' é o
    formato dos cortes de podcast. É só um default: o usuário confirma na
    criação do job, porque o tipo decide em qual conta o clipe é postado.
    """
    return "gameplay" if (layout_mode or "").lower() == "streamer" else "podcast"


def source_criteria(source_type: str | None) -> str:
    """Bloco de critérios do tipo de fonte, caindo em podcast se desconhecido."""
    return SOURCE_CRITERIA.get(
        (source_type or DEFAULT_SOURCE_TYPE).lower(),
        PODCAST_CRITERIA,
    )


# ─── User prompt template ──────────────────────────────────────────────────────

USER_PROMPT_TEMPLATE = """Analise a transcrição abaixo e identifique todos os trechos com potencial viral de {threshold_100} ou mais no final_score.

## Metadados do vídeo
- **Título**: {title}
- **Canal**: {channel}
- **Duração total**: {duration_str}
- **Tipo de fonte**: {source_type}

## Transcrição (timestamps em segundos)
{gap_legend}
{transcript_with_timestamps}

## Tarefa
Encontre TODOS os trechos que fecham {threshold_100}+ de final_score, aplicando os critérios de {source_type}.
Prefira cortes enxutos de {preferred_min}-{preferred_max}s; passe disso (até {max_duration}s) só quando o momento realmente precisar da construção.
Antes de fixar cada `start`, responda a si mesmo: o que está sendo dito aqui é o FATO ou é a REAÇÃO ao fato? Se for reação, o corte começa antes.
Os campos `start` e `end` são o corte final, em segundos absolutos do vídeo.
Retorne SOMENTE JSON válido — sem markdown, sem texto fora do JSON.

## Formato exigido
{{
  "clips": [
    {{
      "start": 12.4,
      "end": 47.2,
      "hook_score": 9,
      "retention_score": 8,
      "shareability_score": 8,
      "loopability_score": 6,
      "comment_bait_score": 7,
      "final_score": 79,
      "verdict": "post",
      "trim_reason": "Começa direto na afirmação polêmica e termina na frase-momento, sem a divagação de 15s que vinha antes.",
      "suggested_hook_caption": "Ninguém fala sobre isso",
      "suggested_title": "A verdade escondida sobre [tema]",
      "reason": "Gancho de revelação com afirmação contra-intuitiva, tensão construída por história pessoal e um soundbite final que pede compartilhamento.",
      "weak_points": ["hesitação curta aos 31s, não chega a quebrar o ritmo"],
      "tags": ["revelation", "controversial", "educational"]
    }}
  ],
  "analysis_notes": "Avaliação geral do potencial viral do vídeo e dos temas."
}}

Regras do JSON:
- `verdict` é "post" quando o trecho está pronto para publicar, ou "revisar_corte" quando vale a pena mas o corte precisa de ajuste humano. Trechos que você descartaria simplesmente não entram na lista.
- `weak_points` lista os pontos que derrubam retenção; use lista vazia quando não houver.
- `final_score` é a média ponderada dos cinco eixos (retention 30%, hook 25%, shareability 20%, comment_bait 15%, loopability 10%), numa escala de 0 a 100.

Se nenhum trecho atingir o limiar, retorne: {{"clips": [], "analysis_notes": "motivo"}}
{segments_rule}"""

# ─── Helper functions ──────────────────────────────────────────────────────────

# Buraco sem evento e curto é respiração entre frases: anotar todos eles
# encheria a transcrição de linhas que não mudam decisão nenhuma e diluiria as
# que mudam. Evento entra sempre, independentemente da duração.
_MIN_ANNOTATED_QUIET = 5.0


def worth_annotating(gap) -> bool:
    """Se este buraco tem algo a dizer ao modelo sobre onde cortar."""
    return gap.is_event or gap.duration >= _MIN_ANNOTATED_QUIET


def format_gap(gap) -> str:
    """
    A linha que descreve um buraco da transcrição pelo que o áudio diz dele.

    O buraco alto é o caso que existe para ser resolvido: sem esta linha ele
    chega ao modelo como ausência de conteúdo, e a instrução de penalizar
    silêncio longo faz o resto do estrago.
    """
    # Construção longa muda ONDE o corte começa, então ela vai junto do
    # momento em vez de ficar implícita na transcrição. Sem este número o
    # modelo lê 128s de conversa como enchimento e abre direto no barulho.
    buildup = ""
    if gap.is_event and getattr(gap, "has_long_buildup", False):
        buildup = (
            f" A fala vem sem pausa desde {gap.buildup_start:.1f}s, ou seja, "
            f"{gap.buildup:.0f}s de construção antes deste momento — pode ser "
            f"um payoff que levou tempo sendo montado. Isso NÃO é um ponto de "
            f"corte pronto: quase sempre é longo demais para um clipe. Leia a "
            f"construção e comece onde a tentativa que dá errado começa, "
            f"respeitando o teto de duração."
        )

    head = f"[{gap.start:.1f} - {gap.end:.1f}] (({gap.duration:.0f}s sem fala"
    if gap.is_event:
        # Com descrição da imagem o modelo não precisa mais supor o que houve —
        # e supor era exatamente o que fazia ele tratar o trecho como vazio.
        scene = getattr(gap, "scene", None)
        if scene:
            return (
                f"{head.replace('sem fala', 'SEM FALA')} — ÁUDIO ALTO, "
                f"{gap.above_speech:+.0f} dB em relação à fala normal. "
                f"NA IMAGEM: {scene}{buildup}))"
            )
        return (
            f"{head.replace('sem fala', 'SEM FALA')} — ÁUDIO ALTO, "
            f"{gap.above_speech:+.0f} dB em relação à fala normal: aconteceu "
            f"ALGUMA COISA aqui — risada, grito, reação, ação na tela. "
            f"É momento, não tempo morto.{buildup}))"
        )
    if gap.is_dead:
        return f"{head} — áudio baixo, {gap.above_speech:+.0f} dB: silêncio, tempo morto.))"
    return f"{head} — áudio {gap.above_speech:+.0f} dB em relação à fala.))"


def format_transcript_with_timestamps(words: list[dict], gaps: list | None = None) -> str:
    """
    Agrupa palavras em frases com timestamps e formata para o prompt.

    Agrupa palavras em chunks de ~15 palavras ou até encontrar pontuação
    de fim de frase, mantendo timestamps do início e fim do grupo.

    `gaps` são os intervalos sem fala já medidos por services.audio_events, e
    entram na posição cronológica deles como anotação. É o que permite ao
    modelo diferenciar o silêncio que mata retenção do silêncio que É o clipe.
    """
    if not words:
        return "(empty transcript)"

    lines: list[tuple[float, str]] = []
    chunk_words = []
    chunk_start = None

    for word in words:
        text = word["text"]
        start = word["start"]
        end = word["end"]

        if chunk_start is None:
            chunk_start = start

        chunk_words.append(text)

        # Quebra em fim de frase ou a cada 15 palavras
        is_sentence_end = text.rstrip().endswith((".", "!", "?", "..."))
        if is_sentence_end or len(chunk_words) >= 15:
            line_text = " ".join(chunk_words)
            lines.append((chunk_start, f"[{chunk_start:.1f} - {end:.1f}] {line_text}"))
            chunk_words = []
            chunk_start = None

    # Flush do último chunk
    if chunk_words and chunk_start is not None:
        end = words[-1]["end"]
        line_text = " ".join(chunk_words)
        lines.append((chunk_start, f"[{chunk_start:.1f} - {end:.1f}] {line_text}"))

    for gap in gaps or []:
        if worth_annotating(gap):
            lines.append((gap.start, format_gap(gap)))

    lines.sort(key=lambda item: item[0])
    return "\n".join(line for _, line in lines)


def format_duration(seconds: float) -> str:
    """Formata duração em mm:ss ou hh:mm:ss."""
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def build_analysis_prompt(
    words: list[dict],
    title: str,
    channel: str,
    duration_seconds: float,
    threshold: float,
    min_duration: int,
    max_duration: int,
    preferred_min: int = 25,
    preferred_max: int = 40,
    source_type: str = DEFAULT_SOURCE_TYPE,
    max_segmented: int = 70,
    gaps: list | None = None,
) -> str:
    """
    Constrói o prompt de usuário da análise de viralidade.

    O system prompt não sai daqui: ele é montado pelo PromptBuilder a partir de
    `prompt_engine/core_prompt.txt`, que injeta exemplos validados e padrões
    aprendidos. Manter uma segunda cópia neste módulo só criava divergência.

    Args:
        threshold: Limiar na escala 0-10 do sistema; convertido para a escala
            0-100 do final_score que o modelo devolve.
    """
    transcript_text = format_transcript_with_timestamps(words, gaps)
    source = (source_type or DEFAULT_SOURCE_TYPE).lower()

    return USER_PROMPT_TEMPLATE.format(
        gap_legend=GAP_LEGEND.strip() if gaps else "",
        segments_rule=(
            SEGMENTS_RULE.format(max_segmented=max_segmented)
            if source == "siege"
            else ""
        ),
        title=title,
        channel=channel,
        duration_str=format_duration(duration_seconds),
        transcript_with_timestamps=transcript_text,
        threshold_100=round(threshold * 10),
        min_duration=min_duration,
        max_duration=max_duration,
        preferred_min=preferred_min,
        preferred_max=preferred_max,
        source_type=(source_type or DEFAULT_SOURCE_TYPE).lower(),
    )
