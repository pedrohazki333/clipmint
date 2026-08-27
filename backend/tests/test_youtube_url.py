"""
As duas validações de URL do YouTube têm que responder igual.

O regex existe duas vezes — em `app/schemas.py` (Python) e em
`frontend/src/lib/youtube.ts` (TypeScript) — porque a URL é validada nos dois
lados: no navegador para o erro ser imediato, no servidor porque validação de
cliente não é validação. Divergirem é bug, e foi:

  - o front recusava `youtube.com/shorts/...` e `/live/...` que o backend
    aceita: link válido morria na tela com "URL inválida";
  - o front aceitava `www.youtube.com/watch?v=x` (sem esquema) e
    `https://evil.com/?redir=youtube.com/watch?v=x`, que o backend recusava
    depois do submit.

Este arquivo faz duas coisas: fixa a tabela de casos que ambos têm que
responder igual, e compara os dois regexes CARACTERE A CARACTERE, para a
sincronia não depender de alguém lembrar.
"""

import re
from pathlib import Path

import pytest

from app.schemas import _YOUTUBE_URL_RE

_TS_FILE = (
    Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "youtube.ts"
)

#: (url, é válida?). Os casos de divergência medidos na auditoria de 25/08/2026
#: estão todos aqui.
CASOS = [
    ("https://www.youtube.com/watch?v=abc123", True),
    ("https://youtube.com/watch?v=abc123", True),
    ("https://m.youtube.com/watch?v=abc123", True),
    ("https://youtu.be/abc123", True),
    ("http://www.youtube.com/watch?v=abc123", True),
    # Divergiam: o front recusava os dois
    ("https://www.youtube.com/shorts/abc123", True),
    ("https://www.youtube.com/live/abc123", True),
    # Divergiam: o front aceitava os três
    ("www.youtube.com/watch?v=abc123", False),
    ("https://evil.com/?redir=youtube.com/watch?v=abc", False),
    ("lixo aleatorio youtu.be/ mais lixo", False),
    # Endereço sem o identificador do vídeo. Antes passava nos dois validadores
    # E no extract_info do yt-dlp (que o resolve para uma URL sem id nenhum):
    # virava um job que baixava nada e falhava sem explicar. Verificado contra o
    # yt-dlp real em 25/08/2026.
    ("https://youtu.be/", False),
    ("https://www.youtube.com/watch?", False),
    ("https://www.youtube.com/watch?v=", False),
    ("https://www.youtube.com/shorts/", False),
    ("https://www.youtube.com/live/", False),
    # Com id, seguem válidos — inclusive com o `v=` depois de outro parâmetro,
    # que é como o YouTube monta link de dentro de playlist.
    ("https://youtu.be/dQw4w9WgXcQ", True),
    ("https://www.youtube.com/watch?list=PLabc&v=dQw4w9WgXcQ", True),
    ("https://www.youtube.com/shorts/abc123", True),
    # Nunca foram válidos
    ("", False),
    ("https://vimeo.com/12345", False),
    ("ftp://youtube.com/watch?v=abc", False),
]


@pytest.mark.parametrize("url,valida", CASOS)
def test_regex_do_backend(url, valida):
    assert bool(_YOUTUBE_URL_RE.match(url.strip())) is valida


def _regex_do_frontend() -> str:
    """Extrai o literal do regex do arquivo TypeScript."""
    fonte = _TS_FILE.read_text(encoding="utf-8")
    achado = re.search(r"const YOUTUBE_URL_RE\s*=\s*\n?\s*/(.+?)/;", fonte, re.S)
    assert achado, f"não encontrei o regex em {_TS_FILE}"
    return achado.group(1).strip()


@pytest.mark.parametrize("url,valida", CASOS)
def test_regex_do_frontend(url, valida):
    """O mesmo padrão, aplicado pelo motor de regex do Python."""
    # Em TypeScript a barra precisa ser escapada por estar dentro de /.../;
    # em Python não. É a única diferença permitida entre as duas cópias.
    padrao = _regex_do_frontend().replace(r"\/", "/")
    assert bool(re.match(padrao, url.strip())) is valida


def test_os_dois_regexes_sao_o_mesmo_texto():
    """
    A guarda que dispensa boa vontade.

    Sem isto, "mantenha as duas cópias iguais" é um comentário que alguém
    esquece de ler. Aqui, mexer num lado e não no outro quebra o teste.
    """
    frontend = _regex_do_frontend().replace(r"\/", "/")
    assert frontend == _YOUTUBE_URL_RE.pattern, (
        "os regexes divergiram:\n"
        f"  backend : {_YOUTUBE_URL_RE.pattern}\n"
        f"  frontend: {frontend}"
    )
