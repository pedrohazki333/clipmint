"""
A configuração comercial: preços, pacotes, planos e o trial.

Mora numa tabela (`billing_config`, linha única) e não em variável de ambiente
porque preço muda com o negócio, não com o deploy — o dono precisa poder ajustar
o preço do crédito ou criar um pacote com desconto sem reiniciar o servidor.

Regra que não se negocia: **preço nunca vem do cliente**. O servidor resolve o
valor aqui, no momento do checkout, e congela o resultado na linha de
`payments`. Editar um preço amanhã não pode reescrever o que já foi vendido.
"""

import logging
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BillingConfig

logger = logging.getLogger(__name__)

#: A configuração é uma linha só, e o id dela é este. O `CHECK (id = 1)` da
#: migração é o que impede uma segunda aparecer por acidente.
CONFIG_ID = 1

#: Os valores com que a configuração nasce.
#:
#: A migração 0006 semeia ESTES MESMOS valores, escritos lá literalmente — uma
#: migração não importa código da aplicação, senão editar um padrão hoje
#: reescreveria o que uma migração fez meses atrás. A duplicação é deliberada, e
#: `test_credits.py` compara as duas cópias para que não divirjam em silêncio.
#:
#: Os planos são PLACEHOLDER: valores para o dono ajustar pela configuração.
CONFIG_PADRAO: dict = {
    "credito_avulso_brl": Decimal("0.12"),
    "pacotes": [
        {"creditos": 300, "preco_brl": None},
        {"creditos": 600, "preco_brl": None},
        {"creditos": 1500, "preco_brl": None},
    ],
    "planos": [
        {"code": "essencial", "nome": "Essencial", "valor_brl": "49.90", "creditos_mes": 500},
        {"code": "pro", "nome": "Pro", "valor_brl": "99.90", "creditos_mes": 1200},
    ],
    # 120 = um vídeo médio (~2h) inteiro. O trial existe para a pessoa ver o
    # produto funcionar UMA vez; com 30 ela não chegava lá, e ainda entrava
    # vendo o aviso de saldo baixo. Ver a migração 0009.
    "creditos_gratis_cadastro": 120,
    # Um vídeo médio deste produto tem ~2h: "saldo baixo" é não ter para mais um.
    "saldo_baixo_threshold": 120,
}


async def get_config(db: AsyncSession) -> BillingConfig:
    """A configuração vigente, criando-a com os padrões se ainda não existir.

    Em produção a linha já nasce com a migração 0006 — este caminho de criação
    existe para o banco montado direto pelo metadata (os testes) e para um banco
    novo que ainda não migrou. É idempotente: `CHECK (id = 1)` mais a chave
    primária garantem que só exista uma.

    Não commita: quem chamou fecha a transação.
    """
    config = await db.scalar(
        select(BillingConfig).where(BillingConfig.id == CONFIG_ID)
    )
    if config is None:
        logger.info("billing_config ausente; criando a linha 1 com os padrões")
        config = BillingConfig(id=CONFIG_ID, **CONFIG_PADRAO)
        db.add(config)
        await db.flush()
    return config


async def update_config(
    db: AsyncSession, *, updated_by_user_id: str | None = None, **campos
) -> BillingConfig:
    """Altera a configuração. Só os campos passados são tocados.

    Não commita: quem chamou fecha a transação.
    """
    config = await get_config(db)

    permitidos = {
        "credito_avulso_brl",
        "pacotes",
        "planos",
        "creditos_gratis_cadastro",
        "saldo_baixo_threshold",
    }
    desconhecidos = set(campos) - permitidos
    if desconhecidos:
        raise ValueError(f"campos de configuração desconhecidos: {sorted(desconhecidos)}")

    for chave, valor in campos.items():
        setattr(config, chave, valor)
    config.updated_by_user_id = updated_by_user_id

    await db.flush()
    logger.info("billing_config alterada: %s", sorted(campos))
    return config


def preco_do_pacote(config: BillingConfig, creditos: int) -> Decimal:
    """Quanto custa um pacote de `creditos` créditos, em reais.

    Se o pacote estiver na configuração com `preco_brl` preenchido, é esse — é
    assim que um pacote grande ganha desconto. Caso contrário o preço deriva de
    `credito_avulso_brl`, que é o comportamento padrão.

    Arredonda para centavo com ROUND_HALF_UP (o arredondamento comercial); o
    padrão do Python é banqueiro e faria 0,125 virar 0,12.
    """
    if creditos <= 0:
        raise ValueError("pacote precisa ter pelo menos 1 crédito")

    for pacote in config.pacotes or []:
        if int(pacote.get("creditos", 0)) == creditos:
            preco = pacote.get("preco_brl")
            if preco is not None:
                return Decimal(str(preco)).quantize(Decimal("0.01"), ROUND_HALF_UP)
            break

    unitario = Decimal(str(config.credito_avulso_brl))
    return (unitario * creditos).quantize(Decimal("0.01"), ROUND_HALF_UP)
