"""
As contas do painel: receita, custo, imposto e lucro de um mês.

## O fuso não é detalhe

As colunas de data são `timestamptz` em UTC. "Mês corrente" para quem toca o
negócio é o mês em **America/São_Paulo** — é o que bate com o extrato do
contador. Um mês calculado em UTC joga as três primeiras horas do dia 1 para o
mês anterior, e a virada do ano fica errada por três horas de faturamento.

Por isso a fronteira é sempre calculada no fuso local e CONVERTIDA para UTC
antes de ir ao banco: a comparação continua sendo entre instantes, que é o que
um índice sabe fazer rápido.

## Onde a soma acontece

Totais são `SUM` no banco — barato, indexado, não traz linha nenhuma para a
memória. Só a série diária traz linhas, e traz duas colunas apenas (instante e
valor), porque agrupar por dia LOCAL depende do fuso e fazer isso em SQL
amarraria a consulta ao dialeto.

Na escala deste produto isso é um mês de eventos — centenas de linhas. Se um dia
passar de dezenas de milhares, o caminho é uma agregação diária materializada,
não um `GROUP BY` mais esperto.

## Estimado é marcado como estimado

Duas coisas aqui não são medição:

  - a **taxa do gateway**, quando o pagamento ainda não liquidou: o Mercado Pago
    só informa a taxa depois, e até lá ela é calculada pelo percentual da
    configuração;
  - o **imposto**, que é um percentual sobre a receita bruta e um placeholder
    até o contador confirmar.

As duas voltam com a contagem do que foi estimado, para o painel poder dizer.
"""

import calendar
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Payment, Subscription, UsageEvent, User
from app.services import costs

logger = logging.getLogger(__name__)

#: O fuso do negócio. As fronteiras de mês são daqui, não de UTC.
FUSO = ZoneInfo("America/Sao_Paulo")

ZERO = Decimal("0")


def _brl(valor) -> Decimal:
    return Decimal(str(valor or 0)).quantize(Decimal("0.01"), ROUND_HALF_UP)


def _pct(parte: Decimal, total: Decimal) -> Decimal:
    if total == 0:
        return ZERO
    return (parte / total * 100).quantize(Decimal("0.01"), ROUND_HALF_UP)


@dataclass
class Periodo:
    """Um mês em America/São_Paulo, com as bordas já em UTC."""

    ano: int
    mes: int
    inicio: datetime  # UTC, inclusivo
    fim: datetime  # UTC, exclusivo

    @property
    def rotulo(self) -> str:
        return f"{self.ano:04d}-{self.mes:02d}"


def mes(ano: int, numero: int) -> Periodo:
    """As bordas do mês, calculadas no fuso local e convertidas para UTC."""
    primeiro = datetime.combine(date(ano, numero, 1), time.min, tzinfo=FUSO)
    if numero == 12:
        seguinte = datetime.combine(date(ano + 1, 1, 1), time.min, tzinfo=FUSO)
    else:
        seguinte = datetime.combine(date(ano, numero + 1, 1), time.min, tzinfo=FUSO)
    return Periodo(
        ano=ano,
        mes=numero,
        inicio=primeiro.astimezone(timezone.utc),
        fim=seguinte.astimezone(timezone.utc),
    )


def mes_corrente(agora: datetime | None = None) -> Periodo:
    local = (agora or datetime.now(timezone.utc)).astimezone(FUSO)
    return mes(local.year, local.month)


def mes_anterior(p: Periodo) -> Periodo:
    return mes(p.ano - 1, 12) if p.mes == 1 else mes(p.ano, p.mes - 1)


