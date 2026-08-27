"""
Qual layout serve a qual rubrica.

Dois dos quatro modos presumem coisas sobre o conteúdo: a **capa** é escolhida
pelo quadro mais expressivo de um ROSTO falando (num gameplay ela pega uma tela
de jogo, que não diz nada), e a **facecam empilhada** precisa de uma câmera
separada do gameplay (num podcast o vídeo inteiro já é a câmera). Os outros dois
— recortar no centro e não recortar — não presumem nada e servem a qualquer um.

A regra vive em `app/layouts.py` e é espelhada em `frontend/src/lib/layouts.ts`.
Como no regex de URL (D16), a cópia é o preço de decidir nos dois lados; o que
dá para eliminar é a chance de divergirem, e é o que o último teste faz.
"""

import json
import re
from pathlib import Path

import pytest

from app.layouts import (
    ALL_LAYOUTS,
    LAYOUT_LABELS,
    layout_allowed,
    layouts_for,
)

_TS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "layouts.ts"
_PESSOAL_TS = (
    Path(__file__).resolve().parents[2] / "frontend" / "src" / "personal" / "data.ts"
)


# ─── A regra ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "nicho,esperado",
    [
        ("podcast", ("cover", "crop", "original")),
        ("gameplay", ("streamer", "crop", "original")),
        ("siege", ("streamer", "crop", "original")),
    ],
)
def test_layouts_por_rubrica(nicho, esperado):
    assert layouts_for(nicho) == esperado


def test_capa_e_so_de_podcast():
    """A capa é o quadro mais expressivo de um rosto — gameplay não tem isso."""
    assert layout_allowed("cover", "podcast")
    assert not layout_allowed("cover", "gameplay")
    assert not layout_allowed("cover", "siege")


def test_facecam_empilhada_nao_e_de_podcast():
    """Num podcast não há câmera separada para empilhar sobre nada."""
    assert layout_allowed("streamer", "gameplay")
    assert layout_allowed("streamer", "siege")
    assert not layout_allowed("streamer", "podcast")


@pytest.mark.parametrize("nicho", ["podcast", "gameplay", "siege"])
def test_crop_e_original_servem_a_todos(nicho):
    """Eles não presumem nada sobre o conteúdo — por isso valem para tudo."""
    assert layout_allowed("crop", nicho)
    assert layout_allowed("original", nicho)


def test_rubrica_desconhecida_so_recebe_os_universais():
    assert layouts_for("inventada") == ("crop", "original")


def test_layout_inventado_e_recusado():
    assert not layout_allowed("holograma", "podcast")
    assert not layout_allowed(None, "podcast")


def test_todo_layout_tem_rotulo():
    """Sem rótulo, a mensagem de erro citaria uma chave interna."""
    assert set(LAYOUT_LABELS) == set(ALL_LAYOUTS)
    for nome, descricao in LAYOUT_LABELS.values():
        assert nome and descricao


# ─── Paridade com o frontend ──────────────────────────────────────────────────

def _tabela_ts(arquivo: Path, nome: str) -> dict[str, list[str]]:
    """Extrai uma tabela `layout → rubricas` de um arquivo TypeScript."""
    fonte = arquivo.read_text(encoding="utf-8")
    achado = re.search(
        rf"export const {nome}[^=]*=\s*(\{{.*?\}})\s*(?:as const)?;", fonte, re.S
    )
    assert achado, f"não encontrei {nome} em {arquivo}"
    bruto = achado.group(1)
    # TS aceita chave sem aspas e vírgula sobrando; JSON não.
    bruto = re.sub(r"//.*", "", bruto)
    bruto = re.sub(r"(\w+):", r'"\1":', bruto)
    bruto = re.sub(r",(\s*[\]}])", r"\1", bruto)
    return json.loads(bruto)


def _regra_do_frontend() -> dict[str, list[str]]:
    """
    A tabela como o build PESSOAL a monta: a base mais o que `@/personal`
    acrescenta.

    As duas metades vivem separadas porque `layouts.ts` entra no bundle público
    e a rubrica pessoal não pode aparecer nele nem como texto. Aqui elas voltam
    a ser uma só, que é o que o backend enxerga.
    """
    base = _tabela_ts(_TS, "BASE_LAYOUT_RUBRICS")
    pessoal = _tabela_ts(_PESSOAL_TS, "PERSONAL_LAYOUT_RUBRICS")
    return {
        layout: (rubricas + pessoal.get(layout, []) if rubricas else [])
        for layout, rubricas in base.items()
    }


