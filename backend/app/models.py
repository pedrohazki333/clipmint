from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import relationship

from app.database import Base


def uuid4_hex() -> str:
    return uuid4().hex


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


#: JSON que vira JSONB no Postgres (indexável, comparável) e JSON comum no
#: SQLite dos testes. Sem a variante, o Postgres guardaria texto e o painel
#: financeiro não teria como consultar dentro do documento.
JSONVariant = JSON().with_variant(postgresql.JSONB(), "postgresql")


class User(Base):
    """
    Uma conta do produto público.

    Existe para duas coisas que o produto público não tem como fazer sem ela:
    separar o que é de cada um, e cobrar o limite de uso de alguém (o rate limit
    da Fatia 7 conta vídeos e minutos POR usuário — sem identidade, o limite
    seria por IP e qualquer um o contornaria).

    A versão pessoal continua com a senha única compartilhada; quando ela roda,
    existe UM usuário-dono e todos os jobs são dele. Ou seja, o modelo é o mesmo
    nas duas versões e o pipeline não precisa saber em qual está.

    A autenticação de verdade (cadastro, login, sessão) é da Fatia 6. Aqui fica
    só o schema, para o banco nascer certo de uma vez e não precisar de uma
    segunda migração depois do Postgres já estar em produção.
    """

    __tablename__ = "users"

    id = Column(String, primary_key=True, default=uuid4_hex)
    # Guardado em minúsculas e sem espaços (normalizado na criação): senão o
    # mesmo endereço vira duas contas conforme quem digitou usou maiúscula.
    email = Column(String, nullable=False, unique=True, index=True)
    # Hash, nunca a senha. O algoritmo entra na Fatia 6 junto do login; a coluna
    # nasce aqui para o schema não mudar depois do deploy.
    password_hash = Column(String, nullable=False, default="")
    display_name = Column(String, nullable=True)
    # Desligar uma conta sem apagar o histórico dela.
    is_active = Column(Boolean, nullable=False, default=True)
    # O dono da instalação: na versão pessoal é o usuário único; no público, quem
    # administra. Não dá privilégio nenhum ainda — só marca quem é.
    is_owner = Column(Boolean, nullable=False, default=False)
    # Saldo de créditos, em CRÉDITOS INTEIROS (1 crédito = 1 minuto de vídeo).
    #
    # É um cache do `credit_ledger`, e o ledger é a fonte da verdade. A coluna
    # existe por duas razões, e a segunda é a que importa: (1) o saldo é lido a
    # cada página e a cada criação de job, e somar um ledger append-only cresce
    # sem teto; (2) é esta LINHA que é travada com SELECT ... FOR UPDATE antes
    # de cada lançamento, e é esse lock que impede dois jobs simultâneos de
    # gastarem o mesmo saldo. Derivar por SUM() precisaria do mesmo lock.
    #
    # Nunca escreva aqui direto: todo lançamento passa por services/credits.py,
    # que atualiza esta coluna e insere no ledger na MESMA transação.
    credit_balance = Column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    jobs = relationship("Job", back_populates="user")


class Session(Base):
    """
    Uma sessão aberta — o que o cookie do navegador representa.

    Guardada no banco, e não num JWT, por um motivo concreto: sessão em token
    assinado não dá para revogar antes de expirar. Aqui, "sair de todos os
    aparelhos" e "desativar a conta" são um DELETE, e a sessão morre na hora.
    O custo é uma consulta por request, indexada por chave primária.

    O que fica gravado é o HASH do token, nunca o token. Quem conseguir ler a
    tabela — um dump, um backup vazado — não consegue se passar por ninguém.
    Um SHA-256 basta e é o certo aqui: o token tem 256 bits de entropia vinda do
    `secrets`, então não há o que adivinhar por força bruta, e um hash lento
    (como o das senhas) só tornaria cada request mais caro sem ganho nenhum.
    """

    __tablename__ = "sessions"

    token_hash = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    # Só para o usuário reconhecer a sessão numa futura tela de "aparelhos
    # conectados". Não é usado em nenhuma decisão de segurança.
    user_agent = Column(String, nullable=True)

    user = relationship("User")


