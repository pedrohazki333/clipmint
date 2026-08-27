"""
Cadastro, login e sessão.

Só existe no build público: a versão pessoal entra pela senha única de sempre e
não tem contas para criar. O router nem é registrado lá (ver app/main.py).
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.deps import current_user, current_user_optional
from app.models import User
from app.services import credits
from app.services.quota import usage as quota_usage
from app.services.auth import (
    SESSION_COOKIE,
    create_session,
    hash_password,
    needs_rehash,
    normalize_email,
    revoke_all_sessions,
    revoke_session,
    verify_password,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["auth"], prefix="/auth")


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)
    display_name: str | None = Field(default=None, max_length=80)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class UserResponse(BaseModel):
    id: str
    email: str
    display_name: str | None
    is_owner: bool

    model_config = {"from_attributes": True}


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,  # fora do alcance de JavaScript
        samesite="lax",  # não viaja em requisição de outro site
        path="/",
        max_age=settings.session_days * 24 * 60 * 60,
        # `secure` não é marcado: o acesso pode ser HTTP puro numa rede privada
        # (Tailscale), e ali o cookie nem seria gravado. Em produção com HTTPS,
        # quem termina o TLS é o proxy da frente — é lá que se marca.
    )


def _validar_senha(password: str) -> None:
    """Regra de senha: tamanho, e só.

    Sem exigência de composição ("uma maiúscula e um símbolo") de propósito: ela
    empurra as pessoas para senhas curtas e previsíveis do tipo `Senha@123`, que
    é pior que uma frase longa. A recomendação atual da OWASP é exatamente esta.
    """
    if len(password) < settings.min_password_length:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"A senha precisa ter pelo menos {settings.min_password_length} "
                f"caracteres. Uma frase que você lembre vale mais que símbolos."
            ),
        )


@router.post("/register", response_model=UserResponse, status_code=201)
async def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> User:
    """Cria a conta e já deixa a pessoa logada."""
    if not settings.registration_open:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="O cadastro está fechado no momento.",
        )

    _validar_senha(payload.password)
    email = normalize_email(payload.email)

    existente = (
        await db.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    if existente:
        # Dizer que o e-mail já existe é vazamento pequeno e inevitável (o
        # próprio fluxo de cadastro revelaria isso de qualquer jeito), e a
        # alternativa — fingir sucesso — deixaria a pessoa sem entender por que
        # não consegue entrar.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Já existe uma conta com este e-mail.",
        )

    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        display_name=(payload.display_name or "").strip() or None,
        is_active=True,
        is_owner=False,
    )
    db.add(user)
    # O bônus de boas-vindas entra na MESMA transação que cria a conta, e é daí
    # que vem a garantia de ser concedido uma única vez: se algo falhar, a conta
    # e o crédito voltam juntos. O flush antes é para a linha do usuário já
    # existir quando o lançamento referenciar a chave estrangeira dela.
    await db.flush()
    await credits.conceder_bonus_cadastro(db, user)
    await db.commit()
    await db.refresh(user)

    token = await create_session(db, user, request.headers.get("user-agent"))
    _set_session_cookie(response, token)
    logger.info(f"Conta criada: {email}")
    return user


@router.post("/login", response_model=UserResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> User:
    email = normalize_email(payload.email)
    user = (
        await db.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()

    # A MESMA resposta para "não existe", "senha errada" e "conta desativada".
    # Respostas diferentes deixariam descobrir quais e-mails têm conta aqui.
    if not user or not user.is_active or not verify_password(user.password_hash, payload.password):
        logger.warning(f"Login recusado para {email}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="E-mail ou senha incorretos.",
        )

    # Parâmetros do Argon2 podem ter subido desde o cadastro: aproveita que a
    # senha em claro está aqui, agora, e regrava o hash mais forte. Sem pedir
    # nada ao usuário e sem invalidar quem ainda não entrou.
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(payload.password)
        await db.commit()
        logger.info(f"Hash de senha atualizado para {email}")

    token = await create_session(db, user, request.headers.get("user-agent"))
    _set_session_cookie(response, token)
    return user


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> None:
    token = request.cookies.get(SESSION_COOKIE, "")
    if token:
        await revoke_session(db, token)
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.post("/logout-all", status_code=200)
async def logout_all(
    response: Response,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Derruba a sessão de todos os aparelhos.

    É o que a sessão em banco permite e o token assinado não permitiria: com
    JWT, só restaria esperar expirar.
    """
    quantas = await revoke_all_sessions(db, user.id)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"sessoes_encerradas": quantas}


@router.get("/me", response_model=UserResponse | None)
async def me(user: User | None = Depends(current_user_optional)) -> User | None:
    """Quem está logado, ou null. Não é erro não haver ninguém."""
    return user


class UsageResponse(BaseModel):
    """O consumo da janela de cota, para a tela de conta."""

    window_hours: int
    videos_used: int
    videos_max: int
    minutes_used: float
    minutes_max: int
    max_source_minutes: int


@router.get("/me/usage", response_model=UsageResponse)
async def me_usage(
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Quanto desta janela já foi usado. Exige sessão."""
    return await quota_usage(db, user)
