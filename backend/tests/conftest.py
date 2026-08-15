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