def test_frontend_e_backend_concordam():
    """
    A guarda que dispensa boa vontade.

    Um layout liberado só no frontend viraria um botão que o servidor recusa; só
    no backend, uma opção que ninguém vê.
    """
    do_front = _regra_do_frontend()
    do_back = {
        layout: list(
            n for n in ("podcast", "gameplay", "siege") if layout_allowed(layout, n)
        )
        for layout in ALL_LAYOUTS
    }
    front_normalizado = {
        layout: list(
            n for n in ("podcast", "gameplay", "siege")
            if not do_front[layout] or n in do_front[layout]
        )
        for layout in do_front
    }
    assert front_normalizado == do_back


# ─── A regra pela API ─────────────────────────────────────────────────────────

import asyncio  # noqa: E402

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings  # noqa: E402
from app.database import Base, get_db  # noqa: E402
from app.main import register_routers  # noqa: E402


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "public_build", False)
    monkeypatch.setattr(settings, "clipmint_password", "")
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path / "storage"))
    settings.ensure_dirs()

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'l.db'}")
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
    return TestClient(app)


URL = "https://youtu.be/dQw4w9WgXcQ"


@pytest.mark.parametrize(
    "nicho,layout,esperado",
    [
        ("podcast", "cover", 201),
        ("podcast", "crop", 201),
        ("podcast", "original", 201),
        ("podcast", "streamer", 422),   # não há câmera separada para empilhar
        ("gameplay", "streamer", 201),
        ("gameplay", "crop", 201),
        ("gameplay", "original", 201),
        ("gameplay", "cover", 422),     # a capa procura um rosto falando
    ],
)
def test_combinacoes_pela_api(cliente, nicho, layout, esperado):
    resp = cliente.post(
        "/api/jobs",
        json={"youtube_url": URL, "source_type": nicho, "layout_mode": layout},
    )
    assert resp.status_code == esperado, resp.text
    if esperado == 422:
        assert "não serve à rubrica" in resp.text


def test_a_recusa_diz_o_que_serve(cliente):
    """Erro que só nega deixa a pessoa adivinhando."""
    resp = cliente.post(
        "/api/jobs",
        json={"youtube_url": URL, "source_type": "gameplay", "layout_mode": "cover"},
    )
    assert "Facecam + gameplay" in resp.text
    assert "Crop vertical" in resp.text


@pytest.mark.parametrize(
    "nicho,esperado", [("podcast", "cover"), ("gameplay", "streamer")]
)
def test_layout_omitido_cai_no_primeiro_da_rubrica(cliente, nicho, esperado):
    """
    Sem layout, o antigo default fixo era "cover" — que recusava todo pedido de
    gameplay que não o informasse.
    """
    resp = cliente.post("/api/jobs", json={"youtube_url": URL, "source_type": nicho})
    assert resp.status_code == 201, resp.text
    assert resp.json()["layout_mode"] == esperado


def test_layout_omitido_usa_o_padrao_do_perfil(cliente):
    perfil = cliente.post(
        "/api/profiles",
        json={"name": "P", "source_type": "podcast", "default_layout_mode": "crop"},
    ).json()
    resp = cliente.post(
        "/api/jobs", json={"youtube_url": URL, "profile_id": perfil["id"]}
    )
    assert resp.json()["layout_mode"] == "crop"


def test_perfil_nao_aceita_layout_de_outra_rubrica(cliente):
    resp = cliente.post(
        "/api/profiles",
        json={"name": "P", "source_type": "gameplay", "default_layout_mode": "cover"},
    )
    assert resp.status_code == 422
    assert "não serve à rubrica" in resp.text


def test_perfil_sem_layout_ganha_o_da_rubrica(cliente):
    p = cliente.post(
        "/api/profiles", json={"name": "G", "source_type": "gameplay"}
    ).json()
    assert p["default_layout_mode"] == "streamer"
