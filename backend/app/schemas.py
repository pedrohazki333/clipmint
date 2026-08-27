import json
import re
from datetime import datetime
from decimal import Decimal
from typing import Optional, List, Literal
from pydantic import BaseModel, Field, field_validator, model_validator

from app.features import SourceTypeField
from app.layouts import LayoutField
from app.utils.timecodes import TimecodeError, parse_ranges

# Exige o identificador do vídeo, não só o formato do endereço. Sem isso,
# `https://youtu.be/` passava na validação E no extract_info do yt-dlp — que o
# resolve para uma URL sem id nenhum — e virava um job que baixava nada e
# falhava com uma mensagem que não explicava coisa alguma. Verificado em
# 25/08/2026 contra o yt-dlp de verdade.
#
# O tamanho do id NÃO é validado de propósito: hoje são 11 caracteres, mas quem
# tem autoridade para dizer se um id existe é o YouTube, não um regex nosso. O
# que se recusa aqui é o endereço vazio, que nunca vai a lugar nenhum.
#
# ESPELHO de frontend/src/lib/youtube.ts — ver tests/test_youtube_url.py, que
# compara os dois caractere a caractere.
_YOUTUBE_URL_RE = re.compile(
    r"^https?://(www\.|m\.)?(youtube\.com/(watch\?(\S*&)?v=[\w-]+|shorts/[\w-]+|live/[\w-]+)|youtu\.be/[\w-]+)"
)


# ─── Job ───────────────────────────────────────────────────────────────────────

class FacecamRectPayload(BaseModel):
    """Caixa da facecam em frações (0–1) da fonte."""

    x: float = Field(ge=0, lt=1)
    y: float = Field(ge=0, lt=1)
    w: float = Field(gt=0, le=1)
    h: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def validate_inside_frame(self) -> "FacecamRectPayload":
        if self.x + self.w > 1.0 or self.y + self.h > 1.0:
            raise ValueError("A caixa da facecam ultrapassa os limites do vídeo")
        return self


class JobCreate(BaseModel):
    # De qual perfil veio este job. Opcional de propósito: a API continua
    # aceitando exatamente o payload de antes, sem perfil nenhum — o pipeline
    # não lê este campo, quem ele lê é `source_type`.
    profile_id: Optional[str] = None
    youtube_url: str
    subtitle_mode: Literal["word_highlight", "traditional", "none"] = "word_highlight"
    # Sem default fixo: "cover" só serve a podcast, e cravá-lo aqui fazia um
    # pedido de gameplay sem layout ser recusado. Omitido, o layout é derivado
    # do perfil ou da rubrica (ver routers/jobs.py).
    layout_mode: Optional[LayoutField] = None
    # Muda a rubrica da análise e define a conta no cronograma de postagem.
    # Omitido = inferido do layout_mode (streamer→gameplay, cover→podcast).
    # Quais nichos são aceitos depende do build (ver app/features.py).
    source_type: Optional[SourceTypeField] = None
    # "compilation" pede um compilado; sem material que se sustente como
    # compilado, o pipeline entrega clipes individuais do jeito de sempre.
    clip_mode: Literal["individual", "compilation"] = "individual"
    # Trechos marcados à mão, como digitados ("3:24 - 4:10, 12:05 - 12:40").
    manual_clips: Optional[str] = None
    # Só tem efeito junto de manual_clips.
    manual_mode: Literal["only", "plus"] = "only"
    # Só no modo streamer: posição da facecam. Omitido = detecção automática.
    facecam_rect: Optional[FacecamRectPayload] = None

    @field_validator("manual_clips")
    @classmethod
    def validate_manual_clips(cls, v: Optional[str]) -> Optional[str]:
        """
        Recusa a lista aqui, e não no pipeline.

        Erro de digitação num trecho é do usuário e tem conserto imediato: a
        mensagem do parser diz QUAL pedaço está errado. Deixar passar faria o
        job baixar 7 GB e falhar depois, ou pior, cortar o trecho errado em
        silêncio.
        """
        if v is None or not v.strip():
            return None
        try:
            parse_ranges(v)
        except TimecodeError as exc:
            raise ValueError(str(exc)) from exc
        return v

    @field_validator("youtube_url")
    @classmethod
    def validate_youtube_url(cls, v: str) -> str:
        v = v.strip()
        if not _YOUTUBE_URL_RE.match(v):
            raise ValueError("URL inválida: forneça um link do YouTube (youtube.com ou youtu.be)")
        return v


