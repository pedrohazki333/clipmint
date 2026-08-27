"""
O build público não pode expor as features pessoais.

Duas features seguem evoluindo na versão pessoal e não podem existir no produto
público: o nicho **Siege X** e a aba **Melhorar vídeo**. Esconder no frontend
não basta — quem souber o caminho chama a API direto, e do outro lado tem
download, transcrição paga e render.

Estes testes são a trava: exercitam a API com `PUBLIC_BUILD=true` e afirmam que
não há porta de entrada. E, na outra direção, afirmam que com a flag desligada
(o default, a versão pessoal) tudo continua funcionando — porque esconder do
público não pode custar a versão que é usada todo dia.
"""

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app import features
from app.config import settings
from app.database import Base, get_db
from app.models import User
from app.main import _require_password_on_public_build, register_routers
from app.services import branding


def _make_client(tmp_path, *, public: bool, monkeypatch) -> TestClient:
    """App montado do zero com a flag de build pedida."""
    monkeypatch.setattr(settings, "public_build", public)

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'public.db'}")
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async def create_schema():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(create_schema())

    async def override_db():
        async with factory() as session:
            yield session

    app = FastAPI()
    register_routers(app)
    app.dependency_overrides[get_db] = override_db
    app.state.factory = factory  # a fixture promover_a_dono precisa dela
    client = TestClient(app)

    if public:
        # No build público toda rota exige sessão. Criar a conta aqui é o que
        # faz os testes exercitarem a API como um cliente de verdade — sem isso
        # eles mediriam o 401, não a regra que querem provar.
        resp = client.post(
            "/api/auth/register",
            json={"email": "teste@exemplo.com", "password": "uma-senha-bem-longa"},
        )
        assert resp.status_code == 201, resp.text
    return client


@pytest.fixture
def public_client(tmp_path, monkeypatch):
    return _make_client(tmp_path, public=True, monkeypatch=monkeypatch)


@pytest.fixture
def personal_client(tmp_path, monkeypatch):
    return _make_client(tmp_path, public=False, monkeypatch=monkeypatch)


@pytest.fixture
def promover_a_dono(public_client):
    """Transforma o usuário do teste em administrador da instalação."""

    def promover() -> None:
        async def executar():
            async with public_client.app.state.factory() as db:
                await db.execute(User.__table__.update().values(is_owner=True))
                await db.commit()

        asyncio.run(executar())

    return promover


# ─── Melhorar vídeo ────────────────────────────────────────────────────────────

# Todo caminho do router de video-enhance, com o método que ele atende.
VIDEO_ENHANCE_ROUTES = [
    ("post", "/api/video-enhance"),
    ("get", "/api/video-enhance"),
    ("get", "/api/video-enhance/qualquer-id"),
    ("get", "/api/video-enhance/qualquer-id/video"),
    ("get", "/api/video-enhance/qualquer-id/download"),
    ("delete", "/api/video-enhance/qualquer-id"),
]


@pytest.mark.parametrize("method,path", VIDEO_ENHANCE_ROUTES)
def test_video_enhance_nao_existe_no_publico(public_client, method, path):
    """Sem rota registrada, a API responde 404 — não há como chegar ao worker."""
    resp = getattr(public_client, method)(path)
    assert resp.status_code == 404, f"{method.upper()} {path} respondeu {resp.status_code}"


@pytest.mark.parametrize("method,path", VIDEO_ENHANCE_ROUTES)
def test_video_enhance_continua_na_versao_pessoal(personal_client, method, path):
    """A mesma rota existe na versão pessoal.

    404 aqui significaria que a feature foi removida em vez de escondida. O que
    se espera é qualquer OUTRA coisa: 422 por falta de arquivo no upload, 404 do
    id inexistente vindo do handler... por isso a asserção é sobre a rota existir,
    e ela é feita no roteador, não no código de status.
    """
    rotas = {(m.lower(), r.path) for r in personal_client.app.routes
             for m in getattr(r, "methods", [])}
    assert (method, path.replace("qualquer-id", "{job_id}")) in rotas


# ─── Nicho Siege X ─────────────────────────────────────────────────────────────

def test_criar_job_de_siege_e_recusado_no_publico(public_client):
    resp = public_client.post(
        "/api/jobs",
        json={"youtube_url": "https://youtube.com/watch?v=abc", "source_type": "siege"},
    )
    assert resp.status_code == 422
    assert "siege" not in resp.text.lower() or "inválido" in resp.text.lower()


