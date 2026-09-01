"""
Senhas, sessões e o usuário-dono.

Três coisas que o resto do código não deveria precisar saber:

  - como uma senha vira hash (e como se troca de algoritmo sem invalidar as
    senhas já gravadas);
  - como um cookie vira um usuário;
  - como a versão pessoal, que não tem cadastro, mesmo assim tem um dono.
"""

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import PasswordReset, Session, User

logger = logging.getLogger(__name__)

#: Argon2id com os parâmetros padrão da biblioteca, que seguem a recomendação
#: da OWASP. Medido nesta máquina: ~76 ms por hash — caro o bastante para
#: atrapalhar quem tenta adivinhar em massa, barato o bastante para um login.
_hasher = PasswordHasher()

#: Nome do cookie da sessão.
SESSION_COOKIE = "clipmint_session"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """A senha confere?

    Todas as formas de "não confere" viram False: senha errada, hash corrompido,
    ou o hash vazio de um usuário que nunca definiu senha (o dono da versão
    pessoal). Deixar qualquer uma delas subir como exceção transformaria uma
    tentativa de login inválida num erro 500.
    """
    if not password_hash:
        return False
    try:
        _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    return True


def needs_rehash(password_hash: str) -> bool:
    """O hash foi feito com parâmetros mais fracos que os de hoje?

    Existe para o dia em que os parâmetros do Argon2 subirem: no próximo login
    bem-sucedido a senha é regravada com os novos, sem pedir nada ao usuário e
    sem invalidar quem não entrou ainda.
    """
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def normalize_email(email: str) -> str:
    """Minúsculas e sem espaços — senão o mesmo endereço vira duas contas."""
    return email.strip().lower()


# ─── Sessões ───────────────────────────────────────────────────────────────────