class JobResponse(BaseModel):
    id: str
    youtube_url: str
    video_title: Optional[str]
    channel_name: Optional[str]
    duration_seconds: Optional[float]
    thumbnail_url: Optional[str]
    profile_id: Optional[str] = None
    subtitle_mode: str
    layout_mode: str = "cover"
    source_type: str = "podcast"
    clip_mode: str = "individual"
    manual_clips: Optional[list] = None
    manual_mode: str = "only"
    facecam_rect: Optional[dict] = None
    status: str
    error_message: Optional[str]
    # Por que terminou sem clips (ver models.Job.result_note).
    result_note: Optional[str] = None
    # Quando cada etapa começou, para a tela mostrar o tempo real de cada uma.
    stage_log: Optional[list] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("stage_log", mode="before")
    @classmethod
    def parse_stage_log(cls, v):
        """A coluna guarda JSON; a API entrega a lista pronta."""
        if v is None or isinstance(v, list):
            return v
        try:
            marcas = json.loads(v)
        except (json.JSONDecodeError, TypeError):
            return None
        return marcas if isinstance(marcas, list) else None

    @field_validator("layout_mode", mode="before")
    @classmethod
    def default_layout_mode(cls, v: Optional[str]) -> str:
        # Jobs criados antes da coluna existir vêm sem valor
        return v or "cover"

    @field_validator("manual_clips", mode="before")
    @classmethod
    def parse_manual_clips(cls, v):
        """A coluna guarda JSON serializado; a API entrega a lista."""
        if not v:
            return None
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return None
        return v

    @field_validator("facecam_rect", mode="before")
    @classmethod
    def parse_facecam_rect(cls, v):
        """A coluna guarda JSON serializado; a API entrega o objeto."""
        if not isinstance(v, str):
            return v
        try:
            return json.loads(v)
        except json.JSONDecodeError:
            return None


# ─── Clip ──────────────────────────────────────────────────────────────────────

class ClipResponse(BaseModel):
    id: str
    job_id: str
    start_time: float
    end_time: float
    duration: float
    virality_score: float
    # Eixos da rubrica (0-10). O cronograma escolhe o clip de cada horário por
    # um deles; ficam nulos em clips analisados antes da rubrica de 5 eixos.
    hook_score: Optional[float] = None
    retention_score: Optional[float] = None
    shareability_score: Optional[float] = None
    loopability_score: Optional[float] = None
    comment_bait_score: Optional[float] = None
    verdict: Optional[str] = None
    weak_points_json: Optional[str] = None
    trim_reason: Optional[str] = None
    segments_json: Optional[str] = None
    hook: Optional[str]
    reason: Optional[str]
    tags_json: Optional[str]
    suggested_title: Optional[str]
    transcript_excerpt: Optional[str]
    part_number: Optional[int]
    parent_clip_id: Optional[str]
    subtitle_mode: str
    status: str
    file_path: Optional[str]
    file_size_bytes: Optional[int]
    created_at: datetime
    # Desempenho real depois de postado. Nulo = ainda não medido.
    posted_at: Optional[datetime] = None
    views: Optional[int] = None
    completion_rate: Optional[float] = None
    likes: Optional[int] = None
    comments: Optional[int] = None
    shares: Optional[int] = None
    metrics_at: Optional[datetime] = None


class ClipMetricsRequest(BaseModel):
    """
    Desempenho real de um clipe já postado.

    Todos os campos são opcionais e aplicados um a um: dá para registrar só as
    views hoje e a retenção amanhã sem apagar o que já estava lá. Passar um
    campo com valor nulo não limpa nada — para isso existe o DELETE.
    """

    posted_at: Optional[datetime] = None
    views: Optional[int] = Field(None, ge=0)
    completion_rate: Optional[float] = Field(None, ge=0.0, le=1.0)
    likes: Optional[int] = Field(None, ge=0)
    comments: Optional[int] = Field(None, ge=0)
    shares: Optional[int] = Field(None, ge=0)

    model_config = {"from_attributes": True}


# ─── Job Detail (com clips aninhados) ─────────────────────────────────────────

class JobDetailResponse(JobResponse):
    clips: List[ClipResponse] = []

    #: Créditos deste job, para a tela dizer o que foi gasto.
    #: `reservado` enquanto roda, `cobrado` depois que fecha. Nulos na versão
    #: pessoal e em jobs anteriores à cobrança — lá não há o que mostrar.
    creditos_reservados: Optional[int] = None
    creditos_cobrados: Optional[int] = None
    saldo: Optional[int] = None

    model_config = {"from_attributes": True}


# ─── Validação de exemplo (few-shot) ──────────────────────────────────────────

class ValidateClipRequest(BaseModel):
    performance: Literal["viral", "muito_bom", "bom"]
    aprendizado: str = ""
    views: Optional[int] = None


class ValidateClipResponse(BaseModel):
    example_path: str
    clip_id: str


# ─── Referência (aprender com clipe viral de outro criador) ───────────────────

