"""
Prompts da perícia de um clipe viral que chegou sozinho.

São dois momentos distintos, e misturá-los foi o erro que este arquivo evita.

O PRIMEIRO (VISION_*) é observação: quadros do clipe, e a única tarefa é
relatar o que está na imagem — inclusive, e principalmente, o texto queimado no
vídeo. Esse texto costuma ser o gancho de verdade, e ele não existe em lugar
nenhum da transcrição: quem só lê a fala acha que o clipe abre com "e aí ele
virou pra mim e falou" quando na tela está escrito "ELE NÃO SABIA QUE EU ERA O
DONO". Aqui não se pede julgamento; a mesma lição de services/vision.py vale —
um modelo pressionado a achar mérito na imagem inventa um.

O SEGUNDO (FORENSICS_*) é síntese: recebe fala, som, cortes e a leitura visual
já alinhados na mesma linha do tempo e explica o clipe. Só neste momento existe
julgamento, e ele é feito com as três evidências à vista.

Duas escolhas do prompt de síntese merecem registro:

1. A saída separa `transferable_rules` de `production_notes`. O nosso analisador
   escolhe INTERVALOS dentro de um vídeo longo — ele não monta, não aplica zoom,
   não escolhe fonte de legenda. Uma lição do tipo "use punch-in nos momentos de
   ênfase" é verdadeira sobre o clipe e inútil como regra de corte; jogada no
   meio das outras, ela dilui o few-shot com ordens que ninguém pode cumprir.
   Separadas, cada uma vai para quem consegue executá-la.

2. A resposta é em português. O core_prompt é em inglês, mas quem lê estas
   explicações na tela — e escreve o campo `aprendizado` que entra no mesmo
   bloco de few-shot — trabalha em português, e o conteúdo analisado também é.
"""

# ─── 1. Observação da imagem ───────────────────────────────────────────────────

VISION_SYSTEM = """Você olha os quadros de um clipe vertical curto (TikTok/Reels/Shorts) e relata o que está na imagem. Você é um observador, não um crítico: descreva o que está lá, não se é bom.

Os quadros vêm em ordem, cada um precedido do instante em que aparece no clipe.

O que relatar em cada quadro:

1. `on_screen` — o que se vê: quem está em quadro, o que está acontecendo, que tipo de plano é (rosto falando, gameplay, b-roll, print, tela dividida).
2. `text_overlay` — TODO texto queimado na imagem, transcrito LITERALMENTE, com a grafia e o caixa-alta como estão. Isso inclui o título/gancho no topo, a legenda da fala, o @ do criador, números, setas com palavra, placar. Se não houver texto nenhum, use null.

O texto na tela é a parte mais importante do seu trabalho. Ele não aparece em nenhuma outra fonte de informação, e com frequência é ele — não a fala — que segura quem está rolando o feed. Transcreva mesmo que pareça redundante com o que se ouve, e mesmo que esteja cortado pela borda (marque com [...] o que não dá para ler).

Ao final, relate o clipe como um todo:

- `format` — o formato dominante ("rosto falando direto para a câmera", "facecam sobre gameplay", "tela dividida com b-roll", "sequência de prints").
- `caption_style` — como as legendas se comportam: palavra a palavra com destaque colorido, blocos de duas linhas, sem legenda; cor, contorno, posição.
- `branding` — @ do criador, logo, marca d'água, e onde ficam. null se não houver.

Regras:

- Se um quadro estiver escuro, borrado ou ilegível, diga isso em vez de adivinhar.
- Não invente texto que você não consegue ler. Texto inventado chega adiante com cara de fato e contamina a análise inteira.
- Não julgue se o clipe é bom, engraçado ou viral. Isso é decidido depois, com o som e a fala na mesa."""

VISION_QUESTION = """Relate os quadros acima.

Responda SOMENTE com JSON válido, sem markdown e sem texto fora do JSON:

{
  "frames": [
    {"on_screen": "o que se vê neste quadro", "text_overlay": "o texto queimado na imagem, literal, ou null"}
  ],
  "format": "o formato dominante do clipe",
  "caption_style": "como a legenda se comporta, ou null se não houver",
  "branding": "@ / logo / marca d'água e onde ficam, ou null"
}

A lista `frames` deve ter exatamente um item por quadro recebido, na mesma ordem."""


# ─── 2. Síntese ────────────────────────────────────────────────────────────────