class Profile(Base):
    """
    Um perfil: o conjunto de configurações que se repete de vídeo para vídeo.

    O que ele é, e o que ele NÃO é. Antes desta tabela, "conta" era um valor de
    enum (`podcast` | `gameplay` | `siege`) escrito em código, com uma pasta de
    presets no disco. Isso bastava enquanto as contas eram fixas e eram do dono
    da instalação; num produto com vários usuários, cada um precisa das suas.

    **`source_type` continua sendo a fonte de verdade do pipeline.** O perfil é
    quem FORNECE esse valor na criação do job, não quem o substitui: analyzer,
    clipper, layout, watermark e cronograma seguem lendo `jobs.source_type` como
    sempre. Trocar isso faria todo job antigo perder a rubrica.

    Por isso `source_type` aqui é a rubrica BASE, escolhida entre as que existem
    — um perfil não inventa critérios de análise novos.

    Os defaults de layout e legenda são só isso: o que o formulário de geração
    vem preenchido. O job continua gravando os próprios valores, então mudar o
    perfil não reescreve o passado.
    """

    __tablename__ = "profiles"

    id = Column(String, primary_key=True, default=uuid4_hex)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    # Rubrica base. Validada contra os nichos que o build permite — um perfil não
    # dá acesso a um nicho que a versão não tem.
    source_type = Column(String, nullable=False, default="podcast")
    # Chave de um ícone da interface ("mic", "gamepad", "person"), não um arquivo:
    # upload de avatar seria funcionalidade nova, e não é disso que se trata aqui.
    avatar = Column(String, nullable=True)
    # Defaults do formulário de geração. O nicho já carregava um layout padrão em
    # código (`NichePage` passava `defaultLayout`); isto move esse padrão para o
    # dado, sem mudar o que ele significa.
    default_layout_mode = Column(String, nullable=False, default="cover")
    default_subtitle_mode = Column(String, nullable=False, default="word_highlight")
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    user = relationship("User")
    jobs = relationship("Job", back_populates="profile")


class Job(Base):
    __tablename__ = "jobs"

    id = Column(String, primary_key=True, default=uuid4_hex)
    # Dono do job. NULO é permitido de propósito: os jobs que já existiam quando
    # a coluna nasceu não têm dono, e inventar um seria pior que admitir a
    # ausência. Job sem dono só aparece para quem administra.
    user_id = Column(String, ForeignKey("users.id"), nullable=True, index=True)
    # Perfil que originou este job. NULO nos jobs criados antes de haver perfis —
    # mesma razão do user_id: inventar um dono seria pior que admitir a ausência.
    # O pipeline não lê esta coluna; quem ele lê é `source_type`, que o perfil
    # preencheu na criação.
    profile_id = Column(String, ForeignKey("profiles.id"), nullable=True, index=True)
    youtube_url = Column(String, nullable=False)
    video_title = Column(String, nullable=True)
    channel_name = Column(String, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    thumbnail_url = Column(String, nullable=True)
    video_path = Column(String, nullable=True)
    audio_path = Column(String, nullable=True)
    subtitle_mode = Column(String, default="word_highlight")  # word_highlight | traditional | none
    layout_mode = Column(String, default="cover")   # cover (capa+banner) | streamer (facecam+gameplay)
    # Muda a rubrica da análise (critérios de podcast x gameplay) e define em
    # qual conta o clip é postado no cronograma. Default vem do layout_mode.
    source_type = Column(String, default="podcast")  # podcast | gameplay
    # individual: um clipe por momento, como sempre. compilation: PROCURA um
    # compilado (vários momentos costurados num vídeo só) e, não achando, cai
    # de volta em clipes individuais — o modo é um pedido, não uma promessa.
    clip_mode = Column(String, default="individual")  # individual | compilation
    # Trechos que o usuário marcou assistindo, JSON [[inicio, fim], ...] em
    # segundos, NA ORDEM EM QUE FORAM DIGITADOS — num compilado essa ordem é a
    # montagem. Nulo = nenhum trecho indicado.
    manual_clips = Column(Text, nullable=True)
    # only: corta só os trechos indicados. plus: eles entram garantidos e a
    # análise segue procurando outros.
    manual_mode = Column(String, default="only")  # only | plus
    # Caixa da facecam em frações da fonte, JSON {x,y,w,h,confidence,method}.
    # Detectada no 1º clip e reusada nos demais; editável pelo usuário.
    facecam_rect = Column(Text, nullable=True)
    status = Column(String, default="queued")  # queued|downloading|transcribing|analyzing|clipping|done|error
    error_message = Column(String, nullable=True)
    # Por que este job terminou sem clips. Um job 'done' com zero clips tem mais
    # de uma causa (nenhum trecho passou do threshold, o vídeo não tinha fala,
    # os candidatos eram do streamer morto) e a tela afirmava sempre a primeira.
    # Nulo = terminou com clips, ou é um job anterior a esta coluna.
    result_note = Column(String, nullable=True)
    # Registro append-only das trocas de status: [{"s": "downloading", "at": iso}].
    # É o que permite à tela mostrar quanto CADA etapa levou, em vez de uma
    # porcentagem inventada. Append-only de propósito: derivar a duração de uma
    # etapa é diferença entre duas marcas consecutivas, e assim nenhuma escrita
    # precisa saber qual era a etapa anterior.
    stage_log = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    transcript = relationship("Transcript", back_populates="job", uselist=False)
    clips = relationship("Clip", back_populates="job")
    user = relationship("User", back_populates="jobs")
    profile = relationship("Profile", back_populates="jobs")

    # A tela de cada conta lista "meus jobs, do mais novo para o mais velho", e
    # é a consulta mais repetida do produto (todo polling passa por ela).
    __table_args__ = (Index("ix_jobs_user_created", "user_id", "created_at"),)


class Transcript(Base):
    __tablename__ = "transcripts"

    id = Column(String, primary_key=True, default=uuid4_hex)
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False)
    full_text = Column(Text, nullable=False)
    words_json_path = Column(String, nullable=False)  # path pro JSON com word-level timestamps
    language = Column(String, nullable=True)
    confidence = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    job = relationship("Job", back_populates="transcript")