class ReferenceResponse(BaseModel):
    id: str
    # 'aligned' = veio com o vídeo original e foi localizado dentro dele.
    # 'standalone' = só o arquivo do clipe, periciado por si (ver models.py).
    kind: Literal["aligned", "standalone"] = "aligned"
    source_type: str = "podcast"
    # No modo standalone pode ser o link do post, ou vazio quando nem isso se sabe.
    source_url: str
    source_title: Optional[str]
    source_channel: Optional[str]
    source_duration: Optional[float]
    language: Optional[str]
    source_start: Optional[float]
    source_end: Optional[float]
    alignment_confidence: Optional[float]
    clip_duration: Optional[float]
    analysis: Optional[dict] = None       # analysis_json parseado
    # Só no modo standalone: a perícia detalhada (gancho, batidas, som, estilo
    # visual, regras transferíveis). forensics_json parseado.
    forensics: Optional[dict] = None
    opening_phrase: Optional[str]
    transcript_excerpt: Optional[str]
    performance: Optional[str]
    views: Optional[int]
    notas: Optional[str]
    status: str
    error_message: Optional[str]
    published: bool
    example_path: Optional[str]
    created_at: datetime
    updated_at: datetime


class ReferenceUpdateRequest(BaseModel):
    """Ajustes do usuário sobre a referência analisada."""
    source_start: Optional[float] = None
    source_end: Optional[float] = None
    performance: Optional[Literal["viral", "muito_bom", "bom"]] = None
    views: Optional[int] = None
    notas: Optional[str] = None
    reanalyze: bool = False               # re-roda a análise reversa com o novo intervalo


class ReferenceConfirmResponse(BaseModel):
    reference_id: str
    example_path: str


# ─── Melhorar vídeo ───────────────────────────────────────────────────────────

class VideoEnhanceJobResponse(BaseModel):
    id: str
    original_filename: Optional[str] = None
    status: Literal["pending", "processing", "done", "failed"]
    # Etapa atual ("fazendo upscale"). Só preenchido durante o trabalho.
    status_detail: Optional[str] = None
    # Em 'failed', o motivo. Em 'done', o aviso das etapas que falharam — o
    # vídeo existe do mesmo jeito.
    error_message: Optional[str] = None
    # Antes/depois em texto, para a tela mostrar o ganho em vez de prometê-lo.
    source_summary: Optional[str] = None
    final_summary: Optional[str] = None
    steps_applied: list[str] = []
    # Dispensadas por já estarem no alvo — não são problema.
    steps_skipped: list[str] = []
    has_video: bool = False
    created_at: datetime
    updated_at: datetime


# ─── Cobrança ─────────────────────────────────────────────────────────────────


class TopupRequest(BaseModel):
    """Compra de um pacote de créditos.

    Só o número de créditos: o preço é resolvido no servidor pela
    billing_config. Aceitar valor vindo do cliente seria deixar o comprador
    escolher quanto paga.
    """

    creditos: int = Field(..., gt=0, description="Créditos do pacote escolhido")


class TopupResponse(BaseModel):
    payment_id: str
    creditos: int
    valor_brl: Decimal
    status: str
    qr_code: str | None = None
    qr_code_base64: str | None = None
    expires_at: datetime | None = None


class PaymentStatusResponse(BaseModel):
    """O que o polling da tela de recarga precisa saber."""

    payment_id: str
    status: str
    creditos: int
    #: O saldo DEPOIS deste pagamento, para a tela atualizar sem outra chamada.
    saldo: int


class BalanceResponse(BaseModel):
    """O saldo para a navbar. Chamado em toda página, então é magro de propósito."""

    saldo: int
    #: Abaixo disto a interface avisa. Vem da billing_config, não do frontend:
    #: "baixo" é decisão de negócio e muda sem deploy.
    threshold: int
    baixo: bool


class PacoteResponse(BaseModel):
    creditos: int
    preco_brl: Decimal


class PlanoResponse(BaseModel):
    code: str
    nome: str
    valor_brl: Decimal
    creditos_mes: int


class CatalogResponse(BaseModel):
    """O que a tela de recarga oferece. Preço sempre resolvido no servidor."""

    credito_avulso_brl: Decimal
    pacotes: List[PacoteResponse]
    planos: List[PlanoResponse]


class LedgerEntryResponse(BaseModel):
    id: str
    tipo: str
    amount: int
    balance_after: int
    descricao: Optional[str] = None
    created_at: datetime
    ref_payment_id: Optional[str] = None
    ref_usage_id: Optional[str] = None

    model_config = {"from_attributes": True}


class EstimateRequest(BaseModel):
    youtube_url: str


class EstimateResponse(BaseModel):
    """O aviso antes de gastar: quanto este vídeo custa e se dá.

    Passa pelas MESMAS guardas da criação do job (live, teto de duração), para a
    tela não prometer um vídeo que o servidor vai recusar em seguida.
    """

    minutos: int
    creditos: int
    saldo: int
    suficiente: bool
    #: Quantos créditos faltam. 0 quando dá.
    faltam: int


