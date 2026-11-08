"""
Renderiza de novo os clipes de um job, sem chamar análise nenhuma.

    cd backend && .venv/bin/python -m app.scripts.rerender_job <job_id>
    ... rerender_job <job_id> --layout fullscreen
    ... rerender_job <job_id> --estilo-do-perfil
    ... rerender_job <job_id> --estilo-padrao

O `reanalyze_job` repensa os cortes e paga a análise. Este é o que serve quando o que
mudou foi só o visual: os cortes, a costura e os títulos são os mesmos, então a
comparação é direta e o custo de API é zero. Os arquivos antigos são apagados.

`--layout` troca o layout do job. `--estilo-do-perfil` recopia o estilo atual do perfil
para o job, e `--estilo-padrao` usa o padrão do produto, útil para conferir a
especificação em um perfil com identidade própria.
"""

import argparse
import asyncio
import logging
import shutil
import sys

from sqlalchemy import select, update

from app.clip_style import ClipStyle, style_for_profile
from app.config import settings
from app.database import AsyncSessionLocal
from app.layouts import layout_allowed
from app.models import Clip, Job, Profile
from app.workers import joblock
from app.workers.pipeline import run_pipeline


async def _preparar(args: argparse.Namespace) -> int:
    """Ajusta o job e devolve quantos clipes voltaram para a fila."""
    async with AsyncSessionLocal() as db:
        job = (await db.execute(select(Job).where(Job.id == args.job_id))).scalar_one_or_none()
        if job is None:
            print(f"Job {args.job_id} não existe.", file=sys.stderr)
            raise SystemExit(1)

        if args.layout:
            if not layout_allowed(args.layout, job.source_type):
                print(f"O layout {args.layout} não serve à rubrica {job.source_type}.", file=sys.stderr)
                raise SystemExit(1)
            job.layout_mode = args.layout

        if args.estilo_padrao:
            job.style_json = ClipStyle().model_dump_json()
        elif args.estilo_do_perfil:
            perfil = await db.get(Profile, job.profile_id) if job.profile_id else None
            job.style_json = (style_for_profile(perfil) if perfil else ClipStyle()).model_dump_json()

        result = await db.execute(
            update(Clip)
            .where(Clip.job_id == args.job_id)
            .values(status="error", file_path=None, file_size_bytes=None)
        )
        await db.commit()

    shutil.rmtree(settings.clips_dir / args.job_id, ignore_errors=True)
    return result.rowcount or 0


async def _run(args: argparse.Namespace) -> None:
    clipes = await _preparar(args)
    if not clipes:
        print("Este job não tem clipes: use o reanalyze_job.", file=sys.stderr)
        raise SystemExit(1)
    logging.info(f"[{args.job_id}] {clipes} clipe(s) de volta para a fila de render")
    await run_pipeline(args.job_id, resume=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job_id")
    parser.add_argument("--layout")
    estilo = parser.add_mutually_exclusive_group()
    estilo.add_argument("--estilo-do-perfil", action="store_true")
    estilo.add_argument("--estilo-padrao", action="store_true")
    args = parser.parse_args()

    # Mesma guarda dos outros scripts: dois processos no mesmo job corrompem os
    # arquivos um do outro.
    owner = joblock.owner_pid(args.job_id)
    if owner is not None:
        print(f"O job {args.job_id} já está sendo processado pelo PID {owner}.", file=sys.stderr)
        raise SystemExit(1)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
