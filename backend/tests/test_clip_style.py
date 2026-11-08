"""
O estilo do clipe: um esquema só, e ninguém perde o que já tinha configurado.

O caso que guia a migração é real: o banner azul com letra amarela de uma página é a
identidade registrada dela. Medir contraste contra um preto fixo recusaria essa cor;
por isso se mede contra o fundo que o perfil usa de verdade.
"""

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.clip_style import (
    INK,
    PALETTE,
    CaptionStyle,
    ClipStyle,
    TitleStyle,
    contrast_ratio,
    legacy_style,
    parse_style,
    style_for_job,
    style_for_profile,
)
from app.config import settings
from app.database import Base, get_db
from app.main import register_routers
from app.models import Job
from app.prompts.viral_analysis import build_analysis_prompt
from app.services import branding
from app.services.hook_keyword import pick_keyword

AZUL, AMARELO = "#032DA5", "#FAC007"
PERFIL = "a" * 32


@pytest.fixture
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "public_build", False)
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path / "storage"))
    settings.ensure_dirs()
    return tmp_path


def _marca_antiga(banner=None, bar=None, perfil=PERFIL):
    pasta = branding.ensure_profile_dir(perfil)
    if banner is not None:
        (pasta / branding.BANNER_COLORS_FILE).write_text(json.dumps(banner), encoding="utf-8")
    if bar is not None:
        (pasta / branding.BAR_STYLE_FILE).write_text(json.dumps(bar), encoding="utf-8")


# ─── Padrões e validação ───────────────────────────────────────────────────────

def test_padroes_da_especificacao():
    style = ClipStyle()
    assert style.marca == "#FD375C"
    assert style.legenda.cor == "#FD375C"
    assert style.legenda.estilo == "caixa"
    assert style.legenda.tamanho == "M"
    assert style.titulo.ligado is True
    assert style.titulo.fundo == "#0B0B0C"
    assert style.arroba.ligado is True
    assert style.fonte == "archivo"


@pytest.mark.parametrize("cor", PALETTE.values())
def test_paleta_inteira_passa_no_contraste(cor):
    assert contrast_ratio(cor, INK) >= 4.5
    ClipStyle(marca=cor, legenda=CaptionStyle(cor=cor, estilo="caixa"))
    ClipStyle(marca=cor, legenda=CaptionStyle(cor=cor, estilo="cor"))


def test_contraste_bate_com_o_que_foi_medido():
    assert contrast_ratio("#FD375C", INK) == pytest.approx(5.51, abs=0.01)
    assert contrast_ratio("#FFFFFF", "#000000") == pytest.approx(21.0)


def test_cor_livre_que_fica_ilegivel_na_legenda_e_recusada():
    with pytest.raises(ValueError, match="ilegível na legenda"):
        CaptionStyle(cor="#1A1A2E")


def test_cor_livre_legivel_passa():
    assert CaptionStyle(cor="#ff8800").cor == "#FF8800"


@pytest.mark.parametrize("valor", ["rosa", "#FFF", "FD375C", "#GGGGGG", ""])
def test_cor_em_formato_errado_e_recusada(valor):
    with pytest.raises(ValueError, match="Cor inválida"):
        CaptionStyle(cor=valor)


def test_marca_ilegivel_sobre_o_fundo_e_recusada():
    with pytest.raises(ValueError, match="marca"):
        ClipStyle(marca=AZUL)


def test_identidade_azul_e_amarela_passa():
    """A marca registrada da página. Medido contra o preto, o azul seria recusado."""
    style = ClipStyle(marca=AMARELO, titulo=TitleStyle(fundo=AZUL, texto=AMARELO))
    assert style.titulo.fundo == AZUL


def test_texto_ilegivel_no_titulo_e_recusado():
    with pytest.raises(ValueError, match="ilegível sobre o fundo"):
        TitleStyle(fundo=AZUL, texto="#000000")


def test_fonte_desconhecida_e_recusada():
    with pytest.raises(ValueError, match="Fonte inválida"):
        ClipStyle(fonte="comic")


@pytest.mark.parametrize("fonte", ["archivo", "condensed", "montserrat_black"])
def test_fontes_que_ja_existiam_continuam(fonte):
    assert ClipStyle(fonte=fonte).fonte == fonte


def test_estilo_e_tamanho_fora_da_lista_sao_recusados():
    with pytest.raises(ValueError):
        CaptionStyle(estilo="neon")
    with pytest.raises(ValueError):
        CaptionStyle(tamanho="XG")


def test_arroba_e_limpo_e_tem_limite():
    assert ClipStyle.model_validate({"arroba": {"texto": "  @conta "}}).arroba.texto == "@conta"
    with pytest.raises(ValueError):
        ClipStyle.model_validate({"arroba": {"texto": "x" * 41}})


def test_estilo_gravado_invalido_nao_derruba_nada():
    assert parse_style("{quebrado") is None
    assert parse_style('{"marca": "#000000"}') is None
    assert parse_style(None) is None


def test_ida_e_volta_pelo_json():
    style = ClipStyle(marca="#FFD23F", legenda=CaptionStyle(estilo="cor", tamanho="G"))
    assert parse_style(style.model_dump_json()) == style


