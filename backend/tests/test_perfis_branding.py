"""
Marca por perfil — a dívida D42, resolvida.

O problema: os presets eram gravados só por NICHO, num diretório compartilhado.
Num produto multiusuário isso significava duas coisas ruins ao mesmo tempo — a
logo de um usuário apareceria no clipe do outro, e dois perfis da MESMA rubrica
("HZ Pod Clips" e "Cortes de Entrevistas", ambos podcast) não teriam como ter
marcas diferentes. O contorno da Fatia 6 foi fechar as rotas para não-donos, o
que deixava o usuário comum sem marca nenhuma.

Agora há duas escalas. A do PERFIL é sua; a do NICHO é da instalação e continua
restrita a quem administra, servindo de padrão para quem não subiu a própria.

O que estes testes guardam, além disso: que a LEITURA cai no nicho (para nada
existente quebrar) e que a ESCRITA nunca cai (senão salvar a marca de um perfil
sobrescreveria a de todo mundo).
"""

import asyncio
import io

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base, get_db
from app.main import register_routers
from app.models import User
from app.services.branding import (
    BANNER_COLORS_FILE,
    branding_dir,
    clipmint_defaults_dir,
    preset_path,
)


def _png(cor: str = "#ff0000") -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (64, 64), cor).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "public_build", True)
    monkeypatch.setattr(settings, "clipmint_password", "")
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path / "storage"))
    settings.ensure_dirs()

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'b.db'}")
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async def criar():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(criar())

    async def override_db():
        async with factory() as session:
            yield session

    app = FastAPI()
    register_routers(app)
    app.dependency_overrides[get_db] = override_db
    return app, factory


def _cliente(app, email="alice@x.com") -> TestClient:
    c = TestClient(app)
    assert c.post(
        "/api/auth/register",
        json={"email": email, "password": "uma-senha-bem-longa"},
    ).status_code == 201
    return c


def _perfil(cliente, nome="HZ Pod Clips", source="podcast") -> str:
    r = cliente.post("/api/profiles", json={"name": nome, "source_type": source})
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ─── A dívida resolvida ───────────────────────────────────────────────────────

def test_usuario_comum_configura_a_marca_do_proprio_perfil(ambiente):
    """
    Era exatamente isto que não dava para fazer.

    Antes, `/api/settings/*` era só para quem administra, então usuário comum
    ficava sem marca nos clipes — o item que eu tinha registrado como bloqueio
    de lançamento.
    """
    app, _ = ambiente
    alice = _cliente(app)
    pid = _perfil(alice)

    resp = alice.post(
        "/api/settings/watermark",
        params={"source": "podcast", "profile_id": pid},
        files={"file": ("logo.png", _png(), "image/png")},
    )
    assert resp.status_code == 201, resp.text
    assert alice.get(
        "/api/settings/watermark", params={"source": "podcast", "profile_id": pid}
    ).status_code == 200


def test_dois_perfis_da_mesma_rubrica_tem_marcas_diferentes(ambiente):
    """O caso que motivou a mudança: dois perfis de podcast, logos distintas."""
    app, _ = ambiente
    alice = _cliente(app)
    pod = _perfil(alice, "HZ Pod Clips", "podcast")
    entrevistas = _perfil(alice, "Cortes de Entrevistas", "podcast")

    alice.put(
        "/api/settings/banner-colors",
        params={"source": "podcast", "profile_id": pod},
        json={"bg_color": "#FF0000", "text_color": "#FFFFFF", "font": "condensed"},
    )
    alice.put(
        "/api/settings/banner-colors",
        params={"source": "podcast", "profile_id": entrevistas},
        json={"bg_color": "#0000FF", "text_color": "#FFFFFF", "font": "condensed"},
    )

    a = alice.get(
        "/api/settings/banner-colors", params={"source": "podcast", "profile_id": pod}
    ).json()
    b = alice.get(
        "/api/settings/banner-colors",
        params={"source": "podcast", "profile_id": entrevistas},
    ).json()
    assert a["bg_color"] == "#FF0000"
    assert b["bg_color"] == "#0000FF", "os dois perfis dividiram a mesma marca"


def test_marca_de_outro_usuario_e_inalcancavel(ambiente):
    app, _ = ambiente
    alice = _cliente(app, "alice@x.com")
    bruno = _cliente(app, "bruno@x.com")
    pid = _perfil(alice)

    resp = bruno.post(
        "/api/settings/watermark",
        params={"source": "podcast", "profile_id": pid},
        files={"file": ("logo.png", _png(), "image/png")},
    )
    assert resp.status_code == 404, "404, nunca 403 — um 403 confirmaria o id"


# ─── No público a queda é a marca do ClipMint; a escrita nunca cai ────────────

