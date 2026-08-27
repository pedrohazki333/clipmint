"""
Copia os dados do SQLite para o Postgres.

O Alembic cria o SCHEMA nos dois bancos; o que ele não faz é levar as linhas de
um para o outro. Este script faz isso, tabela por tabela, na ordem em que as
chaves estrangeiras exigem.

Uso:

    cd backend
    # confere o que seria copiado, sem escrever nada:
    .venv/bin/python -m app.scripts.migrate_to_postgres --dry-run \\
        --destino "postgresql+psycopg://clipmint:senha@localhost:5432/clipmint"

    # copia de verdade:
    .venv/bin/python -m app.scripts.migrate_to_postgres \\
        --destino "postgresql+psycopg://clipmint:senha@localhost:5432/clipmint"

Duas garantias deliberadas:

  - **A origem nunca é modificada.** É aberta somente para leitura; se algo der
    errado no meio, o SQLite continua sendo a cópia boa. Migrar não é mover.
  - **O destino precisa estar vazio** naquilo que vai receber. Copiar por cima
    de tabela com conteúdo duplicaria linha e violaria chave primária no meio do
    caminho, deixando o banco pela metade. Use --force se souber o que quer.

Tabelas que existem no banco mas não no código (a `model_video_jobs`, resquício
da geração pelo Veo) NÃO são copiadas: elas não têm modelo, e o destino nem tem
onde pôr. Elas continuam no arquivo SQLite, que fica intacto.
"""

import argparse
import asyncio
import logging
import sys

from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base
from app.models import Clip, Job, ReferenceExample, Transcript, User, VideoEnhanceJob

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("migrate")

#: Ordem importa: quem é apontado vem antes de quem aponta.
ORDEM = [User, Job, Transcript, Clip, ReferenceExample, VideoEnhanceJob]

#: Quantas linhas por INSERT. Suficiente para não fazer uma ida por linha, e
#: pequeno o bastante para não montar um comando gigante na memória.
LOTE = 500

#: (modelo, coluna que aponta, modelo apontado). O SQLite NÃO aplica chave
#: estrangeira (`PRAGMA foreign_keys = 0`), o Postgres aplica — então linha
#: órfã, que no arquivo de origem convive em paz, derruba a cópia no meio.
#:
#: Não é hipótese: o banco de desenvolvimento tem 9 transcrições apontando para
#: jobs que já não existem (auditoria de 25/08/2026), e a primeira tentativa de
#: cópia real morreu exatamente nelas com ForeignKeyViolation.
REFERENCIAS = [
    (Transcript, "job_id", Job),
    (Clip, "job_id", Job),
    (Job, "user_id", User),
]


async def _orfaos(session: AsyncSession, modelo, coluna, apontado) -> list[str]:
    """IDs de linhas de `modelo` cuja referência não existe."""
    col = getattr(modelo, coluna)
    alvo = select(apontado.id)
    consulta = select(modelo.id).where(col.is_not(None), col.not_in(alvo))
    return list((await session.execute(consulta)).scalars().all())