# ─── Migração: ninguém perde o que configurou ──────────────────────────────────

def test_hzpodclips_mantem_a_identidade(storage):
    """Os valores reais do perfil."""
    _marca_antiga(
        banner={"bg_color": AZUL, "text_color": AMARELO, "font": "condensed"},
        bar={"bg_color": AZUL, "text_color": AMARELO, "font": "condensed", "name": "@HZPODCLIPS"},
    )
    style = legacy_style("podcast", PERFIL)
    assert style.titulo.fundo == AZUL
    assert style.titulo.texto == AMARELO
    assert style.marca == AMARELO
    assert style.arroba.texto == "@HZPODCLIPS"
    assert style.fonte == "condensed"
    assert style.legenda.estilo == "cor"
    assert style.legenda.cor == AMARELO


def test_migrar_nao_altera_os_arquivos_antigos(storage):
    """Eles continuam sendo do streamer, e voltar de versão não encontra nada mudado."""
    _marca_antiga(banner={"bg_color": AZUL, "text_color": AMARELO})
    arquivo = branding.profile_dir(PERFIL) / branding.BANNER_COLORS_FILE
    antes = arquivo.read_text(encoding="utf-8")
    legacy_style("podcast", PERFIL)
    assert arquivo.read_text(encoding="utf-8") == antes


def test_quem_nao_configurou_nada_mantem_a_palavra_amarela(storage):
    style = legacy_style("podcast", PERFIL)
    assert style.legenda.estilo == "cor"
    assert style.legenda.cor == "#FFD23F"
    assert style.titulo.fundo == INK


def test_cores_antigas_fora_da_regra_nao_quebram(storage):
    """Foram escolhidas antes de a regra existir: viram padrão, sem recusar o perfil."""
    _marca_antiga(banner={"bg_color": "#111111", "text_color": "#222222"}, bar={"name": "@conta"})
    style = legacy_style("podcast", PERFIL)
    assert style.titulo.fundo == INK
    assert style.arroba.texto == "@conta"


def test_arquivo_antigo_corrompido_nao_quebra(storage):
    pasta = branding.ensure_profile_dir(PERFIL)
    (pasta / branding.BANNER_COLORS_FILE).write_text("{quebrado", encoding="utf-8")
    assert legacy_style("podcast", PERFIL).titulo.fundo == INK


def test_estilo_gravado_vence_o_derivado(storage):
    _marca_antiga(banner={"bg_color": AZUL, "text_color": AMARELO})
    perfil = SimpleNamespace(
        id=PERFIL, source_type="podcast", style_json=ClipStyle(marca="#3EC8FF").model_dump_json()
    )
    assert style_for_profile(perfil).marca == "#3EC8FF"


def test_job_usa_a_propria_copia_mesmo_com_perfil_mudado(storage):
    copia = ClipStyle(marca="#9DFF4F").model_dump_json()
    job = SimpleNamespace(style_json=copia, profile_id=PERFIL, source_type="podcast")
    perfil = SimpleNamespace(
        id=PERFIL, source_type="podcast", style_json=ClipStyle(marca="#3EC8FF").model_dump_json()
    )
    assert style_for_job(job, perfil).marca == "#9DFF4F"


def test_job_antigo_usa_o_perfil(storage):
    job = SimpleNamespace(style_json=None, profile_id=PERFIL, source_type="podcast")
    perfil = SimpleNamespace(
        id=PERFIL, source_type="podcast", style_json=ClipStyle(marca="#3EC8FF").model_dump_json()
    )
    assert style_for_job(job, perfil).marca == "#3EC8FF"


# ─── Pela API ──────────────────────────────────────────────────────────────────

@pytest.fixture
def api(storage, monkeypatch):
    monkeypatch.setattr(settings, "clipmint_password", "")
    engine = create_async_engine(f"sqlite+aiosqlite:///{storage / 's.db'}")
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
    cliente = TestClient(app)
    cliente.factory = factory
    return cliente


BASE = {"name": "P", "source_type": "podcast"}


def test_perfil_novo_nasce_com_o_padrao(api):
    style = api.post("/api/profiles", json=BASE).json()["style"]
    assert style["marca"] == "#FD375C"
    assert style["legenda"]["estilo"] == "caixa"


def test_perfil_novo_com_estilo_proprio(api):
    resp = api.post("/api/profiles", json={**BASE, "style": {"marca": "#FFD23F"}})
    assert resp.status_code == 201
    assert resp.json()["style"]["marca"] == "#FFD23F"


def test_api_recusa_cor_ilegivel_dizendo_o_motivo(api):
    resp = api.post(
        "/api/profiles", json={**BASE, "style": {"legenda": {"cor": "#101020"}}}
    )
    assert resp.status_code == 422
    assert "ilegível" in resp.text


def test_editar_sem_mandar_estilo_nao_perde_o_estilo(api):
    """A tela atual de perfil não conhece o campo, e salvar por ela não pode apagá-lo."""
    criado = api.post("/api/profiles", json={**BASE, "style": {"marca": "#3EC8FF"}}).json()
    editado = api.put(f"/api/profiles/{criado['id']}", json={**BASE, "name": "Novo"}).json()
    assert editado["name"] == "Novo"
    assert editado["style"]["marca"] == "#3EC8FF"


