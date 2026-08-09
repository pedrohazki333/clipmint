"""
Pattern miner — destila heurísticas concretas a partir dos exemplos validados.

Enquanto o PromptBuilder injeta exemplos individuais como calibração (few-shot),
o miner olha o CONJUNTO de exemplos e extrai padrões agregados persistentes:
distribuição de duração, posição normalizada do corte no vídeo, tags recorrentes
e estilo de hook. Esses agregados são resumidos pelo Claude em poucas diretrizes
imperativas e gravados em learned_patterns.json, que o PromptBuilder passa a
anexar ao system prompt de TODAS as análises seguintes.

Separação:
  - compute_stats(): puro e determinístico (testável sem rede).
  - mine_and_write(): chama o Claude para destilar as diretrizes e persiste.
"""

import json
import logging
import statistics
from collections import Counter
from pathlib import Path
from typing import Optional

import anthropic

from app.config import settings

logger = logging.getLogger(__name__)

_EXAMPLES_DIR = Path(__file__).parent / "examples" / "validated"
_LEARNED_PATH = Path(__file__).parent / "learned_patterns.json"

# Buckets de posição do corte no vídeo (início/meio/fim)
_EARLY = 1 / 3
_LATE = 2 / 3


def load_validated_examples() -> list[dict]:
    """Carrega todos os JSONs válidos de examples/validated/."""
    if not _EXAMPLES_DIR.exists():
        return []
    examples: list[dict] = []
    for path in sorted(_EXAMPLES_DIR.glob("*.json")):
        try:
            examples.append(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Skipping invalid example file {path.name}: {e}")
    return examples


def _median(values: list[float]) -> Optional[float]:
    return round(statistics.median(values), 1) if values else None


def compute_stats(examples: list[dict]) -> dict:
    """
    Computa agregados determinísticos sobre os exemplos validados.

    Retorna um dict com contagens e distribuições — seguro mesmo com campos
    ausentes (exemplos antigos podem não ter video.duration).
    """
    n = len(examples)
    durations: list[float] = []
    positions: list[float] = []          # start / video.duration ∈ [0,1]
    hook_word_counts: list[int] = []
    tag_counter: Counter = Counter()
    perf_counter: Counter = Counter()
    source_counter: Counter = Counter()

    for ex in examples:
        clip = ex.get("clip", {})
        video = ex.get("video", {})
        val = ex.get("validation", {})

        start = float(clip.get("start", 0) or 0)
        end = float(clip.get("end", 0) or 0)
        dur = float(clip.get("duration", end - start) or 0)
        if dur > 0:
            durations.append(dur)

        vid_dur = float(video.get("duration", 0) or 0)
        if vid_dur > 0:
            positions.append(max(0.0, min(1.0, start / vid_dur)))

        hook = (clip.get("hook") or "").strip()
        if hook:
            hook_word_counts.append(len(hook.split()))

        for tag in clip.get("tags", []) or []:
            tag_counter[tag] += 1

        perf_counter[val.get("performance", "bom")] += 1
        source_counter[ex.get("source", "own_clip")] += 1

    position_buckets = {"inicio": 0, "meio": 0, "fim": 0}
    for p in positions:
        if p < _EARLY:
            position_buckets["inicio"] += 1
        elif p < _LATE:
            position_buckets["meio"] += 1
        else:
            position_buckets["fim"] += 1

    return {
        "n_examples": n,
        "sources": dict(source_counter),
        "duration": {
            "median": _median(durations),
            "min": round(min(durations), 1) if durations else None,
            "max": round(max(durations), 1) if durations else None,
            "count": len(durations),
        },
        "cut_position": {
            "with_duration": len(positions),
            "mean": round(statistics.mean(positions), 2) if positions else None,
            "buckets": position_buckets,
        },
        "hook_words": {
            "median": _median([float(x) for x in hook_word_counts]),
            "max": max(hook_word_counts) if hook_word_counts else None,
        },
        "top_tags": tag_counter.most_common(8),
        "performance": dict(perf_counter),
    }


def _sample_hooks(examples: list[dict], limit: int = 8) -> list[str]:
    hooks = [(ex.get("clip", {}).get("hook") or "").strip() for ex in examples]
    return [h for h in hooks if h][:limit]


def _sample_reasons(examples: list[dict], limit: int = 5) -> list[str]:
    out: list[str] = []
    for ex in examples:
        r = (ex.get("clip", {}).get("reason") or "").strip()
        apr = (ex.get("validation", {}).get("aprendizado") or "").strip()
        text = apr or r
        if text:
            out.append(text)
        if len(out) >= limit:
            break
    return out


_SYSTEM = """You distill reusable clip-selection heuristics from a set of real short-form clips that performed well. You are given aggregate statistics plus sample hooks and rationales. Produce a SHORT list of concrete, imperative guidelines that a viral-clip-selection AI should follow — grounded in the data provided, specific, and non-generic. Do not restate raw numbers verbatim as trivia; translate them into actionable selection rules."""

_USER_TEMPLATE = """Here is what worked across {n} validated example clip(s).

## Aggregate stats
{stats}

## Sample hooks that worked
{hooks}

## Sample rationales / lessons
{reasons}

## Task
Return ONLY valid JSON, no markdown:
{{
  "patterns": [
    "Imperative guideline 1 grounded in the data",
    "Imperative guideline 2",
    "..."
  ]
}}
Return between 3 and 6 guidelines. If the data is too sparse to be confident, return fewer but still useful ones."""


def _parse(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    return json.loads(raw)


def _format_patterns_text(patterns: list[str]) -> str:
    """Formata a lista de diretrizes como seção pronta para o system prompt."""
    lines = [
        "## LEARNED PATTERNS (distilled from clips that performed well)",
        "Apply these calibrated guidelines when selecting and cutting clips:",
        "",
    ]
    lines += [f"- {p}" for p in patterns]
    return "\n".join(lines)


async def mine_and_write(examples: list[dict]) -> dict:
    """
    Destila padrões dos exemplos via Claude e persiste em learned_patterns.json.

    Retorna o dict persistido: {patterns_text, patterns, stats, n_examples, generated_at}.
    """
    from datetime import datetime, timezone

    stats = compute_stats(examples)

    system = _SYSTEM
    user = _USER_TEMPLATE.format(
        n=stats["n_examples"],
        stats=json.dumps(stats, ensure_ascii=False, indent=2),
        hooks="\n".join(f"- {h}" for h in _sample_hooks(examples)) or "(none)",
        reasons="\n".join(f"- {r}" for r in _sample_reasons(examples)) or "(none)",
    )

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    message = await client.messages.create(
        model=settings.claude_model,
        max_tokens=1024,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    text_blocks = [b.text for b in message.content if b.type == "text"]
    if not text_blocks:
        raise RuntimeError(f"Claude returned no text (stop_reason={message.stop_reason})")

    parsed = _parse(text_blocks[0])
    patterns = [p.strip() for p in parsed.get("patterns", []) if p.strip()]
    if not patterns:
        raise RuntimeError("Claude returned no patterns")

    result = {
        "patterns": patterns,
        "patterns_text": _format_patterns_text(patterns),
        "stats": stats,
        "n_examples": stats["n_examples"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    _LEARNED_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"Mined {len(patterns)} learned pattern(s) from {stats['n_examples']} example(s)")
    return result


def load_learned() -> Optional[dict]:
    """Retorna o conteúdo persistido de learned_patterns.json, ou None."""
    if not _LEARNED_PATH.exists():
        return None
    try:
        return json.loads(_LEARNED_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Could not read learned_patterns.json: {e}")
        return None


def clear_learned() -> bool:
    """Remove learned_patterns.json. Retorna True se removeu."""
    if _LEARNED_PATH.exists():
        _LEARNED_PATH.unlink()
        return True
    return False