async def _contar(session: AsyncSession, modelo) -> int:
    return (await session.execute(select(func.count()).select_from(modelo))).scalar() or 0


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--origem",
        default=settings.db_url,
        help="URL do banco de origem (padrão: o DATABASE_URL atual)",
    )
    parser.add_argument("--destino", required=True, help="URL do Postgres de destino")
    parser.add_argument(
        "--dry-run", action="store_true", help="Só conta o que seria copiado"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Copia mesmo com o destino já tendo linhas (pode duplicar)",
    )
    parser.add_argument(
        "--pular-orfaos",
        action="store_true",
        help="Deixa para trás as linhas cuja referência não existe, em vez de parar",
    )
    args = parser.parse_args()

    if not args.destino.startswith("postgresql"):
        raise SystemExit("--destino precisa ser uma URL postgresql+psycopg://...")
    if args.origem == args.destino:
        raise SystemExit("origem e destino são o mesmo banco")

    origem = create_async_engine(args.origem)
    destino = create_async_engine(args.destino)
    SessaoOrigem = async_sessionmaker(bind=origem, class_=AsyncSession)
    SessaoDestino = async_sessionmaker(bind=destino, class_=AsyncSession)

    try:
        async with SessaoOrigem() as src, SessaoDestino() as dst:
            # 1. O destino tem o schema?
            async with destino.begin() as conn:
                from sqlalchemy import inspect

                tabelas = await conn.run_sync(
                    lambda c: set(inspect(c).get_table_names())
                )
            faltando = {m.__tablename__ for m in ORDEM} - tabelas
            if faltando:
                raise SystemExit(
                    f"O destino não tem as tabelas {sorted(faltando)}. Rode as "
                    f"migrações primeiro:\n"
                    f'  DATABASE_URL="{args.destino}" .venv/bin/alembic upgrade head'
                )

            # 2. O que existe de cada lado
            print()
            print(f"{'tabela':<22} {'origem':>8} {'destino':>8}")
            print("-" * 40)
            plano = []
            ocupado = []
            for modelo in ORDEM:
                n_origem = await _contar(src, modelo)
                n_destino = await _contar(dst, modelo)
                print(f"{modelo.__tablename__:<22} {n_origem:>8} {n_destino:>8}")
                if n_destino and n_origem:
                    ocupado.append(modelo.__tablename__)
                if n_origem:
                    plano.append(modelo)
            print()

            if ocupado and not args.force:
                raise SystemExit(
                    f"O destino já tem linhas em {ocupado}. Copiar por cima "
                    f"duplicaria dado e quebraria no meio. Esvazie o destino, "
                    f"ou use --force se souber o que está fazendo."
                )

            if not plano:
                print("Nada a copiar — a origem está vazia.")
                return

            # 3. Linhas órfãs: o SQLite tolera, o Postgres recusa.
            excluir: dict[str, set[str]] = {}
            achou_orfao = False
            for modelo, coluna, apontado in REFERENCIAS:
                ids = await _orfaos(src, modelo, coluna, apontado)
                if not ids:
                    continue
                achou_orfao = True
                excluir.setdefault(modelo.__tablename__, set()).update(ids)
                print(
                    f"  ATENÇÃO: {len(ids)} linha(s) de '{modelo.__tablename__}' "
                    f"apontam para {apontado.__tablename__} que não existe "
                    f"(ex.: {ids[0]})"
                )

            if achou_orfao:
                print()
                if not args.pular_orfaos:
                    raise SystemExit(
                        "O Postgres aplica chave estrangeira e recusaria essas "
                        "linhas no meio da cópia, deixando a migração pela "
                        "metade.\n"
                        "Escolha uma saída:\n"
                        "  --pular-orfaos   copia todo o resto e deixa essas para trás\n"
                        "  ou apague-as na origem antes de migrar."
                    )
                print("--pular-orfaos: essas linhas NÃO serão copiadas.\n")

            if args.dry_run:
                print("--dry-run: nada foi escrito.")
                return

            # 4. Cópia — tudo ou nada.
            # Um commit por tabela deixaria o destino pela metade se a terceira
            # falhasse, e um banco meio migrado é pior que nenhum: parece pronto.
            total_pulado = 0
            for modelo in plano:
                pular = excluir.get(modelo.__tablename__, set())
                linhas = (await src.execute(select(modelo))).scalars().all()
                dados = [
                    {c.name: getattr(obj, c.name) for c in modelo.__table__.columns}
                    for obj in linhas
                    if obj.id not in pular
                ]
                total_pulado += len(linhas) - len(dados)
                for i in range(0, len(dados), LOTE):
                    await dst.execute(insert(modelo.__table__), dados[i : i + LOTE])
                logger.info(
                    f"{modelo.__tablename__}: {len(dados)} linha(s)"
                    + (f" ({len(linhas) - len(dados)} órfã(s) pulada(s))" if pular else "")
                )
            await dst.commit()
            if total_pulado:
                logger.warning(
                    f"{total_pulado} linha(s) órfã(s) ficaram para trás — elas "
                    f"continuam na origem, que não foi alterada."
                )

            # 4. Conferência: contagem final tem que bater
            print()
            print("Conferindo...")
            problemas = []
            for modelo in ORDEM:
                n_origem = await _contar(src, modelo)
                n_destino = await _contar(dst, modelo)
                pulado = len(excluir.get(modelo.__tablename__, set()))
                esperado = n_origem - pulado
                estado = "ok" if n_destino >= esperado else "DIVERGIU"
                if estado != "ok":
                    problemas.append(modelo.__tablename__)
                nota = f"  ({pulado} órfã(s) pulada(s))" if pulado else ""
                print(
                    f"  {modelo.__tablename__:<22} {n_origem:>6} → {n_destino:>6}  "
                    f"{estado}{nota}"
                )

            if problemas:
                raise SystemExit(f"\nContagem não bateu em: {problemas}")
            print("\nCópia concluída. O SQLite de origem não foi alterado.")
    finally:
        await origem.dispose()
        await destino.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
