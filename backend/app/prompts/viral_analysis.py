"""
Prompt de análise de viralidade — o coração do ClipMint.

Este módulo contém os templates de prompt usados para instruir o Claude API
a identificar trechos de vídeo com alto potencial viral. O prompt foi projetado
para ser iterado e melhorado com o tempo; evite acoplá-lo à lógica do analyzer.

Critérios de viralidade avaliados:
  1. Gancho emocional (hook) — os primeiros 3 segundos prendem o espectador?
  2. Compartilhamento — as pessoas vão querer mostrar isso a alguém?
  3. Controvérsia / opinião forte — instiga comentários e debates?
  4. Humor — provoca riso genuíno ou situação constrangedora relatable?
  5. Revelação / surpresa — há um twist, fact inesperado ou "eu não sabia disso"?
  6. Relatabilidade — o público-alvo vai pensar "isso acontece comigo"?
  7. Tensão narrativa — há suspense, conflito ou clímax que prende até o fim?
  8. Valor de informação — ensina algo útil de forma concisa e memorável?
"""

# ─── Formato do transcript com timestamps ─────────────────────────────────────

TRANSCRIPT_FORMAT_NOTE = """
The transcript below uses the format: [START_TIME - END_TIME] Text
Times are in seconds (e.g., [12.4 - 15.1] Hello everyone).
"""

# ─── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an expert viral content strategist with deep knowledge of what makes short-form video content explode on TikTok, Instagram Reels, and YouTube Shorts.

Your task is to analyze a video transcript and identify the segments with the highest viral potential for clips between {min_duration}s and {max_duration}s.

You evaluate virality based on 8 criteria, each scored 0-10:
1. **Emotional Hook**: Do the first 3 seconds immediately grab attention?
2. **Share-worthiness**: Will viewers compulsively share this with friends?
3. **Controversy/Strong Opinion**: Does it provoke debate, strong reactions, or challenge assumptions?
4. **Humor/Entertainment**: Genuine laughter, relatable awkwardness, or entertaining chaos?
5. **Revelation/Surprise**: Unexpected twist, counterintuitive fact, or "I never knew that" moment?
6. **Relatability**: Will the target audience feel "this is exactly me"?
7. **Narrative Tension**: Is there suspense, conflict, or a satisfying resolution?
8. **Information Value**: Does it teach something memorable and immediately useful?

The final virality score (0.0-10.0) is a weighted average:
- Hook (25%) + Share-worthiness (20%) + Surprise (15%) + Tension (15%) + Relatability (10%) + Controversy (5%) + Humor (5%) + Info Value (5%)

IMPORTANT RULES:
- Clips MUST be between {min_duration}s and {max_duration}s duration
- Prefer clips that start mid-sentence only if the hook is incredibly strong; otherwise start at a natural speech boundary
- End clips at complete sentences or natural pauses, never mid-word
- Overlapping clips are allowed if different parts are independently viral
- Be selective — only return clips that genuinely score above the threshold; don't pad results
- The "hook" field should be a suggested on-screen text overlay for the first frame (max 8 words, punchy)
""".strip()

# ─── User prompt template ──────────────────────────────────────────────────────

USER_PROMPT_TEMPLATE = """Analyze this video transcript and identify all segments with viral potential scoring {threshold} or above.

## Video Metadata
- **Title**: {title}
- **Channel**: {channel}
- **Total Duration**: {duration_str}

## Transcript (with timestamps in seconds)
{transcript_with_timestamps}

## Task
Find ALL segments that score {threshold}+ on the virality scale.
Return ONLY valid JSON — no markdown, no explanation outside the JSON.

## Required JSON Format
{{
  "clips": [
    {{
      "start": 12.4,
      "end": 47.2,
      "score": 8.7,
      "hook": "Nobody talks about this",
      "suggested_title": "The hidden truth about [topic]",
      "reason": "Strong revelation hook combined with counterintuitive insight. Opens with a direct challenge to common belief, builds tension through personal story, ends with a memorable punchline that begs to be shared.",
      "tags": ["revelation", "controversial", "educational"],
      "criteria_scores": {{
        "hook": 9,
        "share_worthiness": 8,
        "controversy": 7,
        "humor": 3,
        "revelation": 10,
        "relatability": 8,
        "tension": 7,
        "info_value": 9
      }}
    }}
  ],
  "analysis_notes": "Brief overall assessment of the video's viral potential and content themes"
}}

If no segments meet the threshold, return: {{"clips": [], "analysis_notes": "reason why"}}
"""

# ─── Helper functions ──────────────────────────────────────────────────────────

def format_transcript_with_timestamps(words: list[dict]) -> str:
    """
    Agrupa palavras em frases com timestamps e formata para o prompt.

    Agrupa palavras em chunks de ~15 palavras ou até encontrar pontuação
    de fim de frase, mantendo timestamps do início e fim do grupo.
    """
    if not words:
        return "(empty transcript)"

    lines = []
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
            lines.append(f"[{chunk_start:.1f} - {end:.1f}] {line_text}")
            chunk_words = []
            chunk_start = None

    # Flush do último chunk
    if chunk_words and chunk_start is not None:
        end = words[-1]["end"]
        line_text = " ".join(chunk_words)
        lines.append(f"[{chunk_start:.1f} - {end:.1f}] {line_text}")

    return "\n".join(lines)


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
) -> tuple[str, str]:
    """
    Constrói os prompts system e user para análise de viralidade.

    Retorna uma tupla (system_prompt, user_prompt) prontos para envio ao Claude.
    """
    system = SYSTEM_PROMPT.format(
        min_duration=min_duration,
        max_duration=max_duration,
    )

    transcript_text = format_transcript_with_timestamps(words)

    user = USER_PROMPT_TEMPLATE.format(
        title=title,
        channel=channel,
        duration_str=format_duration(duration_seconds),
        transcript_with_timestamps=transcript_text,
        threshold=threshold,
        min_duration=min_duration,
        max_duration=max_duration,
    )

    return system, user
