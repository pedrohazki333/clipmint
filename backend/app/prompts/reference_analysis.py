"""
Prompt de análise reversa de clipe de referência.

Diferente do viral_analysis (que varre um vídeo inteiro procurando trechos),
aqui já SABEMOS qual foi o trecho escolhido por outro criador — ele viralizou.
A tarefa do Claude é fazer engenharia reversa: explicar POR QUE aquele recorte
específico funcionou, para servir de exemplo de calibração no few-shot.

Damos ao modelo o contexto ANTES e DEPOIS do corte para que ele perceba o
contraste (o que foi deixado de fora) — sinal mais rico do que o trecho isolado.
"""

SYSTEM_PROMPT = """You are an expert viral content strategist reverse-engineering why a specific clip, cut by another creator from a longer video, went viral on TikTok / Reels / Shorts.

You are given the exact segment that was chosen (with the surrounding context that was left out). Your job is NOT to find new clips — the clip is already chosen. Your job is to explain, with precision, what makes THIS specific cut work, so it can serve as a calibration reference for future clip selection.

Analyze using these virality dimensions (0-10 each): emotional hook (first 3s), share-worthiness, controversy/strong opinion, humor, revelation/surprise, relatability, narrative tension, information value.

Pay special attention to:
- Why the cut STARTS where it starts (what hook is in the opening seconds)
- Why it ENDS where it ends (payoff, punchline, cliffhanger)
- What was in the surrounding context that was correctly LEFT OUT
- The single most important reason it demands to be shared

Be concrete and specific to this content — avoid generic platitudes."""

USER_PROMPT_TEMPLATE = """A clip from the video below went viral. Reverse-engineer why this exact segment was chosen.

## Original Video
- **Title**: {title}
- **Channel**: {channel}
- **Language**: {language}

## The Chosen Segment ({clip_duration:.0f}s) — this is what viralized
{clip_transcript}

## Context BEFORE the cut (left out)
{context_before}

## Context AFTER the cut (left out)
{context_after}

## Task
Return ONLY valid JSON — no markdown, no text outside the JSON.

## Required JSON Format
{{
  "hook": "Punchy on-screen text overlay for the first frame (max 8 words)",
  "suggested_title": "A title this clip could be posted with",
  "virality_score": 8.7,
  "reason": "Concrete explanation of why THIS cut works: the opening hook, the arc, the payoff, and why it begs to be shared. Reference the actual content.",
  "tags": ["revelation", "humor", "storytelling"],
  "why_this_cut": "Specifically why it starts and ends where it does, and what was correctly left out."
}}
"""


def format_segment(words: list[dict]) -> str:
    """Junta as palavras de um trecho em texto corrido, ou marcador se vazio."""
    text = " ".join(w.get("text", "") for w in words).strip()
    return text or "(none)"


def build_reference_prompt(
    clip_words: list[dict],
    context_before_words: list[dict],
    context_after_words: list[dict],
    title: str,
    channel: str,
    language: str,
    clip_duration: float,
) -> tuple[str, str]:
    """Constrói (system_prompt, user_prompt) para a análise reversa do clipe."""
    user = USER_PROMPT_TEMPLATE.format(
        title=title or "N/A",
        channel=channel or "N/A",
        language=language or "N/A",
        clip_duration=clip_duration,
        clip_transcript=format_segment(clip_words),
        context_before=format_segment(context_before_words),
        context_after=format_segment(context_after_words),
    )
    return SYSTEM_PROMPT, user