class ReferenceExample(Base):
    """
    Exemplo de aprendizado a partir de um clipe viral de OUTRO criador.

    Há dois jeitos de aprender com um clipe alheio, e `kind` diz qual foi usado:

    'aligned' — o usuário tem a URL do vídeo ORIGINAL. O pipeline baixa o
      original, transcreve os dois e localiza onde o corte foi feito
      (services/aligner.py). Responde a melhor pergunta possível: por que ESTE
      recorte e não o de dois minutos antes — porque sabe o que ficou de fora.
      Status: queued → downloading_source → transcribing → aligning → analyzing → done

    'standalone' — só o arquivo do clipe, tipicamente salvo do TikTok. O
      original é desconhecido (ou é uma live de 6h que não vale baixar), então
      não há o que alinhar e o objeto de estudo passa a ser o clipe em si:
      fala, som e imagem periciados segundo a segundo (services/clip_forensics.py).
      Status: queued → extracting → transcribing → watching → analyzing → done

    Nos dois casos o resultado NÃO vira exemplo few-shot sozinho: fica esperando
    a confirmação do usuário, que informa a performance real antes de publicar
    em prompt_engine/examples/validated/.

    Qualquer etapa pode ir para: error.
    """

    __tablename__ = "reference_examples"

    id = Column(String, primary_key=True, default=uuid4_hex)
    kind = Column(String, default="aligned")         # aligned | standalone (ver docstring)
    # No modo standalone não existe vídeo de origem: a coluna guarda o link do
    # post (TikTok/Reels), quando o usuário souber, ou string vazia. Continua
    # NOT NULL porque o SQLite não afrouxa isso por ALTER TABLE e o projeto não
    # usa Alembic — vazio custa menos que uma tabela reescrita.
    source_url = Column(String, nullable=False)      # URL do vídeo original (YouTube) ou do post
    clip_path = Column(String, nullable=False)       # arquivo do clipe viral enviado
    # Nicho a que a referência pertence (podcast | gameplay | siege). Só rótulo:
    # o few-shot hoje é comum às três contas, e o campo existe para a leitura
    # ser atribuível a um nicho quando isso deixar de ser verdade.
    source_type = Column(String, default="podcast")

    # Metadados do vídeo original (preenchidos após download)
    source_title = Column(String, nullable=True)
    source_channel = Column(String, nullable=True)
    source_duration = Column(Float, nullable=True)
    language = Column(String, nullable=True)

    # Resultado do alinhamento clipe ↔ original
    source_start = Column(Float, nullable=True)
    source_end = Column(Float, nullable=True)
    alignment_confidence = Column(Float, nullable=True)  # 0.0–1.0
    clip_duration = Column(Float, nullable=True)

    # Análise reversa gerada pelo Claude (JSON serializado)
    analysis_json = Column(Text, nullable=True)      # {hook, suggested_title, reason, tags, virality_score}
    # Só no modo standalone: a perícia detalhada do clipe (gancho quadro a
    # quadro, batidas, papel do som, estilo visual, regras transferíveis).
    # Separada de analysis_json porque aquele campo tem o mesmo formato dos dois
    # modos e é o que o confirm() publica como exemplo.
    forensics_json = Column(Text, nullable=True)
    opening_phrase = Column(String, nullable=True)
    transcript_excerpt = Column(Text, nullable=True)

    # Dados fornecidos pelo usuário na confirmação (performance real)
    performance = Column(String, nullable=True)      # viral | muito_bom | bom
    views = Column(Integer, nullable=True)
    notas = Column(Text, nullable=True)

    # Estado
    status = Column(String, default="queued")        # ver docstring
    error_message = Column(String, nullable=True)
    published = Column(Integer, default=0)           # 1 = já gravado em validated/
    example_path = Column(String, nullable=True)     # caminho do JSON publicado
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class VideoEnhanceJob(Base):
    """
    Melhoria de um vídeo enviado pelo usuário.

    O vídeo vem pronto de fora (na prática, gerado no app do Gemini/Flow, que
    entrega 720p com bitrate baixo) e aqui passa pelo tratamento local: upscale
    para 1080p, interpolação se estiver abaixo do fps alvo, e reencode com
    bitrate limpo. Cada etapa é pulada quando a fonte já está no alvo.

    Pipeline de status:
      pending → processing → done | failed

    `status_detail` é o texto que a UI mostra durante as etapas ("fazendo
    upscale"); sem ele a tela fica parada num status só enquanto o FFmpeg roda.
    """

    __tablename__ = "video_enhance_jobs"

    id = Column(String, primary_key=True, default=uuid4_hex)
    original_filename = Column(String, nullable=True)   # como o usuário chamou
    source_video_path = Column(String, nullable=False)  # o arquivo enviado
    final_video_path = Column(String, nullable=True)    # depois do tratamento
    # Antes/depois, para a tela justificar o tratamento em vez de só afirmar.
    source_summary = Column(String, nullable=True)      # ex.: "720x1280 · 24fps · 1.9 Mbps"
    final_summary = Column(String, nullable=True)
    # Etapas que rodaram e as que foram dispensadas/falharam, JSON de listas.
    steps_json = Column(Text, nullable=True)
    status = Column(String, default="pending")  # pending|processing|done|failed
    status_detail = Column(String, nullable=True)
    error_message = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Clip(Base):
    __tablename__ = "clips"

    id = Column(String, primary_key=True, default=uuid4_hex)
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False)
    start_time = Column(Float, nullable=False)
    end_time = Column(Float, nullable=False)
    duration = Column(Float, nullable=False)
    virality_score = Column(Float, nullable=False)  # 0-10, é o final_score/10
    # Eixos da rubrica (0-10 cada). Guardados individualmente porque o
    # cronograma escolhe o clip de cada horário por um eixo específico —
    # 07:00 pega o maior hook_score, 22:30 o maior loopability_score.
    hook_score = Column(Float, nullable=True)
    retention_score = Column(Float, nullable=True)
    shareability_score = Column(Float, nullable=True)
    loopability_score = Column(Float, nullable=True)
    comment_bait_score = Column(Float, nullable=True)
    verdict = Column(String, nullable=True)         # post | revisar_corte
    weak_points_json = Column(String, nullable=True)  # JSON array de trechos fracos
    trim_reason = Column(String, nullable=True)     # por que o corte é esse
    # Trechos costurados num clipe só, JSON [[ini,fim],...] (só Siege).
    # Nulo = clipe contínuo comum entre start_time e end_time.
    segments_json = Column(Text, nullable=True)
    hook = Column(String, nullable=True)
    reason = Column(String, nullable=True)
    tags_json = Column(String, nullable=True)       # JSON array de tags
    suggested_title = Column(String, nullable=True)
    transcript_excerpt = Column(Text, nullable=True)
    part_number = Column(Integer, nullable=True)    # 1, 2 (null se não dividido)
    parent_clip_id = Column(String, nullable=True)  # referência ao clip original se dividido
    subtitle_mode = Column(String, default="word_highlight")
    status = Column(String, default="processing")   # processing|ready|error
    file_path = Column(String, nullable=True)
    file_size_bytes = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    # ── Desempenho real depois de postado ─────────────────────────────────────
    # A nota é uma previsão; estes campos são o que aconteceu. Sem eles o
    # sistema não tem como saber que um 8.4 rendeu mal, e o few-shot dinâmico
    # (prompt_engine/) fica aprendendo só com rótulo manual. Nulo = ainda não
    # medido, que é diferente de zero.
    posted_at = Column(DateTime(timezone=True), nullable=True)
    views = Column(Integer, nullable=True)
    # Fração de quem chegou ao fim (0-1). É o sinal que o algoritmo mais pesa,
    # e o único que distingue "muita gente viu" de "muita gente ficou".
    completion_rate = Column(Float, nullable=True)
    likes = Column(Integer, nullable=True)
    comments = Column(Integer, nullable=True)
    shares = Column(Integer, nullable=True)
    # Quando os números acima foram coletados — views de um clipe de 3 dias e
    # de um de 3 meses não são comparáveis sem isto.
    metrics_at = Column(DateTime(timezone=True), nullable=True)

    job = relationship("Job", back_populates="clips")