class SubscribeRequest(BaseModel):
    plan_code: str


class SubscriptionResponse(BaseModel):
    """A assinatura desta pessoa.

    `init_point` é o link do gateway onde ela autoriza o cartão. Vem preenchido
    enquanto o status é `pending` — é o que permite retomar quem fechou a aba no
    meio, em vez de criar uma segunda assinatura.
    """

    id: str
    plan_code: str
    valor_brl: Decimal
    creditos_mes: int
    status: str
    init_point: Optional[str] = None
    started_at: Optional[datetime] = None
    current_period_end: Optional[datetime] = None
    canceled_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ─── Painel do dono ───────────────────────────────────────────────────────────


class OverviewResponse(BaseModel):
    periodo: str

    mrr_brl: Decimal
    assinantes_ativos: int
    novos_no_mes: int
    cancelados_no_mes: int
    churn_pct: Decimal

    receita_bruta_brl: Decimal
    taxas_gateway_brl: Decimal
    receita_liquida_brl: Decimal
    pagamentos: int

    custo_variavel_brl: Decimal
    custo_fixo_brl: Decimal
    imposto_brl: Decimal

    lucro_liquido_brl: Decimal
    margem_liquida_pct: Decimal

    #: Custou e não recebeu: job que falhou ou foi excluído em andamento.
    prejuizo_devolvido_brl: Decimal
    videos_devolvidos: int
    videos_processados: int

    taxas_estimadas: int
    imposto_pct: Decimal
    avisos: List[str] = []

    model_config = {"from_attributes": True}


class OverviewComparadoResponse(BaseModel):
    """Mês corrente ao lado do anterior — número sozinho não diz se melhorou."""

    atual: OverviewResponse
    anterior: OverviewResponse


class SerieDiaResponse(BaseModel):
    dia: str
    receita_brl: Decimal
    custo_brl: Decimal
    lucro_brl: Decimal

    model_config = {"from_attributes": True}


class UsuarioNoPeriodoResponse(BaseModel):
    user_id: str
    email: str
    receita_brl: Decimal
    custo_brl: Decimal
    resultado_brl: Decimal
    videos: int
    deficitario: bool

    model_config = {"from_attributes": True}


class CostConfigResponse(BaseModel):
    assemblyai_usd_per_min: Decimal
    llm_rates: dict
    storage_usd_per_video: Decimal
    fx_usd_brl: Decimal
    fx_eur_brl: Decimal
    fixed_cost_brl_month: Decimal
    tax_pct_on_revenue: Decimal
    gateway_fee_pct: Decimal
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class CostConfigUpdate(BaseModel):
    """Só o que veio é alterado. Nada aqui reescreve evento já gravado."""

    assemblyai_usd_per_min: Optional[Decimal] = None
    llm_rates: Optional[dict] = None
    storage_usd_per_video: Optional[Decimal] = None
    fx_usd_brl: Optional[Decimal] = None
    fx_eur_brl: Optional[Decimal] = None
    fixed_cost_brl_month: Optional[Decimal] = None
    tax_pct_on_revenue: Optional[Decimal] = None
    gateway_fee_pct: Optional[Decimal] = None


class ManualPaymentRequest(BaseModel):
    """Um recebimento que não veio pelo gateway."""

    email: str
    valor_brl: Decimal = Field(..., ge=0)
    taxa_brl: Optional[Decimal] = None
    #: Informe a referência do Pix (o E2E do comprovante) e o banco passa a
    #: recusar o mesmo recebimento lançado duas vezes.
    referencia: Optional[str] = None
    pago_em: Optional[datetime] = None
    plan_code: Optional[str] = None
    #: Registrar receita e ENTREGAR crédito são coisas diferentes. Padrão é só
    #: registrar — conceder por engano daria crédito de graça.
    conceder_creditos: bool = False
    creditos: int = 0


class ManualStatusRequest(BaseModel):
    status: Literal["paid", "refunded", "chargeback"]


class ManualSubscriptionRequest(BaseModel):
    email: str
    plan_code: str
    valor_brl: Decimal = Field(..., ge=0)
    creditos_mes: int = Field(..., ge=0)
    started_at: Optional[datetime] = None


class PaymentAdminResponse(BaseModel):
    id: str
    user_id: str
    gateway: str
    gateway_payment_id: str
    tipo: str
    amount_brl_gross: Decimal
    gateway_fee_brl: Optional[Decimal] = None
    credits_granted: int
    status: str
    paid_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class SubscriptionAdminResponse(BaseModel):
    id: str
    user_id: str
    plan_code: str
    valor_brl: Decimal
    creditos_mes: int
    status: str
    gateway: str
    started_at: Optional[datetime] = None
    canceled_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
