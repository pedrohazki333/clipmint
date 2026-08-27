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

from pathlib import Path

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
    entregue = ytdlp.base_opts()["cookiefile"]
    assert Path(entregue).read_text() == cookies.read_text()


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

    # O caminho é o de uma cópia (ver _copia_descartavel); o que precisa bater
    # é o conteúdo.
    assert opts["cookiefile"] != str(cookies)
    assert Path(opts["cookiefile"]).read_text() == cookies.read_text()
    assert opts["skip_download"] is True


def test_o_download_usa_os_mesmos_cookies(monkeypatch, cookies, tmp_path):
    from app.services import downloader

    monkeypatch.setattr(settings, "ytdlp_cookies_file", str(cookies))
    monkeypatch.setattr(settings, "ytdlp_proxy", "")
    opts = _capturar_opts(monkeypatch, downloader)

    downloader._download_sync("https://youtu.be/x", str(tmp_path / "v.mp4"))

    assert Path(opts["cookiefile"]).read_text() == cookies.read_text()
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


# ─── O arquivo mestre não pode ser destruído ──────────────────────────────────


def test_o_ytdlp_recebe_uma_copia_e_nao_o_original(monkeypatch, cookies):
    """O yt-dlp REESCREVE o arquivo de cookies quando a sessão é rejeitada.

    Aconteceu em produção: o arquivo caiu de 2954 para 1843 bytes numa única
    tentativa e perdeu SID, HSID, SSID, APISID, SAPISID, LOGIN_INFO e
    __Secure-1PSID. A partir dali toda chamada ia sem credencial, e o erro
    ("confirme que você não é um robô") apontava para o lugar errado.
    """
    monkeypatch.setattr(settings, "ytdlp_cookies_file", str(cookies))
    monkeypatch.setattr(settings, "ytdlp_proxy", "")

    entregue = ytdlp.base_opts()["cookiefile"]

    assert entregue != str(cookies), "entregou o mestre; o yt-dlp o destruiria"
    assert Path(entregue).read_text() == cookies.read_text()


def test_estragar_a_copia_nao_toca_no_mestre(monkeypatch, cookies):
    monkeypatch.setattr(settings, "ytdlp_cookies_file", str(cookies))
    monkeypatch.setattr(settings, "ytdlp_proxy", "")
    original = cookies.read_text()

    # É exatamente o que o yt-dlp faz: sobrescreve com um jar degradado.
    Path(ytdlp.base_opts()["cookiefile"]).write_text("# jar vazio\n")

    assert cookies.read_text() == original


def test_cada_chamada_recebe_a_sua_copia(monkeypatch, cookies):
    """Dois jobs simultâneos não podem escrever no mesmo arquivo."""
    monkeypatch.setattr(settings, "ytdlp_cookies_file", str(cookies))
    monkeypatch.setattr(settings, "ytdlp_proxy", "")

    a = ytdlp.base_opts()["cookiefile"]
    b = ytdlp.base_opts()["cookiefile"]

    assert a != b


def test_copia_impossivel_segue_sem_cookies(monkeypatch, cookies):
    """Entregar o mestre seria arriscar destruí-lo; falhar é recuperável."""
    monkeypatch.setattr(settings, "ytdlp_cookies_file", str(cookies))
    monkeypatch.setattr(settings, "ytdlp_proxy", "")

    def sem_espaco(*a, **k):
        raise OSError("No space left on device")

    monkeypatch.setattr(ytdlp.shutil, "copyfile", sem_espaco)

    assert "cookiefile" not in ytdlp.base_opts()