# ─── Cobrança: créditos, pagamentos e assinaturas ─────────────────────────────
#
# A unidade é o CRÉDITO: 1 crédito = 1 minuto de vídeo de origem, sempre inteiro
# (`ceil` dos minutos). Crédito fracionário em ponto flutuante vira saldo de
# 29.999999 e discussão com o usuário; o inteiro não tem esse problema.
#
# Dinheiro é Numeric, nunca Float, pelo mesmo motivo e com mais consequência.

#: Tipos de lançamento aceitos no ledger.
#:
#: `hold` e `release` são o par que segura o custo estimado enquanto o job roda:
#: o hold sai do saldo na hora (é o que impede disparar dez jobs com saldo para
#: um), e no fim o `debito` cobra o consumo real e o `release` devolve a
#: diferença. `ajuste` é o único que pode deixar o saldo negativo, e é de admin.
TIPOS_LANCAMENTO = (
    "topup",
    "debito",
    "estorno",
    "bonus",
    "ajuste",
    "hold",
    "release",
)

STATUS_PAGAMENTO = ("pending", "paid", "refunded", "chargeback")
#: `pending` = criada no gateway, esperando a pessoa autorizar o cartão na
#: página dele. É onde a assinatura passa mais tempo no começo, e usar
#: `paused` para isso seria mentir no banco.
STATUS_ASSINATURA = ("pending", "active", "canceled", "paused")


