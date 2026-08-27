"""
Testes dos trechos indicados à mão.

Quem marca um momento assistindo anota "3:24 - 4:10", que é o que o player
mostra — não segundos. O que se verifica aqui é que a anotação natural é aceita
como ela vem, que a ORDEM digitada sobrevive (num compilado ela é a montagem) e
que erro de digitação vira mensagem apontando o pedaço errado, não um job caro
que falha depois do download.
"""

import pytest

from app.utils.timecodes import TimecodeError, parse_ranges, parse_timecode
from app.workers.pipeline import _manual_clips


# ─── Leitura do tempo ─────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "text,expected",
    [
        ("3:24", 204.0),
        ("1:02:03", 3723.0),
        ("204", 204.0),
        ("3723", 3723.0),
        ("3:24.5", 204.5),
        ("3:24,5", 204.5),   # vírgula decimal, como se digita em pt-BR
        ("90:00", 5400.0),   # minutos acima de 59: quem anota corrido não converte
        (" 3:24 ", 204.0),
    ],
)
def test_le_o_tempo_como_a_pessoa_escreve(text, expected):
    assert parse_timecode(text) == expected


def test_segundos_de_tres_digitos_sao_tempo_valido():
    """
    Regressão: o padrão aceitava só 1-2 dígitos e recusava "204" como inválido.

    Segundos corridos são a forma que sai de um script ou de uma planilha.
    """
    assert parse_timecode("204") == 204.0
    assert parse_timecode("123456") == 123456.0


# ─── Leitura da lista ─────────────────────────────────────────────────────────

def test_o_caso_do_usuario():
    assert parse_ranges("3:24 - 4:10") == [(204.0, 250.0)]


@pytest.mark.parametrize(
    "text",
    [
        "3:24-4:10, 12:05-12:40",
        "3:24 - 4:10\n12:05 - 12:40",
        "3:24 até 4:10; 12:05 a 12:40",
        "3:24 --> 4:10, 12:05 .. 12:40",
    ],
)
def test_aceita_os_separadores_que_as_pessoas_usam(text):
    assert parse_ranges(text) == [(204.0, 250.0), (725.0, 760.0)]


def test_a_ordem_digitada_e_preservada():
    """
    Num compilado a ordem é a MONTAGEM, não a cronologia.

    Ordenar por tempo aqui destruiria a escolha de abrir por um momento que
    acontece no fim do vídeo — que é como o compilado de referência abre.
    """
    got = parse_ranges("12:05-12:40, 3:24-4:10")

    assert got == [(725.0, 760.0), (204.0, 250.0)]


def test_lista_vazia_nao_e_erro():
    """Não indicar trecho nenhum é o caso normal."""
    assert parse_ranges("") == []
    assert parse_ranges("   \n  ") == []


# ─── Recusas, com mensagem que ajuda ──────────────────────────────────────────

def test_trecho_sem_fim_e_recusado():
    with pytest.raises(TimecodeError, match="início e fim"):
        parse_ranges("3:24")


def test_fim_antes_do_inicio_e_recusado():
    with pytest.raises(TimecodeError, match="depois do início"):
        parse_ranges("4:10 - 3:24")


def test_tempo_ilegivel_diz_qual_pedaco():
    with pytest.raises(TimecodeError, match='"abc"'):
        parse_ranges("abc - 4:10")


def test_trechos_sobrepostos_sao_recusados():
    """
    Sobreposição quase sempre é erro de digitação.

    Fundir em silêncio entregaria um clipe diferente do pedido, e quem indicou
    à mão tem como corrigir.
    """
    with pytest.raises(TimecodeError, match="se sobrepõem"):
        parse_ranges("3:24-4:10, 3:50-4:30")


def test_trecho_curto_demais_para_o_pipeline():
    with pytest.raises(TimecodeError, match="o mínimo é 15s"):
        parse_ranges("3:24-3:30", min_duration=15)


def test_teto_de_quantidade():
    with pytest.raises(TimecodeError, match="o máximo é 3"):
        parse_ranges("1:00-1:20, 2:00-2:20, 3:00-3:20, 4:00-4:20", max_ranges=3)


# ─── Do intervalo ao clipe ────────────────────────────────────────────────────

RANGES = [(725.0, 760.0), (204.0, 250.0)]


def test_compilado_costura_os_trechos_na_ordem_digitada():
    clips = _manual_clips(RANGES, "compilation")

    assert len(clips) == 1
    assert clips[0].segments == RANGES          # 12:05 primeiro, como digitado
    assert clips[0].start == 204.0              # intervalo bruto, não a montagem
    assert clips[0].end == 760.0


def test_modo_individual_gera_um_clipe_por_trecho():
    clips = _manual_clips(RANGES, "individual")

    assert [(c.start, c.end) for c in clips] == RANGES
    assert all(not c.segments for c in clips)


def test_um_trecho_so_nao_vira_compilado():
    """Costura precisa de dois; com um, o compilado é só o clipe."""
    clips = _manual_clips([(204.0, 250.0)], "compilation")

    assert len(clips) == 1
    assert not clips[0].segments


def test_clipe_manual_nao_inventa_titulo():
    """Sem análise não há hook nem título — e banner vazio some no render."""
    clip = _manual_clips(RANGES, "individual")[0]

    assert clip.hook == ""
    assert clip.suggested_title == ""
    assert "manual" in clip.tags


def test_sem_trechos_nao_gera_clipe():
    assert _manual_clips([], "compilation") == []
