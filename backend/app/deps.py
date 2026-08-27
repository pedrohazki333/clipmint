"""
Quem é o usuário desta requisição.

O ponto delicado desta fatia: as duas versões autenticam de formas diferentes e
o resto do código não pode saber disso.

  - **Build público**: cookie de sessão → tabela `sessions` → usuário.
  - **Versão pessoal**: não há cadastro. Quem guarda a porta é a
    `CLIPMINT_PASSWORD` de sempre (middleware em main.py), e todo mundo que
    passou por ela é o usuário-dono.

Assim `current_user` devolve um `User` nas duas, e rota nenhuma precisa
perguntar em qual build está rodando.
"""

import logging

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.features import public_build
from app.models import User
from app.services.auth import SESSION_COOKIE, get_or_create_owner, user_for_token

logger = logging.getLogger(__name__)

NAO_AUTENTICADO = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Sessão inválida ou expirada. Entre de novo.",
)


async def current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    """O usuário da requisição. 401 se não houver."""
    if not public_build():
        # Versão pessoal: quem chegou aqui já passou pela senha única.
        return await get_or_create_owner(db)

    token = request.cookies.get(SESSION_COOKIE, "")
    user = await user_for_token(db, token)
    if not user:
        raise NAO_AUTENTICADO
    return user


async def current_user_optional(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """Como `current_user`, mas devolve None em vez de 401.

    Para rotas que respondem coisas diferentes com e sem login — hoje, só o
    `/api/auth/me`, que precisa poder dizer "ninguém" sem que isso seja erro.
    """
    if not public_build():
        return await get_or_create_owner(db)
    return await user_for_token(db, request.cookies.get(SESSION_COOKIE, ""))


def owned_by(user: User):
    """Condição SQL de "este job é desta pessoa".

    Nas duas versões o significado é o mesmo, mas o alcance difere:

      - **público**: só o que tem o id dela. Job sem dono (os que existiam antes
        de haver contas) não é de ninguém e não aparece para ninguém;
      - **pessoal**: o dela E o que não tem dono. Ali existe UM usuário, então
        job sem dono é dele — não há de quem mais pudesse ser. O startup adota
        os órfãos, mas depender só disso deixaria a pessoa sem enxergar os
        próprios jobs se a adoção não tivesse rodado ainda.
    """
    from sqlalchemy import or_

    from app.models import Job

    if public_build():
        return Job.user_id == user.id
    return or_(Job.user_id == user.id, Job.user_id.is_(None))


async def require_owner(user: User = Depends(current_user)) -> User:
    """
    Restringe a rota a quem administra a instalação.

    Usado nos presets de marca. Eles são gravados por NICHO, num diretório
    compartilhado — no build público, deixar qualquer usuário escrever ali faria
    a logo de um aparecer no clipe do outro. Enquanto o branding não for por
    usuário (ver docs/DECISOES.md, D42), a porta fica fechada para não-donos.

    Na versão pessoal todo mundo é o dono, então nada muda.
    """
    if not user.is_owner:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Os presets de marca são compartilhados nesta instalação e só "
                "quem administra pode alterá-los."
            ),
        )
    return user