def _hash_token(token: str) -> str:
    """SHA-256 do token da sessão.

    Hash rápido é o certo aqui, ao contrário das senhas: o token tem 256 bits
    vindos do `secrets`, então não há o que adivinhar por força bruta, e um hash
    lento só encareceria cada request. O que se ganha é que um dump da tabela
    não permite se passar por ninguém.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def create_session(
    db: AsyncSession, user: User, user_agent: str | None = None
) -> str:
    """Abre uma sessão e devolve o token que vai no cookie (só aqui ele existe)."""
    token = secrets.token_urlsafe(32)
    sessao = Session(
        token_hash=_hash_token(token),
        user_id=user.id,
        expires_at=datetime.now(timezone.utc)
        + timedelta(days=settings.session_days),
        user_agent=(user_agent or "")[:200] or None,
    )
    db.add(sessao)
    await db.commit()
    return token


async def user_for_token(db: AsyncSession, token: str) -> User | None:
    """O usuário dono desta sessão, ou None se ela não vale mais."""
    if not token:
        return None

    resultado = await db.execute(
        select(Session, User)
        .join(User, Session.user_id == User.id)
        .where(Session.token_hash == _hash_token(token))
    )
    linha = resultado.first()
    if not linha:
        return None

    sessao, user = linha
    expira = sessao.expires_at
    if expira.tzinfo is None:
        # O SQLite devolve datetime sem fuso; comparar com um aware estoura.
        expira = expira.replace(tzinfo=timezone.utc)
    if expira <= datetime.now(timezone.utc):
        return None
    if not user.is_active:
        # Conta desativada perde o acesso na hora, sem esperar a sessão expirar.
        return None
    return user


async def revoke_session(db: AsyncSession, token: str) -> None:
    await db.execute(delete(Session).where(Session.token_hash == _hash_token(token)))
    await db.commit()


async def revoke_all_sessions(db: AsyncSession, user_id: str) -> int:
    """Derruba todas as sessões de um usuário. Devolve quantas caíram."""
    resultado = await db.execute(delete(Session).where(Session.user_id == user_id))
    await db.commit()
    return resultado.rowcount or 0


async def purge_expired_sessions(db: AsyncSession) -> int:
    """Limpa sessões vencidas. Elas já não autenticam nada — é só faxina."""
    resultado = await db.execute(
        delete(Session).where(Session.expires_at <= datetime.now(timezone.utc))
    )
    await db.commit()
    return resultado.rowcount or 0


# ─── O dono da instalação ──────────────────────────────────────────────────────

# ─── Redefinição de senha ──────────────────────────────────────────────────────

async def create_password_reset(db: AsyncSession, user: User) -> str:
    """Abre um pedido de redefinição e devolve o token que vai no e-mail.

    O token só existe aqui e no e-mail — a tabela guarda o hash. Pedir de novo
    NÃO invalida o pedido anterior: quem clicou no primeiro e-mail que chegou
    ainda consegue entrar, que é o que não surpreende ninguém.
    """
    token = secrets.token_urlsafe(32)
    db.add(
        PasswordReset(
            token_hash=_hash_token(token),
            user_id=user.id,
            expires_at=datetime.now(timezone.utc)
            + timedelta(minutes=settings.password_reset_ttl_minutes),
        )
    )
    await db.commit()
    return token


async def consume_password_reset(db: AsyncSession, token: str) -> User | None:
    """Gasta o token e devolve o dono. `None` se inválido, vencido ou já usado.

    Marca `used_at` ANTES de o chamador trocar a senha: se a troca falhar, o
    usuário pede outro link — o que não pode acontecer é o token sobreviver a
    uma troca bem-sucedida.
    """
    pedido = await db.scalar(
        select(PasswordReset).where(PasswordReset.token_hash == _hash_token(token))
    )
    if pedido is None or pedido.used_at is not None:
        return None

    vence = pedido.expires_at
    if vence.tzinfo is None:  # SQLite devolve ingênuo; Postgres, ciente
        vence = vence.replace(tzinfo=timezone.utc)
    if vence <= datetime.now(timezone.utc):
        return None

    usuario = await db.scalar(select(User).where(User.id == pedido.user_id))
    if usuario is None or not usuario.is_active:
        return None

    pedido.used_at = datetime.now(timezone.utc)
    await db.commit()
    return usuario


async def purge_expired_password_resets(db: AsyncSession) -> int:
    """Faxina dos pedidos vencidos. Eles já não trocam senha nenhuma."""
    resultado = await db.execute(
        delete(PasswordReset).where(
            PasswordReset.expires_at <= datetime.now(timezone.utc)
        )
    )
    await db.commit()
    return resultado.rowcount or 0


async def get_or_create_owner(db: AsyncSession) -> User:
    """
    O usuário-dono da versão pessoal.

    A versão pessoal não tem cadastro — entra-se com a senha única de sempre — e
    passar a exigir e-mail e senha ali quebraria o uso diário sem ganho nenhum.
    Mas o resto do sistema (jobs, cota, TTL) fala em usuário. Este é o encaixe:
    existe UM usuário, todos os jobs são dele, e o pipeline não precisa saber em
    qual das duas versões está rodando.

    Idempotente: chamado a cada startup.
    """
    email = normalize_email(settings.owner_email)
    existente = (
        await db.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    if existente:
        return existente

    dono = User(
        email=email,
        # Sem senha própria: quem guarda a porta da versão pessoal é a
        # CLIPMINT_PASSWORD. Hash vazio nunca confere (ver verify_password),
        # então esta conta não tem como ser usada num login por senha.
        password_hash="",
        display_name="Dono",
        is_owner=True,
        is_active=True,
    )
    db.add(dono)
    await db.commit()
    await db.refresh(dono)
    logger.info(f"Usuário-dono criado: {email}")
    return dono


async def promote_owner(db: AsyncSession) -> User | None:
    """Dá a coroa de administrador à conta de `OWNER_EMAIL`, no build público.

    Lá o cadastro sempre grava `is_owner=False` — e tem que ser assim, senão
    qualquer um viraria administrador se cadastrando. Só que, sem este passo,
    NINGUÉM é dono num servidor novo: o painel financeiro ficaria inacessível
    inclusive para quem instalou, e a única saída seria um UPDATE à mão no
    Postgres às duas da manhã.

    A configuração já prometia isto (`OWNER_EMAIL`: "no público é quem
    administra"); faltava alguém cumprir a promessa.

    **Não cria conta**, diferente de `get_or_create_owner`: a conta do dono no
    público nasce pelo cadastro normal, com senha de verdade. Criar aqui faria
    um usuário sem senha com poder de administrador, que é o oposto do que se
    quer num servidor exposto. Enquanto o dono não se cadastrar, ninguém
    administra — e isso é seguro, não quebrado.

    Idempotente: roda a cada startup.
    """
    email = normalize_email(settings.owner_email)
    if not email:
        return None

    user = (
        await db.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    if user is None:
        logger.info(
            "Nenhuma conta com OWNER_EMAIL (%s) ainda — cadastre-se com esse "
            "e-mail e reinicie para administrar o painel.",
            email,
        )
        return None

    if not user.is_owner:
        user.is_owner = True
        await db.commit()
        logger.warning("Conta %s promovida a administradora da instalação", email)
    return user


async def adopt_orphan_jobs(db: AsyncSession, user: User) -> int:
    """
    Dá ao dono os jobs que existiam antes de haver usuários.

    Só na versão pessoal, e só faz sentido lá: naquela instalação todos os jobs
    SÃO do dono — não há de quem mais pudessem ser. No build público, job sem
    dono continua sem dono, porque atribuí-lo a alguém seria inventar.
    """
    from app.models import Job

    resultado = await db.execute(
        Job.__table__.update().where(Job.user_id.is_(None)).values(user_id=user.id)
    )
    await db.commit()
    adotados = resultado.rowcount or 0
    if adotados:
        logger.info(f"{adotados} job(s) sem dono atribuído(s) a {user.email}")
    return adotados
