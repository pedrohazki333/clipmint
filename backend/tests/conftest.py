"""
Configuração comum dos testes.
"""

import pytest

from app.config import settings


@pytest.fixture(autouse=True)
def _no_remote_auth(monkeypatch):
    """
    Desliga a guarda de acesso remoto durante os testes.

    O middleware de app/main.py libera quem vem da própria máquina e exige o
    token de todo o resto. O TestClient não é nem uma coisa nem outra: ele se
    identifica como o host "testclient", que não é um IP e portanto não é
    loopback — então, com CLIPMINT_PASSWORD preenchida no .env da máquina, toda
    requisição de teste voltava 401 e o suíte inteiro dependia de o
    desenvolvedor não ter configurado senha.
    """
    monkeypatch.setattr(settings, "clipmint_password", "")


@pytest.fixture(autouse=True)
def _sem_consulta_ao_youtube(monkeypatch):
    """
    Nenhum teste fala com o YouTube.

    A criação de job passou a consultar os metadados do vídeo antes de aceitar
    (services/quota.py), e sem este atalho a suíte inteira sairia para a rede:
    ficou 24s mais lenta, os testes passaram a depender de conexão, e URLs de
    mentira como `watch?v=abc` viravam 422 por motivo que nada tem a ver com o
    que estava sendo testado.

    O padrão representa um vídeo NORMAL e curto: consulta bem-sucedida, 5
    minutos, não ao vivo. Devolver "consulta falhou" seria pior — com teto de
    duração configurado isso agora é recusa (e deve ser: ver docs/DECISOES.md,
    D45), e todo teste que só quer criar um job levaria 422 por um motivo que
    não tem nada a ver com o que ele testa.

    Quem testa os tetos sobrescreve com a duração que quiser.
    """
    from app.services import quota

    async def sem_rede(url: str) -> quota.Metadados:
        return quota.Metadados(duration=300.0, is_live=False, ok=True)

    monkeypatch.setattr(quota, "probe", sem_rede)


# ─── Postgres de verdade, para o que o SQLite não sabe fazer ──────────────────
#
# Row lock e chave estrangeira não existem no SQLite deste suíte (o projeto
# nunca liga `PRAGMA foreign_keys`). O que depende deles só é verificável no
# Postgres, e é melhor PULAR dizendo por quê do que "passar" por ausência.


def postgres_url() -> str:
    """O Postgres de desenvolvimento — o mesmo do `make serve-public`."""
    return (settings.public_database_url or "").strip()


def postgres_disponivel(url: str | None = None) -> bool:
    endereco = url if url is not None else postgres_url()
    if not endereco.startswith("postgresql"):
        return False
    try:
        import psycopg

        with psycopg.connect(
            endereco.replace("postgresql+psycopg://", "postgresql://"), connect_timeout=3
        ):
            return True
    except Exception:
        return False


SEM_POSTGRES = (
    "precisa de Postgres: defina PUBLIC_DATABASE_URL no .env da raiz "
    "(ver docs/POSTGRES.md)."
)