def test_criar_job_de_siege_funciona_na_versao_pessoal(personal_client):
    resp = personal_client.post(
        "/api/jobs",
        json={"youtube_url": "https://youtube.com/watch?v=abc", "source_type": "siege"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["source_type"] == "siege"


@pytest.mark.parametrize(
    "path,params",
    [
        ("/api/jobs", {"source": "siege"}),
    ],
)
def test_consultas_por_siege_sao_recusadas_no_publico(public_client, path, params):
    assert public_client.get(path, params=params).status_code == 422


@pytest.mark.parametrize(
    "path", ["/api/settings/banner-colors", "/api/settings/bar-style"]
)
def test_presets_de_siege_recusados_para_quem_administra(
    public_client, promover_a_dono, path
):
    """
    Aqui o 422 tem que vir da regra de NICHO, não da falta de permissão.

    Os presets são restritos a quem administra, e essa checagem roda antes da
    validação do parâmetro — testando com usuário comum viria 403 e o teste
    passaria sem provar nada sobre Siege X.
    """
    promover_a_dono()
    assert public_client.get(path, params={"source": "siege"}).status_code == 422


@pytest.mark.parametrize(
    "path,corpo",
    [
        (
            "/api/settings/banner-colors",
            {"bg_color": "#123456", "text_color": "#FFFFFF", "font": "condensed"},
        ),
        (
            "/api/settings/bar-style",
            {
                "bg_color": "#123456",
                "text_color": "#FFFFFF",
                "font": "condensed",
                "name": "@outro",
            },
        ),
    ],
)
def test_escrever_no_NICHO_e_fechado_para_usuario_comum(public_client, path, corpo):
    """
    A escala do nicho é compartilhada por toda a instalação.

    É a ESCRITA que precisa ser trancada: sem a trava, a marca de um usuário
    apareceria no clipe do outro. A saída para o usuário comum não é liberar
    isto — é a escala do PERFIL, que é dele (ver test_perfis_branding.py).
    """
    resp = public_client.put(path, params={"source": "podcast"}, json=corpo)
    assert resp.status_code == 403
    assert "perfil" in resp.text.lower()


@pytest.mark.parametrize(
    "path", ["/api/settings/banner-colors", "/api/settings/bar-style"]
)
def test_ler_o_compartilhado_e_liberado_e_nao_mostra_a_marca_de_ninguem(
    public_client, path
):
    """
    Ler tem que passar — e não vaza nada.

    A tela de CRIAR perfil ainda não tem id para pedir, e é dessa leitura que
    ela tira a lista de fontes do servidor; trancá-la deixava o seletor com só
    a fonte padrão. E não há o que proteger: no build público a leitura sem
    perfil cai na marca do PRODUTO, não na de quem administra (ver
    `preset_path`), então a resposta é o default do ClipMint.
    """
    resp = public_client.get(path, params={"source": "podcast"})
    assert resp.status_code == 200
    assert resp.json()["customized"] is False


@pytest.mark.parametrize(
    "path,params",
    [
        ("/api/jobs", {"source": "siege"}),
        ("/api/schedule/pick", {"axis": "hook", "source": "siege"}),
        ("/api/settings/banner-colors", {"source": "siege"}),
        ("/api/settings/bar-style", {"source": "siege"}),
    ],
)
def test_consultas_por_siege_funcionam_na_versao_pessoal(personal_client, path, params):
    assert personal_client.get(path, params=params).status_code == 200


@pytest.mark.parametrize(
    "path,params",
    [
        ("/api/schedule/slots", None),
        ("/api/schedule/pick", {"axis": "hook", "source": "podcast"}),
    ],
)
def test_fila_de_postagem_nao_existe_no_publico(public_client, path, params):
    """
    A grade é a do dono da instalação: horários fixos, contas dele.

    Num produto público ela seria uma tabela de horários que o usuário não
    escolheu, apontando para contas que não são dele. Uma fila por usuário é
    outro produto — precisaria de horários configuráveis e de saber onde
    publicar.
    """
    assert public_client.get(path, params=params).status_code == 404


def test_grade_completa_na_versao_pessoal(personal_client):
    slots = personal_client.get("/api/schedule/slots").json()
    assert len(slots) == 18
    assert {s["source_type"] for s in slots} == {"podcast", "gameplay", "siege"}


# ─── Efeitos fora da API ───────────────────────────────────────────────────────

def test_branding_de_siege_cai_no_default_no_publico(monkeypatch):
    """Nada de criar storage/branding/siege/ num servidor público."""
    monkeypatch.setattr(settings, "public_build", True)
    assert branding.normalize_source("siege") == "podcast"

    monkeypatch.setattr(settings, "public_build", False)
    assert branding.normalize_source("siege") == "siege"


def test_lista_de_nichos_por_build(monkeypatch):
    monkeypatch.setattr(settings, "public_build", True)
    assert features.allowed_source_types() == ("podcast", "gameplay")
    assert not features.video_enhance_enabled()

    monkeypatch.setattr(settings, "public_build", False)
    assert features.allowed_source_types() == ("podcast", "gameplay", "siege")
    assert features.video_enhance_enabled()


# ─── Falhar fechado sem senha ──────────────────────────────────────────────────

def test_build_publico_recusa_subir_sem_senha(monkeypatch):
    """
    Esquecer a senha não pode deixar a API aberta.

    A guarda de acesso do middleware só age quando há senha configurada — sem
    ela, nenhuma checagem acontece. O frontend já falhava fechado (503); o
    backend fazia o oposto, e quem apontasse direto para a API passava por cima
    da tela de login e disparava jobs que gastam crédito.
    """
    monkeypatch.setattr(settings, "public_build", True)
    monkeypatch.setattr(settings, "clipmint_password", "")

    with pytest.raises(RuntimeError, match="CLIPMINT_PASSWORD"):
        _require_password_on_public_build()


def test_build_publico_sobe_com_senha(monkeypatch):
    monkeypatch.setattr(settings, "public_build", True)
    monkeypatch.setattr(settings, "clipmint_password", "uma-senha")
    _require_password_on_public_build()  # não levanta


def test_versao_pessoal_continua_subindo_sem_senha(monkeypatch):
    """Uso local não pode passar a exigir senha — é a ferramenta do dia a dia."""
    monkeypatch.setattr(settings, "public_build", False)
    monkeypatch.setattr(settings, "clipmint_password", "")
    _require_password_on_public_build()  # não levanta


# ─── Aprendizado (referências, padrões, salvar exemplo) ────────────────────────

APRENDIZADO_ROTAS = [
    ("post", "/api/references"),
    ("post", "/api/references/standalone"),
    ("get", "/api/references"),
    ("get", "/api/references/qualquer-id"),
    ("patch", "/api/references/qualquer-id"),
    ("delete", "/api/references/qualquer-id"),
    ("post", "/api/references/qualquer-id/confirm"),
    ("get", "/api/patterns"),
    ("post", "/api/patterns/mine"),
    ("delete", "/api/patterns"),
]


@pytest.mark.parametrize("metodo,path", APRENDIZADO_ROTAS)
def test_aprendizado_nao_existe_no_publico(public_client, metodo, path):
    """
    Aprender com clipe viral e os padrões minerados: só na versão pessoal.

    Não é só "feature interna". Os exemplos validados vão todos para
    `prompt_engine/examples/validated/`, uma pasta ÚNICA que o PromptBuilder
    injeta na análise de TODO job — liberado no público, o aprendizado de um
    usuário mudaria o corte dos outros.
    """
    resp = getattr(public_client, metodo)(path)
    assert resp.status_code == 404, f"{metodo.upper()} {path} respondeu {resp.status_code}"


@pytest.mark.parametrize("metodo,path", APRENDIZADO_ROTAS)
def test_aprendizado_continua_na_versao_pessoal(personal_client, metodo, path):
    """404 aqui significaria remoção, não ocultação."""
    rotas = {
        (m.lower(), r.path)
        for r in personal_client.app.routes
        for m in getattr(r, "methods", [])
    }
    esperado = path.replace("qualquer-id", "{reference_id}")
    assert (metodo, esperado) in rotas


def test_salvar_exemplo_e_recusado_no_publico(public_client):
    """Mesma pasta global — o exemplo de um entraria no prompt dos outros."""
    resp = public_client.post(
        "/api/clips/qualquer/validate",
        json={"performance": "bom", "aprendizado": "x", "views": 1},
    )
    assert resp.status_code == 404


def test_salvar_exemplo_continua_na_versao_pessoal(personal_client):
    """Não pode ter sumido: é como o few-shot do dono da instalação cresce."""
    rotas = {r.path for r in personal_client.app.routes}
    assert "/api/clips/{clip_id}/validate" in rotas
