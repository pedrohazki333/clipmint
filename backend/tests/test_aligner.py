"""
Testes do aligner — localização de um clipe dentro do vídeo original.

Não faz chamadas externas: usa streams de palavras sintéticos para validar o
mapeamento de intervalo, a exclusão de intro/outro e o cálculo de confiança.
"""

from app.services.aligner import align_clip_to_source, _normalize


def _words(pairs):
    """Constrói lista de word-dicts a partir de (text, start, end)."""
    return [{"text": t, "start": s, "end": e, "confidence": 0.99} for t, s, e in pairs]


# Vídeo original sintético: 20 palavras, uma por segundo.
SOURCE = _words([
    ("O", 0.0, 0.4), ("assunto", 0.5, 1.0), ("de", 1.1, 1.3), ("hoje", 1.4, 1.9),
    ("comeca", 2.0, 2.6), ("devagar", 2.7, 3.4),
    ("mas", 4.0, 4.3), ("entao", 4.4, 4.9), ("ele", 5.0, 5.3), ("revela", 5.4, 6.0),
    ("algo", 6.1, 6.5), ("absurdo", 6.6, 7.3), ("que", 7.4, 7.7), ("ninguem", 7.8, 8.4),
    ("esperava", 8.5, 9.2),
    ("e", 10.0, 10.2), ("depois", 10.3, 10.9), ("volta", 11.0, 11.5),
    ("ao", 11.6, 11.8), ("normal.", 11.9, 12.5),
])


def test_normalize_strips_accents_and_punctuation():
    assert _normalize("Então!") == "entao"
    assert _normalize("ABSURDO,") == "absurdo"
    assert _normalize("...") == ""


def test_locates_middle_segment():
    # Clipe = trecho "mas então ele revela algo absurdo que ninguém esperava"
    # (índices 6..14 no source), re-timestampado a partir de 0 como faria o ASR do clipe.
    clip = _words([
        ("mas", 0.0, 0.3), ("entao", 0.4, 0.9), ("ele", 1.0, 1.3), ("revela", 1.4, 2.0),
        ("algo", 2.1, 2.5), ("absurdo", 2.6, 3.3), ("que", 3.4, 3.7), ("ninguem", 3.8, 4.4),
        ("esperava", 4.5, 5.2),
    ])
    r = align_clip_to_source(clip, SOURCE)
    assert r is not None
    assert r.source_start == 4.0        # início da palavra "mas" no original
    assert r.source_end == 9.2          # fim de "esperava" no original
    assert r.confidence == 1.0          # todos os tokens do clipe casaram


def test_excludes_added_intro():
    # Clipe com vinheta/intro que NÃO existe no original + o mesmo trecho do meio.
    clip = _words([
        ("inscrevase", 0.0, 0.6), ("no", 0.7, 0.9), ("canal", 1.0, 1.5),   # intro estranha
        ("ele", 2.0, 2.3), ("revela", 2.4, 3.0), ("algo", 3.1, 3.5),
        ("absurdo", 3.6, 4.3), ("que", 4.4, 4.7), ("ninguem", 4.8, 5.4),
    ])
    r = align_clip_to_source(clip, SOURCE)
    assert r is not None
    # O span deve começar em "ele" (5.0), não na intro inexistente.
    assert r.source_start == 5.0
    assert r.source_end == 8.4          # fim de "ninguem"
    # 6 de 9 tokens do clipe casaram (a intro de 3 tokens não).
    assert 0.6 <= r.confidence <= 0.7


def test_tolerates_asr_variation():
    # Uma palavra transcrita diferente ("revelou" em vez de "revela") não impede o alinhamento.
    clip = _words([
        ("entao", 0.0, 0.5), ("ele", 0.6, 0.9), ("revelou", 1.0, 1.6),   # variação
        ("algo", 1.7, 2.1), ("absurdo", 2.2, 2.9),
    ])
    r = align_clip_to_source(clip, SOURCE)
    assert r is not None
    assert r.source_start == 4.4        # "entao"
    assert r.source_end == 7.3          # "absurdo"
    assert r.confidence >= 0.8


def test_empty_returns_none():
    assert align_clip_to_source([], SOURCE) is None
    assert align_clip_to_source(SOURCE, []) is None


def test_discards_spurious_distant_block():
    # Reproduz o caso real (Podpah): o clipe abre com um par de palavras comuns
    # que também aparece muito antes no original. Como o ASR transcreveu a 2ª
    # palavra do trecho verdadeiro de forma diferente, o matcher casa o par lá
    # atrás — e o span esticava do bloco espúrio até o fim do trecho real
    # (41 min para um clipe de 16s). O bloco espúrio tem deslocamento
    # clip→source incompatível com o âncora e deve ser descartado.
    filler = [(f"filler{i}", 10.0 + i, 10.4 + i) for i in range(80)]
    source = _words([
        ("voce", 0.0, 0.4), ("quis", 0.5, 0.9),            # ocorrência espúria, no início
        *filler,
        ("voce", 100.0, 100.4), ("queria", 100.5, 100.9),  # trecho real ("quis" → "queria")
        ("vencer", 101.0, 101.5), ("de", 101.6, 101.8), ("verdade", 101.9, 102.4),
        ("nao", 102.5, 102.8), ("tinha", 102.9, 103.3), ("outra", 103.4, 103.8),
        ("escolha", 103.9, 104.5), ("ali", 104.6, 105.0),
    ])
    clip = _words([
        ("voce", 0.0, 0.4), ("quis", 0.5, 0.9), ("vencer", 1.0, 1.5),
        ("de", 1.6, 1.8), ("verdade", 1.9, 2.4), ("nao", 2.5, 2.8),
        ("tinha", 2.9, 3.3), ("outra", 3.4, 3.8), ("escolha", 3.9, 4.5),
        ("ali", 4.6, 5.0),
    ])
    r = align_clip_to_source(clip, source)
    assert r is not None
    # O span deve cobrir só o trecho real, não começar no par espúrio (0.0s).
    assert r.source_start == 101.0      # início de "vencer"
    assert r.source_end == 105.0        # fim de "ali"
    # 8 de 10 tokens casaram no trecho real; os 2 do bloco espúrio foram descartados.
    assert r.confidence == 0.8
