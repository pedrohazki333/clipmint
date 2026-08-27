"""
Faxina do storage: TTL dos clipes, vídeos de origem antigos e sobras órfãs.

O servidor roda isto sozinho de tempos em tempos (CLEANUP_INTERVAL_HOURS). Este
script é para rodar à mão — ou por cron, se você preferir tirar a faxina de
dentro do processo da API (aí é só pôr CLEANUP_INTERVAL_HOURS=0).

Uso:

    cd backend
    # mostra o que sairia, sem apagar nada:
    .venv/bin/python -m app.scripts.cleanup --dry-run

    # apaga:
    .venv/bin/python -m app.scripts.cleanup

Por cron, uma vez por dia às 4h:

    0 4 * * * cd /opt/clipmint/backend && .venv/bin/python -m app.scripts.cleanup
"""

import argparse
import asyncio
import logging
import sys

from app.config import settings
from app.database import AsyncSessionLocal
from app.services.retention import faxina

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("cleanup")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="Só mostra o que seria apagado"
    )
    args = parser.parse_args()

    print()
    print("Regras em vigor:")
    print(
        f"  arquivo do clipe apagado depois de : "
        f"{settings.clip_ttl_days or 'nunca'} dia(s)"
    )
    print(
        f"  vídeo de origem apagado depois de  : "
        f"{settings.download_ttl_days or 'nunca'} dia(s)"
    )
    print("  linhas do banco                    : nunca (alimentam o few-shot)")
    print()

    async with AsyncSessionLocal() as db:
        r = await faxina(db, dry_run=args.dry_run)

    print(f"{'SERIAM apagados' if args.dry_run else 'Apagados'}:")
    print(
        f"  clipes vencidos    : {r.clipes_expirados:>4}  "
        f"({r.bytes_de_clipes / 1e9:.2f} GB)"
    )
    print(
        f"  vídeos de origem   : {r.downloads_apagados:>4}  "
        f"({r.bytes_de_downloads / 1e9:.2f} GB)"
    )
    print(f"  transcrições órfãs : {r.transcricoes_orfas:>4}")
    print(
        f"  pastas órfãs       : {r.pastas_orfas:>4}  "
        f"({r.bytes_orfaos / 1e9:.2f} GB)"
    )
    print()
    print(f"  total: {r.bytes_totais / 1e9:.2f} GB")
    if args.dry_run:
        print("\n--dry-run: nada foi apagado.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