@dataclass
class VisaoGeral:
    """O resumo de um mês. Todos os valores em BRL, exceto os marcados."""

    periodo: str

    # Assinatura
    mrr_brl: Decimal = ZERO
    assinantes_ativos: int = 0
    novos_no_mes: int = 0
    cancelados_no_mes: int = 0
    churn_pct: Decimal = ZERO

    # Receita
    receita_bruta_brl: Decimal = ZERO
    taxas_gateway_brl: Decimal = ZERO
    receita_liquida_brl: Decimal = ZERO
    pagamentos: int = 0

    # Custo
    custo_variavel_brl: Decimal = ZERO
    custo_fixo_brl: Decimal = ZERO
    imposto_brl: Decimal = ZERO

    # Resultado
    lucro_liquido_brl: Decimal = ZERO
    margem_liquida_pct: Decimal = ZERO

    # O que o dono pediu para enxergar: gastamos e não recebemos.
    prejuizo_devolvido_brl: Decimal = ZERO
    videos_devolvidos: int = 0
    videos_processados: int = 0

    # Honestidade sobre o que é estimativa
    taxas_estimadas: int = 0
    imposto_pct: Decimal = ZERO
    avisos: list[str] = field(default_factory=list)


async def visao_geral(db: AsyncSession, periodo: Periodo) -> VisaoGeral:
    """Receita, custo, imposto e lucro do período."""
    config = await costs.get_config(db)
    v = VisaoGeral(periodo=periodo.rotulo)

    # ── Receita ───────────────────────────────────────────────────────────────
    # `paid_at`, e não `created_at`: uma cobrança criada em março e paga em
    # abril é receita de ABRIL. Contar pela criação antecipa receita que ainda
    # não entrou.
    linha = (
        await db.execute(
            select(
                func.count(Payment.id),
                func.coalesce(func.sum(Payment.amount_brl_gross), 0),
                func.coalesce(func.sum(Payment.gateway_fee_brl), 0),
                func.count(Payment.id).filter(Payment.gateway_fee_brl.is_(None)),
            ).where(
                Payment.status == "paid",
                Payment.paid_at >= periodo.inicio,
                Payment.paid_at < periodo.fim,
            )
        )
    ).one()
    v.pagamentos = int(linha[0] or 0)
    v.receita_bruta_brl = _brl(linha[1])
    taxa_informada = _brl(linha[2])
    v.taxas_estimadas = int(linha[3] or 0)

    if v.taxas_estimadas:
        # O gateway só informa a taxa depois de liquidar. Até lá, percentual da
        # configuração — melhor uma estimativa marcada que um zero silencioso.
        bruto_sem_taxa = (
            await db.scalar(
                select(func.coalesce(func.sum(Payment.amount_brl_gross), 0)).where(
                    Payment.status == "paid",
                    Payment.paid_at >= periodo.inicio,
                    Payment.paid_at < periodo.fim,
                    Payment.gateway_fee_brl.is_(None),
                )
            )
            or 0
        )
        estimada = _brl(
            Decimal(str(bruto_sem_taxa)) * Decimal(str(config.gateway_fee_pct)) / 100
        )
        v.taxas_gateway_brl = _brl(taxa_informada + estimada)
        v.avisos.append(
            f"{v.taxas_estimadas} pagamento(s) sem taxa informada pelo gateway — "
            f"taxa estimada em {config.gateway_fee_pct}%."
        )
    else:
        v.taxas_gateway_brl = taxa_informada

    v.receita_liquida_brl = _brl(v.receita_bruta_brl - v.taxas_gateway_brl)

    # ── Custo variável ────────────────────────────────────────────────────────
    uso = (
        await db.execute(
            select(
                func.count(UsageEvent.id),
                func.coalesce(func.sum(UsageEvent.total_cost_brl), 0),
            ).where(
                UsageEvent.created_at >= periodo.inicio,
                UsageEvent.created_at < periodo.fim,
            )
        )
    ).one()
    v.videos_processados = int(uso[0] or 0)
    v.custo_variavel_brl = _brl(uso[1])

    devolvidos = (
        await db.execute(
            select(
                func.count(UsageEvent.id),
                func.coalesce(func.sum(UsageEvent.total_cost_brl), 0),
            ).where(
                UsageEvent.created_at >= periodo.inicio,
                UsageEvent.created_at < periodo.fim,
                UsageEvent.credits_charged == 0,
                UsageEvent.total_cost_brl > 0,
            )
        )
    ).one()
    v.videos_devolvidos = int(devolvidos[0] or 0)
    v.prejuizo_devolvido_brl = _brl(devolvidos[1])

    # ── Custo fixo e imposto ──────────────────────────────────────────────────
    # O custo fixo entra INTEIRO, mesmo em mês corrente: o servidor já foi pago.
    # Comparar um mês em andamento com um fechado exige essa ressalva, e o
    # painel a recebe pronta em vez de inventar um rateio por dia.
    v.custo_fixo_brl = _brl(config.fixed_cost_brl_month)
    v.imposto_pct = Decimal(str(config.tax_pct_on_revenue))
    # Sobre a receita BRUTA — é a base usual no Brasil, e é placeholder até o
    # contador confirmar.
    v.imposto_brl = _brl(v.receita_bruta_brl * v.imposto_pct / 100)

    # ── Resultado ─────────────────────────────────────────────────────────────
    v.lucro_liquido_brl = _brl(
        v.receita_bruta_brl
        - v.custo_variavel_brl
        - v.custo_fixo_brl
        - v.imposto_brl
        - v.taxas_gateway_brl
    )
    v.margem_liquida_pct = _pct(v.lucro_liquido_brl, v.receita_bruta_brl)

    # ── Assinatura ────────────────────────────────────────────────────────────
    ativos = (
        await db.execute(
            select(
                func.count(Subscription.id),
                func.coalesce(func.sum(Subscription.valor_brl), 0),
            ).where(Subscription.status == "active")
        )
    ).one()
    v.assinantes_ativos = int(ativos[0] or 0)
    v.mrr_brl = _brl(ativos[1])

    v.novos_no_mes = int(
        await db.scalar(
            select(func.count(Subscription.id)).where(
                Subscription.started_at >= periodo.inicio,
                Subscription.started_at < periodo.fim,
            )
        )
        or 0
    )
    v.cancelados_no_mes = int(
        await db.scalar(
            select(func.count(Subscription.id)).where(
                Subscription.canceled_at >= periodo.inicio,
                Subscription.canceled_at < periodo.fim,
            )
        )
        or 0
    )

    # Churn clássico: cancelados sobre a base do INÍCIO do mês, reconstruída a
    # partir de onde estamos (ativos hoje − entradas + saídas). Sem histórico de
    # estado, é a única base fiel — e dividir pelos ativos de hoje subestimaria
    # o churn justamente nos meses ruins.
    base_inicial = v.assinantes_ativos - v.novos_no_mes + v.cancelados_no_mes
    v.churn_pct = _pct(Decimal(v.cancelados_no_mes), Decimal(max(base_inicial, 0)))

    if v.imposto_pct:
        v.avisos.append(
            f"Imposto estimado em {v.imposto_pct}% sobre a receita bruta — "
            f"placeholder até a confirmação do contador."
        )
    v.avisos.append(
        "Custos de uso são ESTIMADOS (uso x tarifa). Concilie 1x/mês contra as "
        "faturas da AssemblyAI, Anthropic e Hetzner e ajuste as tarifas."
    )
    return v