def test_editar_o_estilo(api):
    criado = api.post("/api/profiles", json=BASE).json()
    editado = api.put(
        f"/api/profiles/{criado['id']}", json={**BASE, "style": {"marca": "#9DFF4F"}}
    ).json()
    assert editado["style"]["marca"] == "#9DFF4F"


def test_listagem_traz_o_estilo(api):
    api.post("/api/profiles", json={**BASE, "style": {"marca": "#3EC8FF"}})
    assert api.get("/api/profiles").json()[0]["style"]["marca"] == "#3EC8FF"


def _estilo_do_job(api, job_id):
    async def ler():
        async with api.factory() as db:
            job = (await db.execute(select(Job).where(Job.id == job_id))).scalar_one()
            return job.style_json

    return asyncio.run(ler())


URL = "https://youtu.be/dQw4w9WgXcQ"


def test_job_guarda_a_copia_do_estilo_do_perfil(api):
    perfil = api.post("/api/profiles", json={**BASE, "style": {"marca": "#3EC8FF"}}).json()
    job = api.post("/api/jobs", json={"youtube_url": URL, "profile_id": perfil["id"]}).json()
    assert parse_style(_estilo_do_job(api, job["id"])).marca == "#3EC8FF"


def test_mudar_o_perfil_nao_muda_o_job_ja_criado(api):
    perfil = api.post("/api/profiles", json={**BASE, "style": {"marca": "#3EC8FF"}}).json()
    job = api.post("/api/jobs", json={"youtube_url": URL, "profile_id": perfil["id"]}).json()
    api.put(f"/api/profiles/{perfil['id']}", json={**BASE, "style": {"marca": "#9DFF4F"}})
    assert parse_style(_estilo_do_job(api, job["id"])).marca == "#3EC8FF"


def test_job_sem_perfil_nasce_com_o_padrao(api):
    job = api.post("/api/jobs", json={"youtube_url": URL, "source_type": "podcast"}).json()
    assert parse_style(_estilo_do_job(api, job["id"])).marca == "#FD375C"


# ─── A palavra-chave ───────────────────────────────────────────────────────────

def test_usa_a_palavra_que_a_analise_escolheu():
    assert pick_keyword("Perdi 200 mil seguidores numa noite", "seguidores") == "seguidores"


def test_devolve_como_esta_no_titulo():
    assert pick_keyword("PERDI TUDO", "tudo") == "TUDO"
    assert pick_keyword("Virou opinião", "OPINIAO") == "opinião"


def test_palavra_que_nao_esta_no_titulo_cai_na_heuristica():
    assert pick_keyword("Ninguém fala sobre isso", "segredo") == "Ninguém"


def test_mais_de_uma_palavra_cai_na_heuristica():
    assert pick_keyword("Perdi 200 mil seguidores", "200 mil") == "200"


def test_heuristica_prefere_numero():
    assert pick_keyword("Perdi 200 mil seguidores numa noite") == "200"


def test_heuristica_ignora_palavras_comuns():
    assert pick_keyword("Por que você faz isso") == "faz"


def test_titulo_vazio_nao_tem_palavra_chave():
    assert pick_keyword("") is None
    assert pick_keyword("   ") is None


def test_prompt_pede_a_palavra_chave():
    prompt = build_analysis_prompt(
        words=[{"text": "oi", "start": 0.0, "end": 0.5}],
        title="t",
        channel="c",
        duration_seconds=60,
        threshold=7,
        min_duration=15,
        max_duration=90,
        preferred_min=25,
        preferred_max=40,
    )
    assert "hook_keyword" in prompt


# ─── As fontes ─────────────────────────────────────────────────────────────────

def test_fontes_sao_instaladas_junto_das_do_branding(storage):
    branding.seed_clipmint_defaults()
    nomes = {p.name for p in branding.fonts_dir().iterdir()}
    assert {
        "ArchivoClipMintTitulo.ttf",
        "ArchivoClipMintLegenda.ttf",
        "ArchivoClipMintArroba.ttf",
        "OFL.txt",
    } <= nomes


def test_fonte_gerada_tem_o_nome_que_o_ass_vai_pedir(storage):
    from PIL import ImageFont

    branding.seed_clipmint_defaults()
    fonte = ImageFont.truetype(str(branding.fonts_dir() / "ArchivoClipMintTitulo.ttf"), 40)
    assert fonte.getname()[0] == "Archivo ClipMint Titulo"
    # Acentos do português precisam existir em caixa alta.
    assert fonte.getlength("OPINIÃO É AÇÃO") > 0


def test_instalar_de_novo_nao_sobrescreve(storage):
    branding.seed_clipmint_defaults()
    alvo = branding.fonts_dir() / "OFL.txt"
    alvo.write_text("alterado", encoding="utf-8")
    branding.seed_clipmint_defaults()
    assert alvo.read_text(encoding="utf-8") == "alterado"
