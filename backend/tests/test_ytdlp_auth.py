"""
Autenticação do yt-dlp: cookies e proxy chegando aos DOIS lugares.

O que estes testes guardam é uma simetria. Num servidor de datacenter o YouTube
recusa tudo com "Sign in to confirm you're not a bot", e a saída (cookies ou
proxy) precisa valer igual para a consulta de metadados e para o download.

Configurar só um dos dois é pior que não configurar nenhum: a consulta passaria,
o job nasceria, o crédito seria reservado, e o download falharia minutos depois
— cobrando ao usuário a espera de um erro conhecido desde o primeiro segundo.
Por isso os testes verificam o dicionário que CADA UM entrega ao yt-dlp, e não
só a função que monta a base.
"""

import pytest

from app.config import settings
from app.utils import ytdlp


@pytest.fixture
def cookies(tmp_path):
    arquivo = tmp_path / "cookies.txt"
    arquivo.write_text("# Netscape HTTP Cookie File\n")
    return arquivo


# ─── A base ───────────────────────────────────────────────────────────────────


def test_sem_configuracao_nao_inventa_nada(monkeypatch):
    """Numa máquina doméstica nada disso é preciso, e o padrão é não mexer."""
    monkeypatch.setattr(settings, "ytdlp_cookies_file", "")
    monkeypatch.setattr(settings, "ytdlp_proxy", "")
    opts = ytdlp.base_opts()

    assert "cookiefile" not in opts
    assert "proxy" not in opts
    assert opts["quiet"] is True


def test_cookies_existentes_entram(monkeypatch, cookies):
    monkeypatch.setattr(settings, "ytdlp_cookies_file", str(cookies))
    monkeypatch.setattr(settings, "ytdlp_proxy", "")
    assert ytdlp.base_opts()["cookiefile"] == str(cookies)


def test_caminho_errado_nao_entra_e_reclama_alto(monkeypatch):
    """Um typo no .env faria o YouTube recusar, e ninguém ligaria uma coisa à outra.

    O erro é capturado interceptando o logger do módulo, e não pelo `caplog`:
    algum outro teste da suíte mexe na configuração global de logging, e o
    `caplog` voltava vazio quando o arquivo rodava junto dos demais — passando
    isolado e falhando em conjunto, que é o pior tipo de teste.
    """
    monkeypatch.setattr(settings, "ytdlp_cookies_file", "/caminho/que/nao/existe.txt")
    monkeypatch.setattr(settings, "ytdlp_proxy", "")

    reclamacoes = []
    monkeypatch.setattr(ytdlp.logger, "error", lambda *a, **k: reclamacoes.append(a))

    opts = ytdlp.base_opts()

    assert "cookiefile" not in opts
    assert reclamacoes, "o caminho errado passou em silêncio"
    assert "não existe" in reclamacoes[0][0]


def test_proxy_entra(monkeypatch):
    monkeypatch.setattr(settings, "ytdlp_cookies_file", "")
    monkeypatch.setattr(settings, "ytdlp_proxy", "http://user:pw@proxy:8080")
    assert ytdlp.base_opts()["proxy"] == "http://user:pw@proxy:8080"


# ─── A simetria, que é o que importa ──────────────────────────────────────────


def _capturar_opts(monkeypatch, modulo):
    """Intercepta o dicionário que o módulo entrega ao yt-dlp."""
    capturado = {}

    class FakeYDL:
        def __init__(self, opts):
            capturado.update(opts)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download=False):
            return {"duration": 300, "title": "t"}

    monkeypatch.setattr(modulo.yt_dlp, "YoutubeDL", FakeYDL)
    return capturado


def test_a_consulta_de_metadados_usa_os_cookies(monkeypatch, cookies):
    from app.services import quota

    monkeypatch.setattr(settings, "ytdlp_cookies_file", str(cookies))
    monkeypatch.setattr(settings, "ytdlp_proxy", "")
    opts = _capturar_opts(monkeypatch, quota)

    quota._probe_sync("https://youtu.be/x")

    assert opts["cookiefile"] == str(cookies)
    assert opts["skip_download"] is True


def test_o_download_usa_os_mesmos_cookies(monkeypatch, cookies, tmp_path):
    from app.services import downloader

    monkeypatch.setattr(settings, "ytdlp_cookies_file", str(cookies))
    monkeypatch.setattr(settings, "ytdlp_proxy", "")
    opts = _capturar_opts(monkeypatch, downloader)

    downloader._download_sync("https://youtu.be/x", str(tmp_path / "v.mp4"))

    assert opts["cookiefile"] == str(cookies)
    # E não perdeu o que já tinha.
    assert opts["merge_output_format"] == "mp4"
    assert "bestvideo" in opts["format"]


def test_os_dois_recebem_o_mesmo_proxy(monkeypatch, tmp_path):
    """Se um sair por outro IP e o outro não, o job nasce e morre no download."""
    from app.services import downloader, quota

    monkeypatch.setattr(settings, "ytdlp_cookies_file", "")
    monkeypatch.setattr(settings, "ytdlp_proxy", "socks5://10.0.0.1:1080")

    consulta = _capturar_opts(monkeypatch, quota)
    quota._probe_sync("https://youtu.be/x")

    baixa = _capturar_opts(monkeypatch, downloader)
    downloader._download_sync("https://youtu.be/x", str(tmp_path / "v.mp4"))

    assert consulta["proxy"] == baixa["proxy"] == "socks5://10.0.0.1:1080"