def test_perfil_sem_marca_propria_nao_herda_a_do_nicho(ambiente):
    """
    Perfil novo não pode nascer com a marca de quem administra a instalação.

    A pasta do nicho é compartilhada e guarda a marca do dono. Enquanto a queda
    era nela, o primeiro clipe de um usuário novo saía assinado por outra
    pessoa — logo, cores e @ inclusive. No build público a queda é a marca do
    próprio produto.
    """
    app, _ = ambiente
    alice = _cliente(app)
    pid = _perfil(alice)

    # Preset do nicho, gravado direto no disco (é o que já existia no projeto).
    do_nicho = branding_dir("podcast") / BANNER_COLORS_FILE
    do_nicho.write_text(
        '{"bg_color": "#123456", "text_color": "#FFFFFF", "font": "condensed"}',
        encoding="utf-8",
    )

    lido = preset_path("podcast", BANNER_COLORS_FILE, pid)
    assert lido != do_nicho, "o perfil herdou a marca do nicho"
    assert lido == clipmint_defaults_dir() / BANNER_COLORS_FILE


def test_salvar_no_perfil_nao_sobrescreve_o_do_nicho(ambiente):
    """
    A distinção entre onde LER e onde ESCREVER.

    Se a escrita usasse o mesmo caminho da leitura, salvar a marca de um perfil
    gravaria por cima do preset da instalação inteira — o bug que a separação
    entre `preset_path` e `_destino` existe para impedir.
    """
    app, _ = ambiente
    alice = _cliente(app)
    pid = _perfil(alice)

    do_nicho = branding_dir("podcast") / BANNER_COLORS_FILE
    do_nicho.write_text(
        '{"bg_color": "#111111", "text_color": "#FFFFFF", "font": "condensed"}',
        encoding="utf-8",
    )

    alice.put(
        "/api/settings/banner-colors",
        params={"source": "podcast", "profile_id": pid},
        json={"bg_color": "#999999", "text_color": "#FFFFFF", "font": "condensed"},
    )

    assert "#111111" in do_nicho.read_text(encoding="utf-8"), (
        "gravar a marca do perfil sobrescreveu a do nicho"
    )


def test_job_sem_perfil_tambem_nao_pega_a_marca_do_dono(ambiente):
    """No público, nem o job sem perfil cai na pasta compartilhada."""
    app, _ = ambiente
    _cliente(app)
    assert preset_path("podcast", BANNER_COLORS_FILE, None) == (
        clipmint_defaults_dir() / BANNER_COLORS_FILE
    )


def test_versao_pessoal_continua_lendo_do_nicho(ambiente, monkeypatch):
    """
    A queda no nicho continua valendo onde ela sempre fez sentido.

    Na instalação pessoal existe uma pessoa só: a marca do nicho é a dela, e os
    jobs anteriores aos perfis não podem mudar de aparência.
    """
    monkeypatch.setattr(settings, "public_build", False)
    assert preset_path("podcast", BANNER_COLORS_FILE, None) == (
        branding_dir("podcast") / BANNER_COLORS_FILE
    )


# ─── A escala do nicho continua restrita ──────────────────────────────────────

def test_nicho_continua_so_para_quem_administra(ambiente):
    """Ele é compartilhado; liberar geral traria o problema de volta."""
    app, _ = ambiente
    alice = _cliente(app)
    resp = alice.put(
        "/api/settings/banner-colors",
        params={"source": "podcast"},
        json={"bg_color": "#FF0000", "text_color": "#FFFFFF", "font": "condensed"},
    )
    assert resp.status_code == 403


def test_id_de_perfil_forjado_nao_escapa_do_diretorio(ambiente):
    """`../` num parâmetro de caminho é o clássico — e aqui ele vem do request."""
    app, _ = ambiente
    alice = _cliente(app)
    resp = alice.get(
        "/api/settings/banner-colors",
        params={"source": "podcast", "profile_id": "../../../etc"},
    )
    assert resp.status_code == 404


def test_excluir_perfil_leva_os_presets_dele(ambiente):
    """
    Sem isto, cada perfil excluído deixaria uma pasta de imagens órfã.

    Os clipes JÁ RENDERIZADOS não mudam: a marca foi queimada no vídeo na hora
    do render, não é lida de novo depois.
    """
    from app.services.branding import profile_dir

    app, _ = ambiente
    alice = _cliente(app)
    pid = _perfil(alice)

    alice.put(
        "/api/settings/banner-colors",
        params={"source": "podcast", "profile_id": pid},
        json={"bg_color": "#ABCDEF", "text_color": "#FFFFFF", "font": "condensed"},
    )
    pasta = profile_dir(pid)
    assert pasta is not None and pasta.exists()

    assert alice.delete(f"/api/profiles/{pid}").status_code == 204
    assert not pasta.exists(), "a pasta de presets do perfil ficou órfã"
