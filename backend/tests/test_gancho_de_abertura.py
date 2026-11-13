"""
O gancho de abertura: a fala mais forte do clipe tocada antes do começo dele.

A análise devolve a fala como texto; aqui ela vira tempo, inteira, de 1 a 4 s.
No render, o gancho entra antes do clipe e as legendas dos dois lados ficam no
lugar certo.
"""

from app.services.opening import find_opening
from app.workers.pipeline import _parse_opening_json, _with_opening


def _palavras(texto: str, inicio: float, passo: float = 0.4) -> list[dict]:
    out = []
    t = inicio
    for p in texto.split():
        out.append({"text": p, "start": round(t, 2), "end": round(t + passo - 0.05, 2)})
        t += passo
    return out


FALA = (
    "a gente tava andando na trilha de noite e o guia parou do nada "
    "e falou assim olha ali e era uma onça Pronto, morremo! Eu juro que "
    "pensei que era o fim da expedição"
)
WORDS = _palavras(FALA, 100.0)


def test_acha_a_fala_inteira_com_pontuacao_e_acento_diferentes():
    achado = find_opening(WORDS, 100.0, 120.0, "pronto morremo")
    assert achado is not None
    ini, fim, texto = achado
    assert texto == "Pronto, morremo!"
    pronto = next(w for w in WORDS if w["text"] == "Pronto,")
    morremo = next(w for w in WORDS if w["text"] == "morremo!")
    assert ini < pronto["start"] and fim >= morremo["end"]
    # Duas palavras, menos de um segundo: curto, e é exatamente o gancho que se quer.
    assert 0.6 <= fim - ini < 1.0


def test_palavra_solta_fica_de_fora():
    assert find_opening(WORDS, 100.0, 120.0, "onça") is None


def test_fala_de_tres_segundos_entra():
    achado = find_opening(WORDS, 100.0, 120.0, "era uma onça Pronto, morremo!")
    assert achado is not None
    ini, fim, _ = achado
    assert 1.0 <= fim - ini <= 4.0


def test_fala_longa_demais_e_recusada_em_vez_de_cortada():
    longa = "e falou assim olha ali e era uma onça Pronto, morremo! Eu juro que pensei"
    assert find_opening(WORDS, 100.0, 120.0, longa) is None


def test_fala_que_nao_esta_no_clipe_e_recusada():
    assert find_opening(WORDS, 100.0, 120.0, "o chat chamou uma onça") is None


def test_fala_fora_do_intervalo_do_clipe_e_recusada():
    # A fala existe, mas fora do corte: numa parte de clipe dividido, ela ficou na outra.
    assert find_opening(WORDS, 100.0, 108.0, "era uma onça Pronto, morremo!") is None


def test_abertura_que_ja_e_o_comeco_do_clipe_nao_repete():
    assert find_opening(WORDS, 100.0, 120.0, "a gente tava andando na trilha") is None


def test_sem_abertura_nada_acontece():
    assert find_opening(WORDS, 100.0, 120.0, None) is None
    assert find_opening(WORDS, 100.0, 120.0, "") is None


def test_legendas_do_gancho_e_do_clipe_na_linha_do_tempo_certa():
    gancho = (109.5, 111.8)
    principal = [(100.0, 120.0)]
    total = (gancho[1] - gancho[0]) + 20.0

    palavras = _with_opening(WORDS, gancho, principal, "podcast", "individual", total)

    dur = gancho[1] - gancho[0]
    no_gancho = [w for w in palavras if w["start"] < dur]
    esperadas = [w["text"] for w in WORDS if w["start"] >= gancho[0] and w["end"] <= gancho[1]]
    assert [w["text"] for w in no_gancho] == esperadas
    assert all(0 <= w["start"] < dur for w in no_gancho)

    # Depois do gancho, o clipe começa do início: a primeira palavra do vídeo.
    depois = [w for w in palavras if w["start"] >= dur]
    assert depois[0]["text"] == "a"
    assert abs(depois[0]["start"] - dur) < 0.05


def test_gancho_salvo_e_lido_de_volta():
    assert _parse_opening_json('[109.5, 111.8, "era uma onça"]') == (109.5, 111.8)
    assert _parse_opening_json(None) is None
    assert _parse_opening_json("lixo") is None