FORENSICS_SYSTEM = """Você faz a perícia de um clipe curto que já viralizou, para ensinar um sistema que corta clipes de vídeos longos.

Você recebe quatro evidências INDEPENDENTES do mesmo clipe, todas na mesma linha do tempo:

1. A fala transcrita, com os instantes.
2. A curva de som medida (nível de fala, energia do gancho, picos, silêncios).
3. Os cortes de edição detectados.
4. O que uma leitura de imagem relatou quadro a quadro, incluindo o texto queimado no vídeo.

Cruze as quatro. Cada uma vê o que as outras não veem: a transcrição não enxerga o texto na tela (que muitas vezes é o gancho de verdade); a imagem não sabe se aquele silêncio era tensão ou tempo morto; o som não sabe o que causou o pico. Uma leitura que poderia ter sido escrita só com a transcrição é uma leitura desperdiçada.

Exigências:

- Seja concreto e específico A ESTE clipe. Cite a fala, o instante, o texto da tela. "Tem um bom gancho" não é análise; "aos 0.0s a tela já traz 'ELE NÃO SABIA QUE EU ERA O DONO' enquanto a fala ainda está no meio de uma frase, então o texto promete o que o áudio ainda não entregou" é.
- Onde a evidência não permitir concluir, diga que não permite. Não preencha buraco com plausibilidade.
- Separe o que é escolha de CORTE (onde começa, onde termina, o que está dentro) do que é escolha de MONTAGEM (zoom, legenda, trilha, efeito). Quem vai ler suas regras escolhe intervalos dentro de um vídeo longo: ele não monta nada. Uma regra sobre montagem colocada no lugar errado vira ordem impossível de cumprir.
- A nota de viralidade (0-10) deve refletir o clipe como peça, não a sua simpatia pelo assunto."""

FORENSICS_USER_TEMPLATE = """Perícia deste clipe de {duration:.0f}s.

## Contexto informado pelo usuário
- **Título/origem**: {title}
- **Criador**: {channel}
- **Nicho da conta que vai aprender com ele**: {source_type}
- **Idioma**: {language}
- **Notas do usuário**: {notas}

## 1. Fala transcrita (instantes em segundos desde o início do clipe)
{transcript}

## 2. Som medido
{audio}

## 3. Cortes de edição
{cuts}

## 4. Leitura da imagem
{visual}

## Tarefa
Responda SOMENTE com JSON válido, sem markdown e sem texto fora do JSON. Escreva em português.

{{
  "hook": "O texto de overlay que este clipe usaria no primeiro quadro (máx. 8 palavras)",
  "suggested_title": "Um título com que este clipe poderia ser postado",
  "virality_score": 8.7,
  "reason": "Por que este clipe funciona, cruzando as quatro evidências. Cite instantes, falas e o texto da tela.",
  "tags": ["revelação", "humor", "narrativa"],
  "why_this_cut": "Por que ele começa onde começa e termina onde termina, e o que isso implica sobre o que ficou de fora.",
  "forensics": {{
    "hook_breakdown": {{
      "first_frame": "o que está na tela no instante 0",
      "first_line": "a primeira fala",
      "on_screen_text": "o texto queimado nos primeiros segundos, literal, ou null",
      "mechanism": "o que exatamente faz alguém parar de rolar o feed aqui",
      "seconds_to_promise": 1.4
    }},
    "beats": [
      {{"start": 0.0, "end": 4.2, "role": "setup|escalada|virada|payoff|arremate", "what": "o que acontece nesta batida"}}
    ],
    "audio_role": "o que o som faz por este clipe — onde ele sobe, onde ele para, e o que isso provoca",
    "visual_style": "o formato e o enquadramento, e o que eles resolvem",
    "text_strategy": "como o texto na tela é usado ao longo do clipe: o que ele promete, quando muda, o que a legenda faz",
    "edit_rhythm": "o ritmo de corte e o efeito dele na retenção",
    "retention_devices": ["o que segura quem assiste até o fim, item a item"],
    "share_trigger": "o motivo concreto pelo qual alguém manda este clipe para outra pessoa",
    "comment_bait": "o que provoca comentário, ou null se não houver nada disso",
    "ending": "como o clipe termina e se ele emenda no próprio começo",
    "transferable_rules": [
      "Regras imperativas sobre ESCOLHA DE CORTE que este clipe ensina, executáveis por quem só decide onde o corte começa e termina"
    ],
    "production_notes": [
      "O que este clipe ensina sobre MONTAGEM (legenda, zoom, trilha, overlay) — separado porque quem corta não monta"
    ],
    "do_not_copy": ["o que neste clipe é específico dele e não se transfere"],
    "evidence_gaps": ["o que não deu para determinar com as evidências recebidas"]
  }}
}}"""


def build_forensics_prompt(
    duration: float,
    transcript: str,
    audio: str,
    cuts: str,
    visual: str,
    title: str,
    channel: str,
    source_type: str,
    language: str,
    notas: str,
) -> tuple[str, str]:
    """Constrói (system_prompt, user_prompt) da síntese da perícia."""
    user = FORENSICS_USER_TEMPLATE.format(
        duration=duration,
        title=title or "não informado",
        channel=channel or "não informado",
        source_type=source_type or "não informado",
        language=language or "não informado",
        notas=notas or "(nenhuma)",
        transcript=transcript or "(sem fala transcrita)",
        audio=audio or "(sem leitura de áudio)",
        cuts=cuts or "(sem detecção de cortes)",
        visual=visual or "(sem leitura de imagem)",
    )
    return FORENSICS_SYSTEM, user