@dataclass
class DiaDaSerie:
    dia: str  # YYYY-MM-DD no fuso local
    receita_brl: Decimal
    custo_brl: Decimal
    lucro_brl: Decimal


async def serie_diaria(db: AsyncSession, periodo: Periodo) -> list[DiaDaSerie]:
    """Receita, custo e lucro por dia LOCAL do mês.

    O agrupamento é feito em Python porque o dia depende do fuso, e fazer isso
    em SQL amarraria a consulta ao dialeto (o `AT TIME ZONE` do Postgres não
    existe no SQLite dos testes). As consultas trazem duas colunas por linha —
    instante e valor —, não as linhas inteiras.

    O lucro diário aqui é receita − custo VARIÁVEL: custo fixo e imposto são
    mensais e ratear por dia daria uma curva que não existe.
    """
    dias = calendar.monthrange(periodo.ano, periodo.mes)[1]
    receitas: dict[str, Decimal] = {}
    gastos: dict[str, Decimal] = {}

    pagamentos = await db.execute(
        select(Payment.paid_at, Payment.amount_brl_gross).where(
            Payment.status == "paid",
            Payment.paid_at >= periodo.inicio,
            Payment.paid_at < periodo.fim,
        )
    )
    for quando, valor in pagamentos:
        chave = quando.astimezone(FUSO).date().isoformat()
        receitas[chave] = receitas.get(chave, ZERO) + Decimal(str(valor or 0))

    eventos = await db.execute(
        select(UsageEvent.created_at, UsageEvent.total_cost_brl).where(
            UsageEvent.created_at >= periodo.inicio,
            UsageEvent.created_at < periodo.fim,
        )
    )
    for quando, valor in eventos:
        chave = quando.astimezone(FUSO).date().isoformat()
        gastos[chave] = gastos.get(chave, ZERO) + Decimal(str(valor or 0))

    serie = []
    for numero in range(1, dias + 1):
        chave = date(periodo.ano, periodo.mes, numero).isoformat()
        receita = _brl(receitas.get(chave, ZERO))
        custo = _brl(gastos.get(chave, ZERO))
        serie.append(
            DiaDaSerie(
                dia=chave,
                receita_brl=receita,
                custo_brl=custo,
                lucro_brl=_brl(receita - custo),
            )
        )
    return serie