def _em(coluna: str, valores: tuple[str, ...]) -> str:
    """SQL `coluna IN (...)` para um CHECK, com os valores escapados."""
    lista = ", ".join(f"'{v}'" for v in valores)
    return f"{coluna} IN ({lista})"


class BillingConfig(Base):
    """Preços e cotas editáveis. Uma linha só, `id = 1`.

    Existe como TABELA e não como variável de ambiente porque preço muda com o
    negócio, não com o deploy: o dono precisa poder ajustar o preço do crédito
    ou criar um pacote com desconto sem reiniciar o servidor. O `CHECK (id = 1)`
    é o que garante que ela continue sendo uma configuração e não vire um
    histórico acidental de configurações.

    Nada aqui é lido pelo cliente para virar preço: o servidor resolve o valor
    no momento do checkout e CONGELA o resultado em `payments`. Editar um preço
    amanhã não pode reescrever o que já foi vendido.
    """

    __tablename__ = "billing_config"

    id = Column(Integer, primary_key=True, default=1)

    #: Preço de UM crédito na compra avulsa, em reais. 4 casas porque o preço
    #: unitário é pequeno (R$ 0,12) e arredondar cedo distorce o pacote inteiro.
    credito_avulso_brl = Column(Numeric(12, 4), nullable=False)

    #: Pacotes avulsos: [{"creditos": 300, "preco_brl": null}, ...]
    #:
    #: `preco_brl` nulo = o preço deriva de `credito_avulso_brl`. Preenchido = é
    #: um pacote com desconto. Guardar objeto em vez de só o número de créditos
    #: é o que permite dar desconto no pacote grande sem migração nova.
    pacotes = Column(JSONVariant, nullable=False)

    #: Planos de assinatura:
    #: [{"code": "pro", "nome": "Pro", "valor_brl": "99.90", "creditos_mes": 1200}]
    #: `code` é o que vai para `subscriptions.plan_code` e não deve mudar depois
    #: de vendido — o nome e o valor podem.
    planos = Column(JSONVariant, nullable=False)

    #: Crédito de boas-vindas, concedido no cadastro. 0 desliga o trial.
    creditos_gratis_cadastro = Column(Integer, nullable=False)

    #: Abaixo disto a interface mostra o aviso de saldo baixo. O padrão é 120 —
    #: um vídeo médio deste produto tem ~2h, então "baixo" é não ter saldo para
    #: mais um vídeo típico.
    saldo_baixo_threshold = Column(Integer, nullable=False)

    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    updated_by_user_id = Column(String, ForeignKey("users.id"), nullable=True)

    __table_args__ = (
        CheckConstraint("id = 1", name="ck_billing_config_linha_unica"),
        CheckConstraint(
            "credito_avulso_brl > 0", name="ck_billing_config_preco_positivo"
        ),
        CheckConstraint(
            "creditos_gratis_cadastro >= 0", name="ck_billing_config_bonus_nao_negativo"
        ),
    )


class Subscription(Base):
    """Assinatura mensal de um usuário.

    `valor_brl` e `creditos_mes` são CÓPIA CONGELADA do plano no momento da
    adesão, e não uma referência ao plano vigente. Quem assinou o Pro a R$ 99,90
    continua nesse valor quando o Pro subir de preço — e a linha diz por quanto
    a venda foi feita, que é o que uma conciliação financeira precisa saber.
    """

    __tablename__ = "subscriptions"

    id = Column(String, primary_key=True, default=uuid4_hex)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)

    plan_code = Column(String, nullable=False)
    valor_brl = Column(Numeric(12, 2), nullable=False)
    creditos_mes = Column(Integer, nullable=False)

    status = Column(String, nullable=False, default="pending")

    gateway = Column(String, nullable=False, default="mercadopago")
    #: O id da recorrência no gateway (`preapproval` do Mercado Pago). É por ele
    #: que o webhook de cobrança do ciclo acha esta assinatura — sem a coluna, a
    #: notificação chega e não tem a quem ser atribuída. Nulo enquanto a
    #: assinatura está sendo criada e o gateway ainda não devolveu o id.
    gateway_preapproval_id = Column(String, nullable=True, unique=True)
    #: O link do gateway onde a pessoa autoriza o cartão. Guardado porque quem
    #: fecha a aba no meio do caminho precisa poder voltar — sem ele, clicar de
    #: novo criaria uma segunda assinatura no Mercado Pago.
    init_point = Column(String, nullable=True)

    started_at = Column(DateTime(timezone=True), nullable=True)
    current_period_end = Column(DateTime(timezone=True), nullable=True)
    canceled_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (
        CheckConstraint(_em("status", STATUS_ASSINATURA), name="ck_subscriptions_status"),
        CheckConstraint("creditos_mes >= 0", name="ck_subscriptions_creditos_mes"),
        CheckConstraint("valor_brl >= 0", name="ck_subscriptions_valor"),
    )


