import asyncio
import hmac
import ipaddress
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import AsyncSessionLocal, init_db
from app.features import (
    learning_enabled,
    public_build,
    schedule_enabled,
    video_enhance_enabled,
)
from app.routers import admin as admin_router
from app.routers import billing as billing_router
from app.routers import (
    auth,
    clips,
    jobs,
    profiles as profiles_router,
    references,
    schedule,
    settings as settings_router,
    video_enhance,
)
from app.services.auth import (
    adopt_orphan_jobs,
    get_or_create_owner,
    promote_owner,
    purge_expired_sessions,
)
from app.services import retention
from app.services.branding import migrate_legacy_branding, seed_clipmint_defaults
from app.services.profiles import (
    adopt_orphan_jobs as adopt_orphan_jobs_to_profiles,
    seed_profiles,
)
from app.workers.video_enhance_pipeline import reconcile_interrupted_enhancements
from app.workers.pipeline import reconcile_interrupted_jobs

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def _faxina_periodica() -> None:
    """Roda a retenção de tempos em tempos enquanto o servidor estiver de pé.

    Dentro do processo, e não num cron, porque um servidor que exige um passo
    manual de instalação para não encher o disco acaba enchendo o disco. Quem
    preferir cron põe CLEANUP_INTERVAL_HOURS=0 e chama
    `python -m app.scripts.cleanup` (ver docs/DEPLOY.md).

    Nunca deixa uma falha derrubar o laço: faxina que para de rodar em silêncio
    é pior que faxina que erra uma vez.
    """
    intervalo = settings.cleanup_interval_hours * 3600
    while True:
        # Espera ANTES da primeira passada: o startup já tem trabalho demais, e
        # varrer o storage inteiro junto com a subida atrasa o servidor a troco
        # de nada — o disco não enche em cinco minutos.
        await asyncio.sleep(intervalo)
        try:
            async with AsyncSessionLocal() as db:
                resultado = await retention.faxina(db)
            if resultado.bytes_totais or resultado.transcricoes_orfas:
                logger.info(f"Faxina do storage: {resultado.resumo()}")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - o laço não pode morrer
            logger.error(f"Faxina do storage falhou: {exc}", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inicializa banco de dados e diretórios de storage no startup."""
    logger.info(
        "Starting ClipMint (build %s)...",
        "PÚBLICO" if public_build() else "pessoal",
    )
    _require_password_on_public_build()
    _require_postgres_on_public_build()
    settings.ensure_dirs()
    await init_db()
    logger.info("Database initialized. Storage dirs ready.")

    # Marca global antiga → presets de cada nicho (idempotente).
    migrate_legacy_branding()

    # A marca do próprio produto, que é a queda de um perfil sem marca no
    # build público (ver preset_path).
    seed_clipmint_defaults()

    # A versão pessoal não tem cadastro, mas o resto do sistema fala em usuário:
    # existe UM dono, e todos os jobs são dele. Semear aqui é o que permite ao
    # pipeline, à cota e ao TTL tratarem as duas versões do mesmo jeito.
    if public_build():
        # No público a conta do dono nasce pelo cadastro normal, com senha de
        # verdade — aqui ela só ganha a coroa. Sem isto ninguém administra num
        # servidor novo, nem quem instalou.
        async with AsyncSessionLocal() as db:
            await promote_owner(db)
    else:
        async with AsyncSessionLocal() as db:
            dono = await get_or_create_owner(db)
            await adopt_orphan_jobs(db, dono)
            # As contas de sempre reaparecem como perfis, com os jobs antigos
            # dentro. Semeia só nicho que ele REALMENTE usou — quem nunca fez
            # gameplay não ganha um perfil de gameplay vazio.
            await seed_profiles(db, dono)
            await adopt_orphan_jobs_to_profiles(db, dono)

    # Sessão vencida não autentica nada; some daqui para a tabela não crescer
    # para sempre com lixo.
    async with AsyncSessionLocal() as db:
        vencidas = await purge_expired_sessions(db)
        if vencidas:
            logger.info(f"{vencidas} sessão(ões) vencida(s) removida(s).")

    # O pipeline roda dentro deste processo: jobs que ainda constam como "em
    # execução" são órfãos de um processo morto (reload, queda, Ctrl+C). Marca
    # como erro para o frontend parar de esperar — dá para retomar depois.
    interrupted = await reconcile_interrupted_jobs()
    if interrupted:
        logger.warning(
            f"{len(interrupted)} job(s) interrompido(s) marcado(s) como erro. "
            f"Retome com POST /api/jobs/<id>/retry."
        )

    # Mesma lógica para os tratamentos de vídeo da aba Melhorar vídeo — que no
    # build público não existe, então não há o que reconciliar.
    if video_enhance_enabled():
        interrupted_videos = await reconcile_interrupted_enhancements()
        if interrupted_videos:
            logger.warning(
                f"{len(interrupted_videos)} tratamento(s) de vídeo interrompido(s) marcado(s) como falha."
            )

    faxina_task = None
    if settings.cleanup_interval_hours > 0:
        faxina_task = asyncio.create_task(_faxina_periodica())
        logger.info(
            f"Faxina do storage a cada {settings.cleanup_interval_hours}h "
            f"(clipes: {settings.clip_ttl_days}d, "
            f"vídeos de origem: {settings.download_ttl_days}d)."
        )

    yield

    if faxina_task:
        faxina_task.cancel()
    logger.info("ClipMint shutting down.")


app = FastAPI(
    title="ClipMint API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _is_loopback(host: str | None) -> bool:
    """O cliente é a própria máquina?

    Não dá para comparar com uma lista de literais: o proxy do Next chega como
    IPv4 mapeado em IPv6 (`::ffff:127.0.0.1`), que o `is_loopback` do módulo
    ipaddress só reconhece depois de desmapeado.
    """
    if not host:
        return False
    if host == "localhost":
        return True
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return addr.is_loopback


def _require_postgres_on_public_build() -> None:
    """No build público, subir em SQLite é recusado.

    O SQLite é um arquivo com um escritor por vez. Serve muito bem à versão
    pessoal — uma pessoa, uma máquina — e é o que os testes usam. Num servidor
    com vários usuários e jobs concorrentes ele vira corrupção e "database is
    locked" no meio de um render.

    Mesma lógica da senha: falhar no startup, onde o problema é visível, em vez
    de descobrir na primeira escrita concorrente em produção.
    """
    if public_build() and not settings.is_postgres:
        # Qual das duas variáveis está mandando importa aqui: o nome antigo
        # (SQLITE_URL) VENCE o novo, de propósito (ver config.db_url). Quem
        # definiu DATABASE_URL e esqueceu o SQLITE_URL no .env leria uma
        # mensagem culpando a variável que ele acabou de configurar certo.
        variavel = "SQLITE_URL" if settings.sqlite_url else "DATABASE_URL"
        remedio = (
            " e APAGUE a linha SQLITE_URL, que tem precedência sobre ela."
            if settings.sqlite_url
            else "."
        )
        raise RuntimeError(
            f"O build PÚBLICO exige PostgreSQL, e {variavel} aponta para "
            f"{settings.db_url.split('://')[0]!r}. Um servidor multiusuário em "
            f"SQLite corrompe sob escrita concorrente. Defina DATABASE_URL="
            f"postgresql+psycopg://usuario:senha@host:5432/clipmint no .env"
            f"{remedio}"
        )


def _require_password_on_public_build() -> None:
    """No build público, subir sem senha é recusado.

    A guarda abaixo só age quando há senha configurada: sem ela, a API inteira
    fica aberta. Isso é aceitável na versão pessoal (é uma ferramenta local, e a
    porta só escuta em 127.0.0.1 no `make serve`), mas num servidor público
    significa que esquecer UMA variável de ambiente deixa qualquer um disparando
    jobs que gastam crédito de AssemblyAI e Anthropic.

    O middleware do frontend já falha fechado nesse caso — responde 503 e não
    deixa ninguém entrar. O backend fazia o oposto, e a assimetria era o furo:
    quem apontasse direto para a API passava por cima da tela de login.

    Falhar no startup, e não no primeiro request, é de propósito: um servidor
    que não sobe é um problema visível: um servidor aberto não é.
    """
    if public_build() and not settings.clipmint_password:
        raise RuntimeError(
            "CLIPMINT_PASSWORD está vazia e este é o build PÚBLICO. Sem ela a "
            "API fica aberta a qualquer um, e é ela que gasta crédito de "
            "transcrição e análise. Defina a variável no .env e suba de novo."
        )


#: Caminhos que precisam ficar abertos para a própria autenticação funcionar.
_ROTAS_ABERTAS = {
    "/health",
    "/api/auth/register",
    "/api/auth/login",
    "/api/auth/me",
    # O webhook do Mercado Pago vem da internet, sem sessão e sem o token da
    # instalação — não teria como passar pela cerca. Quem autentica ali é a
    # assinatura HMAC do próprio gateway (services/mercadopago.py), que é
    # obrigatória: sem segredo configurado o endpoint recusa tudo.
    "/api/billing/webhook",
}


@app.middleware("http")
async def require_local_or_token(request: Request, call_next):
    """Barra acesso direto à porta do backend vindo de fora da máquina.

    Esta é a guarda da VERSÃO PESSOAL: uma senha compartilhada, para o acesso
    remoto. Quem chega pelo frontend já passou pela tela de login do Next; ela
    cobre o caso de alguém apontar direto para a API — que, exposta na rede,
    dispararia jobs gastando crédito de AssemblyAI e Anthropic.

    No build público quem autentica é a SESSÃO de cada usuário (app/deps.py), e
    esta guarda continua valendo por cima como cerca do perímetro: o proxy do
    Next se identifica com o token, e a sessão diz quem é a pessoa. As rotas de
    login precisam passar, senão ninguém consegue nem tentar entrar.

    Senha vazia = sem checagem, e isso só é permitido na versão pessoal: o
    build público recusa subir sem senha (ver _require_password_on_public_build).
    """
    if settings.clipmint_password and request.url.path not in _ROTAS_ABERTAS:
        if not _is_loopback(request.client.host if request.client else None):
            token = request.headers.get("x-clipmint-token", "")
            if not hmac.compare_digest(token, settings.clipmint_password):
                return JSONResponse({"detail": "Não autorizado"}, status_code=401)

    return await call_next(request)


def register_routers(target: FastAPI) -> None:
    """Monta as rotas que ESTE build oferece.

    É uma função, e não um bloco solto, para o teste conseguir montar um app do
    zero com a flag de build trocada — sem isso a única forma de verificar o
    build público seria subir outro processo.
    """
    # Cadastro e login só existem no build público: a versão pessoal entra pela
    # senha única de sempre e não tem contas para criar. Não registrar é o que
    # torna as rotas inexistentes lá, em vez de existirem e recusarem.
    if public_build():
        target.include_router(auth.router, prefix="/api")
        # Cobrança só existe no público (ver features.billing_enabled).
        target.include_router(billing_router.router, prefix="/api")
        # Painel do dono. Registrado aqui e fechado por require_owner lá dentro:
        # a rota existir não é o mesmo que a rota estar aberta.
        target.include_router(admin_router.router, prefix="/api")

    target.include_router(profiles_router.router, prefix="/api")
    target.include_router(jobs.router, prefix="/api")
    target.include_router(clips.router, prefix="/api")
    # Aprender com clipe viral, padrões minerados e validação de exemplo — as
    # três só existem na versão pessoal. Sem o router, não há endpoint nenhum:
    # nem por URL adivinhada. O código segue inteiro em routers/references.py.
    if learning_enabled():
        target.include_router(references.router, prefix="/api")
    # A grade de postagem é a do dono da instalação — horários fixos, contas
    # dele. Não registrada no público, onde ela não descreveria o dia de
    # ninguém.
    if schedule_enabled():
        target.include_router(schedule.router, prefix="/api")
    target.include_router(settings_router.router, prefix="/api")

    # A aba Melhorar vídeo existe só na versão pessoal. Não registrar o router é
    # o que a torna inalcançável no público: sem rota não há como chegar ao
    # worker, nem por URL adivinhada. O código segue inteiro em
    # routers/video_enhance.py, e volta com PUBLIC_BUILD=false.
    if video_enhance_enabled():
        target.include_router(video_enhance.router, prefix="/api")


register_routers(app)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