@dataclass
class LinhaDeUsuario:
    user_id: str
    email: str
    receita_brl: Decimal
    custo_brl: Decimal
    resultado_brl: Decimal
    videos: int
    #: Custa mais do que paga. É o que vai embasar a política de rate limit.
    deficitario: bool


async def por_usuario(db: AsyncSession, periodo: Periodo) -> list[LinhaDeUsuario]:
    """Receita paga contra custo de uso, por usuário, no período.

    Duas agregações separadas e o cruzamento em Python: um `FULL OUTER JOIN`
    entre elas resolveria em SQL, mas o SQLite dos testes não o tem, e o
    resultado seria uma consulta que só roda em produção — o pior lugar para
    descobrir que ela está errada.

    Ordenado do mais deficitário para o mais lucrativo: quem precisa de decisão
    aparece primeiro.
    """
    receitas: dict[str, Decimal] = {}
    for user_id, total in await db.execute(
        select(Payment.user_id, func.coalesce(func.sum(Payment.amount_brl_gross), 0))
        .where(
            Payment.status == "paid",
            Payment.paid_at >= periodo.inicio,
            Payment.paid_at < periodo.fim,
        )
        .group_by(Payment.user_id)
    ):
        receitas[user_id] = Decimal(str(total or 0))

    custos: dict[str, tuple[Decimal, int]] = {}
    for user_id, total, quantos in await db.execute(
        select(
            UsageEvent.user_id,
            func.coalesce(func.sum(UsageEvent.total_cost_brl), 0),
            func.count(UsageEvent.id),
        )
        .where(
            UsageEvent.created_at >= periodo.inicio,
            UsageEvent.created_at < periodo.fim,
            UsageEvent.user_id.is_not(None),
        )
        .group_by(UsageEvent.user_id)
    ):
        custos[user_id] = (Decimal(str(total or 0)), int(quantos or 0))

    ids = set(receitas) | set(custos)
    if not ids:
        return []

    emails = {
        uid: email
        for uid, email in await db.execute(
            select(User.id, User.email).where(User.id.in_(ids))
        )
    }

    linhas = []
    for uid in ids:
        receita = _brl(receitas.get(uid, ZERO))
        custo, videos = custos.get(uid, (ZERO, 0))
        custo = _brl(custo)
        linhas.append(
            LinhaDeUsuario(
                user_id=uid,
                email=emails.get(uid, "(conta removida)"),
                receita_brl=receita,
                custo_brl=custo,
                resultado_brl=_brl(receita - custo),
                videos=videos,
                deficitario=custo > receita,
            )
        )

    linhas.sort(key=lambda l: l.resultado_brl)
    return linhas