class Payment(Base):
    """Uma cobrança no gateway — avulsa (Pix) ou de um ciclo de assinatura.

    `gateway_payment_id` é UNIQUE, e essa restrição É a idempotência do webhook:
    o Mercado Pago reenvia notificação, e a garantia de creditar uma única vez
    tem que estar no banco, não na minha lógica de tratamento. Duas notificações
    simultâneas do mesmo pagamento passariam por qualquer verificação feita em
    Python; nenhuma passa por um índice único.
    """

    __tablename__ = "payments"

    id = Column(String, primary_key=True, default=uuid4_hex)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)

    gateway = Column(String, nullable=False, default="mercadopago")
    gateway_payment_id = Column(String, nullable=False, unique=True, index=True)

    #: topup = compra avulsa de créditos; assinatura = cobrança de um ciclo.
    tipo = Column(String, nullable=False)
    #: Preenchido só quando `tipo = 'assinatura'`: qual assinatura gerou a
    #: cobrança. É o que liga o ciclo pago aos créditos concedidos.
    subscription_id = Column(
        String, ForeignKey("subscriptions.id"), nullable=True, index=True
    )

    amount_brl_gross = Column(Numeric(12, 2), nullable=False)
    #: Taxa e líquido só existem DEPOIS da liquidação — o gateway não informa
    #: quanto vai cobrar quando a cobrança é criada. Nulo aqui significa "ainda
    #: não sabemos", e não "sem taxa".
    gateway_fee_brl = Column(Numeric(12, 2), nullable=True)
    amount_brl_net = Column(Numeric(12, 2), nullable=True)

    #: Quantos créditos esta compra concede. Congelado na criação a partir da
    #: billing_config vigente.
    credits_granted = Column(Integer, nullable=False)

    status = Column(String, nullable=False, default="pending")
    status_updated_at = Column(DateTime(timezone=True), default=utcnow)

    #: Dados do Pix para a tela de recarga desenhar o QR e o copia-e-cola.
    #: Ficam aqui, e não em memória, porque o usuário fecha a aba e volta.
    pix_qr_code = Column(Text, nullable=True)
    pix_qr_base64 = Column(Text, nullable=True)
    pix_expires_at = Column(DateTime(timezone=True), nullable=True)

    #: O payload do gateway como chegou. É o que resolve uma divergência de
    #: conciliação meses depois, quando ninguém lembra o que o MP respondeu.
    raw_gateway_payload = Column(JSONVariant, nullable=True)

    created_at = Column(DateTime(timezone=True), default=utcnow)
    paid_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(_em("status", STATUS_PAGAMENTO), name="ck_payments_status"),
        CheckConstraint(
            _em("tipo", ("topup", "assinatura")), name="ck_payments_tipo"
        ),
        CheckConstraint("credits_granted >= 0", name="ck_payments_creditos"),
        CheckConstraint("amount_brl_gross >= 0", name="ck_payments_valor"),
    )


