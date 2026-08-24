"""
Testes da varredura de candidatos (passada 1 do compilado).

Nada aqui chama a API: o que se verifica é a higienização das janelas que o
modelo devolve, porque é ela que decide o que a visão vai olhar — e olhar a
janela errada custa uma chamada de visão e um momento perdido.

O caso de referência é o compilado real do alanzoka (Grain Rot): dos seis
trechos escolhidos por um editor humano, dois eram fala contínua e não viravam
janela pelo caminho antigo (buracos de áudio). Esta passada existe por causa
deles.
"""

from app.prompts.viral_analysis import format_observation
from app.services.candidates import (
    _MAX_WINDOW,
    _MIN_WINDOW,
    Observation,
    _clean,
    _menu,
    _resolve,
    _speech_in,
)

DURATION = 6593.0


def test_janela_curta_demais_e_esticada():
    """Poucos segundos não dão quadros suficientes para comparar o que mudou."""
    got = _clean([{"start": 100.0, "end": 102.0}], DURATION)

    assert len(got) == 1
    assert got[0].duration == _MIN_WINDOW


def test_janela_longa_demais_e_aparada():
    """Janela grande vira 'o assunto' e dilui o que mudou entre os quadros."""
    got = _clean([{"start": 100.0, "end": 400.0}], DURATION)

    assert got[0].duration == _MAX_WINDOW


def test_janelas_sobrepostas_viram_uma():
    """Dois candidatos no mesmo acontecimento gastariam duas chamadas de visão."""
    got = _clean(
        [{"start": 3840.0, "end": 3852.0}, {"start": 3845.0, "end": 3860.0}], DURATION
    )

    assert len(got) == 1
    assert (got[0].start, got[0].end) == (3840.0, 3860.0)


def test_janelas_vizinhas_mas_separadas_sobrevivem():
    """Encostar não é sobrepor — acontecimentos seguidos continuam dois."""
    got = _clean(
        [{"start": 100.0, "end": 110.0}, {"start": 110.0, "end": 120.0}], DURATION
    )

    assert len(got) == 2


def test_janela_impossivel_e_descartada():
    """Fim antes do começo, tempo negativo ou depois do fim do vídeo."""
    got = _clean(
        [
            {"start": 50.0, "end": 20.0},
            {"start": -10.0, "end": 30.0},
            {"start": DURATION + 5, "end": DURATION + 20},
            {"start": "abc", "end": "def"},
            "nem é dict",
        ],
        DURATION,
    )

    assert got == []


def test_janela_estourando_o_fim_do_video_e_encolhida():
    got = _clean([{"start": DURATION - 4, "end": DURATION + 100}], DURATION)

    assert got[0].end == DURATION


def test_saida_vem_em_ordem_de_tempo():
    got = _clean(
        [{"start": 3000.0, "end": 3020.0}, {"start": 100.0, "end": 120.0}], DURATION
    )

    assert [o.start for o in got] == [100.0, 3000.0]


def test_anotacao_usa_a_imagem_quando_existe():
    """
    A descrição visual é o motivo de a passada existir.

    Sem ela o modelo escolhe sem enxergar o que acontece na tela nos momentos
    em que ninguém para de falar.
    """
    line = format_observation(
        Observation(3840.0, 3852.0, "risada", scene="um personagem pequeno atravessa a tela")
    )

    assert "NA IMAGEM: um personagem pequeno atravessa a tela" in line
    assert "3840.0 - 3852.0" in line


def test_anotacao_cai_para_o_texto_sem_imagem():
    """Visão desligada ou falha: a justificativa da varredura ainda informa."""
    line = format_observation(Observation(100.0, 110.0, "gritaria coletiva"))

    assert "gritaria coletiva" in line


def test_candidato_sem_nada_a_dizer_nao_vira_linha():
    assert format_observation(Observation(100.0, 110.0)) == ""


# ─── Montagem por número de momento ───────────────────────────────────────────

MOMENTS = [Observation(100.0, 112.0), Observation(2780.6, 2800.6), Observation(3843.4, 3851.5)]


def test_ordem_entregue_pelo_modelo_e_a_montagem():
    """
    Escolher 3, 1, 2 significa abrir pelo terceiro momento.

    A ordem é editorial — é ela que põe a risada mais forte na abertura mesmo
    quando ela acontece no fim do vídeo.
    """
    assert _resolve([3, 1, 2], MOMENTS) == [(3843.4, 3851.5), (100.0, 112.0), (2780.6, 2800.6)]


def test_numero_invalido_nao_derruba_o_compilado():
    """Um número fora da lista some; o resto da montagem continua de pé."""
    assert _resolve([3, 99, 0, -2, "x", None, 1], MOMENTS) == [(3843.4, 3851.5), (100.0, 112.0)]


def test_numero_repetido_entra_uma_vez_so():
    """O mesmo momento duas vezes seria o mesmo vídeo colado em si mesmo."""
    assert _resolve([2, 2, 2], MOMENTS) == [(2780.6, 2800.6)]


def test_resposta_que_nao_e_lista_nao_quebra():
    assert _resolve("dois e três", MOMENTS) == []
    assert _resolve(None, MOMENTS) == []


def test_cardapio_numera_a_partir_de_um():
    """
    O número é a única forma de referenciar um momento.

    Numerar do zero faria o modelo escolher '1' pensando no primeiro e receber
    o segundo — um erro silencioso que só apareceria no vídeo montado.
    """
    words = [{"text": "olha", "start": 101.0, "end": 101.4}]
    menu = _menu(MOMENTS, words)

    assert "### Momento 1 — 100.0s a 112.0s" in menu
    assert "### Momento 3 — 3843.4s a 3851.5s" in menu
    assert "Momento 0" not in menu


def test_cardapio_mostra_a_fala_do_momento():
    words = [
        {"text": "que", "start": 101.0, "end": 101.2},
        {"text": "isso", "start": 101.3, "end": 101.6},
        {"text": "longe", "start": 5000.0, "end": 5000.4},
    ]

    assert _speech_in(words, 100.0, 112.0) == "que isso"
    assert _speech_in(words, 100.0, 112.0) not in _speech_in(words, 4990.0, 5010.0)


def test_momento_sem_fala_nao_quebra_o_cardapio():
    """Piada muda: o momento vale pela imagem, não pela fala."""
    menu = _menu([Observation(3843.4, 3851.5, why="risada", scene="alguém atravessa a tela")], [])

    assert "Na imagem: alguém atravessa a tela" in menu
    assert "Fala:" not in menu
