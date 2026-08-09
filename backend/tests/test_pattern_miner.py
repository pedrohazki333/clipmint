"""
Testes do pattern_miner — apenas a parte determinística (compute_stats).
Não faz chamadas ao Claude.
"""

from prompt_engine.pattern_miner import compute_stats, _format_patterns_text


def _ex(start, end, duration_total, tags, hook, perf="bom", source="external_reference"):
    return {
        "source": source,
        "video": {"duration": duration_total},
        "clip": {
            "start": start,
            "end": end,
            "duration": end - start,
            "hook": hook,
            "tags": tags,
        },
        "validation": {"performance": perf},
    }


def test_empty():
    s = compute_stats([])
    assert s["n_examples"] == 0
    assert s["duration"]["median"] is None
    assert s["cut_position"]["mean"] is None
    assert s["top_tags"] == []


def test_aggregates():
    examples = [
        # corte no início (10/100 = 0.1), 30s, tags humor/revelation
        _ex(10, 40, 100, ["humor", "revelation"], "Isso é absurdo", perf="viral"),
        # corte no meio (60/120 = 0.5), 40s
        _ex(60, 100, 120, ["humor", "storytelling"], "Ninguém esperava isso aqui", perf="bom"),
        # corte no fim (180/200 = 0.9), 20s
        _ex(180, 200, 200, ["revelation"], "Olha o final", perf="muito_bom"),
    ]
    s = compute_stats(examples)

    assert s["n_examples"] == 3
    assert s["sources"] == {"external_reference": 3}
    # durações: 30, 40, 20 → mediana 30, min 20, max 40
    assert s["duration"]["median"] == 30.0
    assert s["duration"]["min"] == 20.0
    assert s["duration"]["max"] == 40.0
    # posições: 0.1 (inicio), 0.5 (meio), 0.9 (fim)
    assert s["cut_position"]["buckets"] == {"inicio": 1, "meio": 1, "fim": 1}
    assert s["cut_position"]["with_duration"] == 3
    assert abs(s["cut_position"]["mean"] - 0.5) < 0.01
    # tags: humor x2 no topo
    assert s["top_tags"][0] == ("humor", 2)
    # performance
    assert s["performance"] == {"viral": 1, "bom": 1, "muito_bom": 1}
    # hook words: 3,4,3 → mediana 3
    assert s["hook_words"]["median"] == 3.0


def test_missing_video_duration_skipped():
    # Exemplo sem video.duration não entra no cálculo de posição, mas conta duração.
    examples = [_ex(10, 40, 0, ["humor"], "hook aqui")]
    s = compute_stats(examples)
    assert s["cut_position"]["with_duration"] == 0
    assert s["cut_position"]["mean"] is None
    assert s["duration"]["median"] == 30.0


def test_format_patterns_text():
    txt = _format_patterns_text(["Regra A", "Regra B"])
    assert "LEARNED PATTERNS" in txt
    assert "- Regra A" in txt
    assert "- Regra B" in txt