class CreditLedger(Base):
    """Extrato de créditos. Append-only: nada é atualizado nem apagado aqui.

    É a fonte da verdade do saldo. `users.credit_balance` é cache, atualizado na
    mesma transação (ver services/credits.py) — os dois nunca podem divergir, e
    há teste de invariante justamente para isso.

    `balance_after` é redundante por construção, e é de propósito: é o que
    permite auditar o extrato linha a linha sem recomputar a soma inteira, e é
    o que denuncia na hora um lançamento que tenha escapado do serviço.
    """

    __tablename__ = "credit_ledger"

    id = Column(String, primary_key=True, default=uuid4_hex)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)

    tipo = Column(String, nullable=False)
    #: Com sinal: positivo credita, negativo debita. `hold` é negativo e
    #: `release` é positivo — o saldo disponível já desconta o que está seguro.
    amount = Column(Integer, nullable=False)
    #: O saldo do usuário DEPOIS deste lançamento.
    balance_after = Column(Integer, nullable=False)

    ref_payment_id = Column(String, ForeignKey("payments.id"), nullable=True)
    #: O job que consumiu (ou vai consumir) estes créditos.
    #:
    #: `ON DELETE SET NULL` porque as duas coisas são verdade ao mesmo tempo: o
    #: usuário pode apagar um job dele, e um registro financeiro não pode ser
    #: apagado junto. Sem isso, a chave estrangeira impediria o DELETE do job —
    #: o extrato passaria a mandar no que o usuário pode fazer com o trabalho
    #: dele. O elo não se perde: `descricao` guarda o id do job em texto.
    ref_usage_id = Column(
        String, ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )

    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    descricao = Column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(_em("tipo", TIPOS_LANCAMENTO), name="ck_credit_ledger_tipo"),
        # Lançamento de zero crédito não é lançamento, é ruído no extrato.
        CheckConstraint("amount <> 0", name="ck_credit_ledger_amount_nao_zero"),
        # O extrato da tela do usuário: por usuário, do mais recente para trás.
        Index("ix_credit_ledger_user_created", "user_id", "created_at"),
        # ── As três garantias de "cobra uma vez só" ──────────────────────────
        # Ficam no BANCO porque é o único lugar onde duas requisições
        # simultâneas não conseguem passar as duas.
        #
        # Um pagamento credita uma vez, por mais vezes que o webhook chegue:
        Index(
            "uq_credit_ledger_topup_por_pagamento",
            "ref_payment_id",
            unique=True,
            postgresql_where=text("tipo = 'topup' AND ref_payment_id IS NOT NULL"),
            sqlite_where=text("tipo = 'topup' AND ref_payment_id IS NOT NULL"),
        ),
        # Um job segura crédito uma vez só, e cobra uma vez só. Isto não é
        # teoria: este projeto já retoma job à mão depois de um reinício, e uma
        # retomada não pode cobrar de novo pelo mesmo trabalho.
        Index(
            "uq_credit_ledger_hold_por_job",
            "ref_usage_id",
            unique=True,
            postgresql_where=text("tipo = 'hold' AND ref_usage_id IS NOT NULL"),
            sqlite_where=text("tipo = 'hold' AND ref_usage_id IS NOT NULL"),
        ),
        Index(
            "uq_credit_ledger_debito_por_job",
            "ref_usage_id",
            unique=True,
            postgresql_where=text("tipo = 'debito' AND ref_usage_id IS NOT NULL"),
            sqlite_where=text("tipo = 'debito' AND ref_usage_id IS NOT NULL"),
        ),
        # E devolve uma vez só. Sem esta, uma reconciliação repetida (um retry,
        # dois caminhos terminais disparando juntos) devolveria a reserva duas
        # vezes — crédito de graça, que é o erro mais caro possível aqui.
        Index(
            "uq_credit_ledger_release_por_job",
            "ref_usage_id",
            unique=True,
            postgresql_where=text("tipo = 'release' AND ref_usage_id IS NOT NULL"),
            sqlite_where=text("tipo = 'release' AND ref_usage_id IS NOT NULL"),
        ),
    )


# ─── Monitor financeiro: o outro lado da linha ────────────────────────────────
#
# O `credit_ledger` acima registra o que o USUÁRIO pagou, em créditos. O que
# vem abaixo registra o que NÓS pagamos, em dólar e real. São os dois lados da
# mesma operação, e é o cruzamento deles que diz se um cliente dá lucro.

#: Como o processamento terminou. `failed` e `deleted` ficam separados porque a
#: causa é diferente — um é bug nosso, o outro é o usuário desistindo — e a
#: resposta a cada um também.
STATUS_USO = ("success", "failed", "deleted")


class CostConfig(Base):
    """Tarifas e câmbio. Uma linha só, `id = 1`.

    Irmã da `billing_config` e separada dela de propósito: `billing_config` é
    **o que cobramos**, esta é **o que pagamos**. Misturar as duas faria uma
    alteração de preço de venda mexer no custo histórico.

    Estes são os valores CORRENTES, usados para projeção e para eventos novos.
    O histórico não mora aqui — cada `usage_event` congela as tarifas que usou
    no `rate_snapshot`, e é por isso que mudar uma tarifa hoje não reescreve o
    lucro do mês passado.
    """

    __tablename__ = "cost_config"

    id = Column(Integer, primary_key=True, default=1)

    #: AssemblyAI cobra por minuto de áudio.
    assemblyai_usd_per_min = Column(Numeric(12, 6), nullable=False)

    #: Tarifas de LLM por MODELO, em USD por milhão de tokens:
    #: {"claude-sonnet-4-6": {"input": 3.0, "output": 15.0}, ...}
    #:
    #: Um mapa, e não duas colunas fixas, porque o modelo de análise pode
    #: mudar: com colunas por modelo, trocar de modelo exigiria migração e o
    #: evento antigo passaria a ser lido com a tarifa do modelo novo. Assim o
    #: evento grava QUAL modelo rodou e congela a tarifa dele.
    llm_rates = Column(JSONVariant, nullable=False)

    #: Custo de guardar um vídeo. Estimativa por vídeo, não medição.
    storage_usd_per_video = Column(Numeric(12, 6), nullable=False)

    fx_usd_brl = Column(Numeric(12, 4), nullable=False)
    #: A Hetzner cobra em euro — daí a segunda taxa.
    fx_eur_brl = Column(Numeric(12, 4), nullable=False)

    #: Servidor + IPv4 + domínio, por mês.
    fixed_cost_brl_month = Column(Numeric(12, 2), nullable=False)
    #: Percentual de imposto sobre a receita. PLACEHOLDER até o contador
    #: confirmar — está aqui para o número aparecer no painel, não porque
    #: alguém o apurou.
    tax_pct_on_revenue = Column(Numeric(6, 3), nullable=False)
    #: Taxa do gateway sobre o bruto (Pix).
    gateway_fee_pct = Column(Numeric(6, 3), nullable=False)

    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    updated_by_user_id = Column(String, ForeignKey("users.id"), nullable=True)

    __table_args__ = (
        CheckConstraint("id = 1", name="ck_cost_config_linha_unica"),
        CheckConstraint("fx_usd_brl > 0", name="ck_cost_config_fx_positivo"),
        CheckConstraint(
            "tax_pct_on_revenue >= 0", name="ck_cost_config_imposto_nao_negativo"
        ),
    )


