"""
Vocabulário que é melhor não escrever no banner nem no título do clipe.

## O que é documentado e o que não é

O TikTok **não publica lista de palavras proibidas**. As Community Guidelines
descrevem CATEGORIAS de conteúdo (conteúdo violento e chocante, armas como
"regulated goods", ameaça e incitação, suicídio e automutilação), e as "For You
feed Eligibility Standards" descrevem um segundo nível, mais brando e mais
perigoso para quem posta: conteúdo que não é removido, mas fica **inelegível
para a For You** — some do alcance sem aviso e sem strike.

Ou seja: não dá para confirmar que "arma" ou "morte" são censuradas. O que dá
para afirmar é que existe um mecanismo de perda de alcance sem remoção, que a
moderação é automatizada e lê o texto junto do vídeo, e que a prática de trocar
essas palavras ("algospeak" — "unalive" no lugar de "kill") é documentada em
pesquisa revisada por pares como resposta dos criadores a moderação por
palavra-chave.

## Por que evitar mesmo assim

O custo de escrever "levei um susto" em vez de "quase morri" é zero: o banner
diz a mesma coisa. O custo de errar é um clipe bom sem alcance. Com assimetria
dessas, evitar é a escolha barata — mas é **precaução, não regra do TikTok**, e
é assim que deve ser tratada quando alguém perguntar por que o título mudou.

O escopo é o grupo que o canal mais encosta: violência, arma e morte, mais
automutilação (a categoria de tolerância zero). Não é filtro de palavrão nem de
conteúdo adulto — esses o prompt já trata em outro lugar.

Vale lembrar do limite deste arquivo: ele cuida do TEXTO. A fala do streamer
continua na legenda queimada e no áudio, e nada aqui a alcança. O que se ganha
é o texto que a plataforma lê primeiro — banner e título —, não o clipe inteiro.
"""

import re

# Cada entrada: radical em regex, como se escreve em português, e para onde
# reescrever. As duas últimas colunas existem para o PROMPT — mostrar regex crua
# ao modelo é pedir que ele adivinhe o que `(?:...)` quer dizer. A sugestão fala
# em reescrever a FRASE, nunca a palavra no lugar: substituição automática
# produz português torto ("Com uma 🔫 fico violento demais") e ainda estraga a
# frase que o hook é.
RISKY_TERMS: list[tuple[str, str, str]] = [
    (r"arma(?:s|do|da|dos|das)?",
     "arma, armas, armado",
     "o equipamento, o item, 'isso na mão'"),
    (r"mat(?:ar|ou|a|am|ei|o|aram|ava|avam|ando|ador|adores)",
     "matar, matou, mata, matei, matando",
     "eliminar, derrubar, acabar com"),
    (r"mort(?:e|es|o|a|os|as|al)",
     "morte, morto, mortal",
     "o fim, o susto, 'não sobrou nada'"),
    (r"morr(?:er|eu|i|e|em|eram|ia|iam|endo)",
     "morrer, morreu, morri, morria",
     "cair, apagar, não escapar"),
    (r"tiro(?:s)?|atir(?:ar|ou|ei|a|am|ando)",
     "tiro, tiros, atirar, atirou",
     "acertar em cheio, pegar de jeito"),
    (r"assassin(?:o|a|os|as|ato|atos|ar|ou)",
     "assassino, assassinato",
     "o culpado, quem fez"),
    (r"sangue|sangrent(?:o|a|os|as)",
     "sangue, sangrento",
     "o estrago, a cena pesada"),
    (r"suic[íi]di(?:o|os)|suicid(?:a|ar|ou)",
     "suicídio, suicida",
     "nunca escrever — reformular o momento inteiro"),
]

# Um só regex, com fronteira de palavra dos dois lados. Sem a fronteira, "mata"
# casaria dentro de "matagal" e "arma" dentro de "armadilha" — e "armadilha" é
# justamente uma palavra que os clipes de terror usam à vontade.
_PATTERN = re.compile(
    r"\b(?:" + "|".join(stem for stem, _, _ in RISKY_TERMS) + r")\b",
    re.IGNORECASE | re.UNICODE,
)


def find_risky_terms(text: str | None) -> list[str]:
    """
    As palavras de risco que aparecem no texto, na ordem, sem repetir.

    Casa por radical, então pega a flexão que o modelo inventar ("matou",
    "matando"). Falso positivo é possível e aceitável — "mata atlântica" cai
    aqui — porque o retorno vira AVISO, nunca reescrita automática.
    """
    if not text:
        return []
    seen: list[str] = []
    for match in _PATTERN.finditer(text):
        word = match.group(0).lower()
        if word not in seen:
            seen.append(word)
    return seen


def prompt_rule() -> str:
    """
    A regra como o modelo a lê, com a lista embutida.

    Vive aqui, e não escrita à mão no template, para que lista e checagem nunca
    divirjam: se um radical for acrescentado, o prompt aprende junto.
    """
    lines = "\n".join(f"  - {words} → {hint}" for _, words, hint in RISKY_TERMS)
    return (
        "- `suggested_hook_caption` e `suggested_title` são lidos por moderação "
        "automática antes de chegar a gente. Não use o vocabulário de violência, "
        "arma e morte abaixo NESSES DOIS CAMPOS — reescreva a frase inteira com o "
        "sentido intacto, sem abreviar nem trocar letra por símbolo (isso é pior "
        "que a palavra original). Vale escrever o momento pelo EFEITO ('levei um "
        "susto', 'não sobrou nada') em vez do ato.\n"
        f"{lines}\n"
        "  A restrição é só desses dois campos. `reason`, `trim_reason` e "
        "`weak_points` são notas internas, nunca vão para a plataforma, e devem "
        "descrever o trecho com as palavras normais."
    )
