"""
Vocabulário de risco no banner e no título.

A checagem é warn-only, então falso positivo custa barato e falso NEGATIVO é o
que importa: a palavra que passa batido vai queimada no vídeo.
"""

import pytest

from app.services.moderation_terms import RISKY_TERMS, find_risky_terms, prompt_rule


@pytest.mark.parametrize("text,expected", [
    ("Com uma arma fico violento demais", ["arma"]),
    ("Ele matou o time inteiro", ["matou"]),
    ("Ele matava todo mundo sozinho", ["matava"]),
    ("O time inteiro morreu na caverna", ["morreu"]),
    ("Ele farmava enquanto o time morria", ["morria"]),
    ("Levou um tiro pelas costas", ["tiro"]),
    ("Cena de morte mais absurda do ano", ["morte"]),
])
def test_pega_a_flexao_que_o_modelo_escrever(text, expected):
    assert find_risky_terms(text) == expected


@pytest.mark.parametrize("text", [
    "Achei que era item bom — era uma armadilha",
    "Levei um susto e virei lobisomem no jogo de terror",
    "Se escondeu no matagal e ninguém achou",
    "Farmou a noite toda e não levou nada",
])
def test_nao_marca_palavra_que_so_parece(text):
    """
    'armadilha' e 'matagal' contêm os radicais e são inofensivas — é o que a
    fronteira de palavra existe para separar.
    """
    assert find_risky_terms(text) == []


def test_nao_repete_a_mesma_palavra():
    assert find_risky_terms("arma, arma e mais arma") == ["arma"]


def test_texto_vazio_ou_ausente_nao_quebra():
    assert find_risky_terms(None) == []
    assert find_risky_terms("") == []


def test_a_regra_do_prompt_lista_as_palavras_em_portugues():
    """
    O modelo lê a regra; regex crua ali é ruído. E a lista tem que sair da
    mesma tabela da checagem, senão prompt e aviso divergem com o tempo.
    """
    rule = prompt_rule()

    assert "(?:" not in rule, "vazou regex para o texto que o modelo lê"
    for _, words, hint in RISKY_TERMS:
        assert words in rule
        assert hint in rule


def test_a_regra_restringe_so_os_campos_publicos():
    """`reason` e afins são notas internas — cortar palavra ali cega a análise."""
    rule = prompt_rule()

    assert "suggested_hook_caption" in rule and "suggested_title" in rule
    assert "reason" in rule and "weak_points" in rule