class UsageEvent(Base):
    """Um registro por VÍDEO processado — não por clipe.

    O custo é por minuto de vídeo: um job que gera oito clipes custa o mesmo que
    um que gera dois. Contar por clipe inflaria o custo por um número que não
    tem relação nenhuma com a fatura.

    `credits_charged` é o que fecha o par com a receita. Quando um job falha ou
    é excluído em andamento, a reserva é devolvida e o usuário não paga
    (`COBRAR_JOB_QUE_FALHOU = False`) — mas a transcrição já foi paga por nós.
    Esses eventos ficam com custo maior que zero e `credits_charged = 0`, e é
    exatamente essa combinação que o painel soma para mostrar quanto está sendo
    perdido aí.
    """

    __tablename__ = "usage_events"

    id = Column(String, primary_key=True, default=uuid4_hex)
    user_id = Column(String, ForeignKey("users.id"), nullable=True, index=True)
    #: `SET NULL` pela mesma razão do ledger (migração 0007): registro
    #: financeiro não pode ser apagado junto com o job.
    job_id = Column(String, ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)

    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    source_video_url = Column(Text, nullable=True)
    #: Numeric, e não Float: estes minutos multiplicam direto numa tarifa, e
    #: arredondamento de ponto flutuante aqui vira centavo errado lá na frente.
    source_minutes = Column(Numeric(10, 3), nullable=True)

    transcription_provider = Column(String, nullable=True)
    transcription_minutes = Column(Numeric(10, 3), nullable=True)
    transcription_cost_usd = Column(Numeric(12, 6), nullable=False, default=0)

    #: O modelo que DE FATO rodou, não o que a configuração dizia na hora de ler.
    analysis_model = Column(String, nullable=True)
    input_tokens = Column(Integer, nullable=False, default=0)
    output_tokens = Column(Integer, nullable=False, default=0)
    analysis_cost_usd = Column(Numeric(12, 6), nullable=False, default=0)

    storage_cost_usd = Column(Numeric(12, 6), nullable=False, default=0)
    total_cost_usd = Column(Numeric(12, 6), nullable=False, default=0)
    total_cost_brl = Column(Numeric(12, 4), nullable=False, default=0)

    #: Tarifas, câmbio e modelo congelados no momento do cálculo. É o que faz
    #: uma alteração de tarifa hoje NÃO reescrever o custo do mês passado.
    rate_snapshot = Column(JSONVariant, nullable=True)

    status = Column(String, nullable=False, default="success")
    #: Créditos efetivamente cobrados do usuário. 0 = devolvido.
    credits_charged = Column(Integer, nullable=False, default=0)

    __table_args__ = (
        CheckConstraint(_em("status", STATUS_USO), name="ck_usage_events_status"),
        CheckConstraint("credits_charged >= 0", name="ck_usage_events_creditos"),
        # O painel agrega por período e por usuário. O composto atende os dois
        # (o prefixo mais à esquerda serve a busca só por usuário); o índice de
        # data sozinho atende a agregação do mês inteiro, que não filtra usuário.
        Index("ix_usage_events_user_created", "user_id", "created_at"),
        Index("ix_usage_events_created_at", "created_at"),
        # Um vídeo, um evento. Mesma disciplina do ledger: a garantia mora no
        # banco, para uma retomada ou um caminho terminal disparado duas vezes
        # não contar o custo em dobro.
        Index(
            "uq_usage_events_job",
            "job_id",
            unique=True,
            postgresql_where=text("job_id IS NOT NULL"),
            sqlite_where=text("job_id IS NOT NULL"),
        ),
    )
