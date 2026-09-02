from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path

# Resolve .env relativo a este arquivo: backend/app/config.py → backend/../.env (raiz do projeto)
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_ENV_FILE), env_file_encoding="utf-8")

    # ── Qual build é este ─────────────────────────────────────────────────────
    # false (default) = versão pessoal, com tudo ligado. true = build público,
    # sem o nicho Siege X e sem a aba Melhorar vídeo. Quem decide o que cada
    # valor desliga é app/features.py — não compare esta flag diretamente.
    public_build: bool = False

    # API Keys
    assemblyai_api_key: str = ""
    anthropic_api_key: str = ""

    # Claude
    claude_model: str = "claude-sonnet-4-6"
    # Teto de SAÍDA da análise.
    #
    # 8192 era baixo demais e quebrava vídeo longo: um vídeo de 3h28 (29.223
    # palavras) rende dezenas de candidatos, e o JSON com os cinco eixos da
    # rubrica mais o `trim_reason` de cada um passa folgado dos 8k — a resposta
    # vinha cortada no meio e o job falhava DEPOIS de já ter pago download,
    # transcrição e a própria análise.
    #
    # 32000 cobre com folga o pior caso medido. O Sonnet 4.6 aceita até 128k de
    # saída, mas acima de ~16k o SDK precisa de streaming para não estourar o
    # timeout de HTTP — e é por isso que a chamada da análise passou a ser
    # streaming (ver services/analyzer.py). Sem streaming, aumentar este número
    # trocaria "resposta cortada" por "timeout", que é o que já se suspeitava
    # estar acontecendo.
    claude_max_tokens: int = 32000

    # ── Visão (services/vision.py) ────────────────────────────────────────────
    # Modelo próprio, separado do da análise: ler uma cena de jogo e uma
    # expressão de rosto é outro trabalho, e o Opus 5 tem visão de alta
    # resolução. O custo por vídeo é de centavos, então não vale economizar aqui.
    claude_vision_model: str = "claude-opus-5"
    claude_vision_max_tokens: int = 2000
    # Desligado, o pipeline volta a decidir os cortes só por texto e áudio.
    vision_enabled: bool = True
    # Quanto olhar antes e depois do corte ao refinar os limites. 20s foi
    # medido contra o caso real: o buraco do evento que motivou isto tem 21,4s.
    vision_window: float = 20.0
    # Teto de quadros por janela. Com keyframe a cada ~6s, 10 cobrem um minuto.
    vision_max_frames: int = 10
    # Teto de janelas por vídeo — uma live de 6h não pode virar 80 chamadas.
    vision_max_windows: int = 20
    # Quantos instantes a passada 1 do compilado aponta para a visão olhar. É
    # uma origem de janela independente dos buracos de áudio: medido nos seis
    # trechos do compilado real do alanzoka, dois eram fala contínua e nunca
    # viravam janela pelo caminho antigo (services/candidates.py).
    compilation_candidates: int = 18

    # ── Perícia de clipe pronto (services/clip_forensics.py) ──────────────────
    # Aqui o objeto de estudo é um clipe de 30-60s, não uma janela dentro de um
    # vídeo de uma hora: dá para olhar quadro a quadro e ainda sobra contexto
    # para o modelo cruzar imagem, som e fala numa resposta só.
    claude_forensics_model: str = "claude-opus-5"
    # 16000 e não 8000: a perícia devolve treze campos de prosa mais a lista de
    # batidas, em português (que gasta mais token que inglês). No primeiro clipe
    # real a resposta bateu no teto de 8000 e voltou JSON pela metade. Este é o
    # padrão recomendado para chamada sem streaming — acima dele o SDK pede
    # streaming para não estourar o timeout de HTTP.
    claude_forensics_max_tokens: int = 16000
    # Quadros enviados à visão. 14 num clipe de 40s dá um a cada ~3s depois do
    # gancho, o suficiente para ver troca de plano, legenda e overlay.
    forensics_frame_count: int = 14
    # Os primeiros segundos decidem o clipe, então são amostrados denso e fora
    # da grade uniforme (ver frame_times em clip_forensics.py).
    forensics_hook_seconds: float = 3.0
    # Sensibilidade do detector de corte de cena do FFmpeg (0-1). 0.35 pega
    # corte duro sem disparar em movimento rápido de câmera.
    forensics_scene_threshold: float = 0.35

    # AssemblyAI
    # O antigo `best` (= universal-2) se perde em grito distorcido e fala
    # regional: num trecho de teste ele alucinou "TREADOR!" e travou repetindo
    # "eu tô trabalhando", com 46% das palavras abaixo de 0.7 de confiança.
    #
    # O universal-3-5-pro é o mais preciso (9% no mesmo trecho), mas no vídeo
    # inteiro ele travou em loop duas vezes — 128x e 121x "não" — e um dos
    # loops comeu a fala que estava ali. O universal-3-pro leu o mesmo trecho
    # sem nenhum loop e com 1/3 das palavras sem duração própria, então é ele
    # o padrão: acerto médio um pouco menor vale menos que não produzir lixo.
    # Valores aceitos: universal-2, universal-3-pro, universal-3-5-pro.
    assemblyai_speech_model: str = "universal-3-pro"
    # Vazio = deixa a AssemblyAI detectar o idioma.
    assemblyai_language: str = "pt"

    # ── Escolha do provedor de transcrição ────────────────────────────────────
    # "assemblyai" (padrão) | "deepgram". Trocar isto é decisão a tomar com o
    # relatório do modo de comparação na mão:
    #   cd backend && .venv/bin/python -m app.scripts.compare_transcribers <job_id>
    transcription_provider: str = "assemblyai"

    # ── Deepgram (services/transcription/deepgram.py) ─────────────────────────
    deepgram_api_key: str = ""
    # nova-3 atende português direto (pt, pt-BR, pt-PT) no modelo monolíngue —
    # não precisa do multilíngue, que é mais caro.
    deepgram_model: str = "nova-3"
    # Vazio = pede detecção automática de idioma.
    deepgram_language: str = "pt"
    # Teto de leitura da resposta. Transcrever uma hora leva minutos; o teto é
    # para a chamada pendurada, não para a lenta.
    deepgram_timeout: float = 1800.0

    # ── Tarifas para a estimativa de custo ────────────────────────────────────
    # Preços de tabela pay-as-you-go consultados em 25/08/2026, em USD por hora
    # de áudio. Ficam em configuração porque preço de fornecedor muda e um
    # número cravado no código vira mentira silenciosa no relatório.
    #
    #   AssemblyAI universal-3-pro / universal-3-5-pro : US$ 0,21/h
    #   AssemblyAI universal-2                         : US$ 0,15/h
    #   Deepgram nova-3 monolíngue  : US$ 0,0043/min = US$ 0,258/h
    #   Deepgram nova-3 multilíngue : US$ 0,0052/min = US$ 0,312/h
    #
    # Vale notar para a decisão: no modelo que o projeto usa, o Deepgram é ~23%
    # MAIS CARO que o AssemblyAI. A troca só se justifica por qualidade.
    assemblyai_cost_per_hour: float = 0.21
    deepgram_cost_per_hour: float = 0.258

    # Acesso remoto: senha única compartilhada. Vazia = sem checagem (uso
    # puramente local). Preenchida, exige o header X-ClipMint-Token nas
    # requisições que não vêm do próprio host — ver app/main.py.
    clipmint_password: str = ""

    # ── Contas e sessão ───────────────────────────────────────────────────────
    # Quanto tempo um login dura. 30 dias é o mesmo da senha única que existia
    # antes — não faz sentido o produto público ser mais impaciente que a
    # ferramenta pessoal.
    session_days: int = 30
    # E-mail do usuário-dono. Na versão pessoal é a conta única, dona de todos
    # os jobs; no build público é quem administra a instalação.
    owner_email: str = "dono@clipmint.local"
    # Tamanho mínimo de senha no cadastro. 12 é a recomendação atual da OWASP
    # para senha sem exigência de composição — regra de "1 maiúscula e 1
    # símbolo" empurra as pessoas para senhas curtas e previsíveis.
    min_password_length: int = 12
    # Cadastro aberto. Desligado, só quem já tem conta entra — é o modo para
    # abrir o produto para um grupo fechado antes de abrir para todos.
    registration_open: bool = True

    # ── E-mail transacional ───────────────────────────────────────────────────
    # Só a recuperação de senha usa isto. SMTP, e não a API de um provedor, de
    # propósito: Resend, SendGrid e SES falam SMTP, então trocar de provedor é
    # trocar quatro linhas do .env em vez de reescrever o serviço.
    #
    # `smtp_host` VAZIO desliga a recuperação de senha inteira — a rota passa a
    # responder 503 dizendo que o servidor não manda e-mail, em vez de aceitar
    # o pedido e sumir com ele. Falhar visível é melhor que falhar calado
    # quando o assunto é a única porta de volta para a conta.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    # Remetente. Precisa ser de um domínio com SPF/DKIM configurados, senão o
    # e-mail chega no spam e a recuperação é pior que inexistente: o usuário
    # acha que pediu e ficou sem resposta.
    smtp_from: str = ""
    # Quanto tempo o link de redefinição vale. Curto de propósito: é um token
    # que troca a senha de uma conta com créditos comprados dentro.
    password_reset_ttl_minutes: int = 60

    # Porta em que o uvicorn sobe. Quem lê de verdade são o Makefile e o
    # next.config (para o proxy); aqui existe para o pydantic não recusar a
    # chave do .env, e para o valor ficar documentado junto dos outros.
    backend_port: int = 8001

    # ── Pós-processamento do vídeo bruto ──────────────────────────────────────
    # Altura alvo do lado menor: 1080 dá 1080x1920 no vertical e 1920x1080 no
    # horizontal, sem precisar de dois ajustes.
    enhance_target_height: int = 1080
    # 24 = mesmo fps que o Veo entrega, ou seja, a interpolação é dispensada.
    # Medido em 13/08/2026 num clipe de 8s em 1080p: interpolar para 48fps leva
    # 138s contra 3,6s do reencode sozinho — 38x o custo. E como o bitrate alvo
    # é fixo, dobrar os quadros dá metade dos bits para cada um: em 24fps cada
    # quadro fica mais nítido. Só suba para 48 se o movimento rápido justificar.
    enhance_target_fps: int = 24
    enhance_video_bitrate: str = "12M"  # faixa pedida: 10–15Mbps
    # Ampliar com lanczos deixa a imagem macia; um unsharp leve devolve a
    # impressão de foco. Mesmo valor usado na facecam (ver facecam_sharpen).
    enhance_sharpen: float = 0.8
    # Cada etapa do FFmpeg tem teto próprio: a interpolação com compensação de
    # movimento é de longe a mais cara e trava o job se algo der errado.
    enhance_step_timeout: int = 1800

    # ── Tetos de tempo do FFmpeg (utils/ffmpeg.py) ────────────────────────────
    # Sem teto, um FFmpeg travado deixa o job em "clipping" para sempre: o
    # DELETE não interrompe o pipeline, o retry responde 409 enquanto o lock
    # estiver vivo e o reconcile do startup poupa job com lock — só reiniciar o
    # servidor resolvia. A aba Melhorar vídeo já fazia isso certo desde sempre
    # (enhance_step_timeout); aqui é a mesma ideia para o pipeline principal.
    #
    # 1800s é folga larga: o render mais caro medido (clip de 90s, modo
    # streamer com facecam por frame) fica na casa dos minutos. O teto existe
    # para o caso patológico, não para apertar o caso normal.
    ffmpeg_timeout: int = 1800
    # O ffprobe só lê cabeçalho — se demora, o arquivo ou o disco estão ruins.
    ffprobe_timeout: int = 120

    # ── Travas de custo e de abuso ────────────────────────────────────────────
    # Estas existem por um motivo só: transcrição e análise são pagas por
    # minuto de áudio, e um bug ou um usuário mal-intencionado transformam isso
    # numa fatura. Todos os tetos são por USUÁRIO e por janela de tempo.
    #
    # Janela deslizante, não "por dia": com dia-calendário, quem estoura a cota
    # às 23h volta a ter tudo às 00h, e o pico de abuso cabe em duas horas.
    quota_window_hours: int = 24
    # Vídeos e minutos por janela. 0 = aquele teto está desligado, e é o padrão
    # da VERSÃO PESSOAL: lá é uma pessoa, na própria conta de API, processando
    # uma live de 6h de propósito — uma cota ali atrapalharia o trabalho em vez
    # de proteger alguém. Preencher aqui liga o teto nas duas versões.
    quota_max_videos: int = 0
    quota_max_minutes: int = 0
    # Os tetos do build público, usados quando os de cima estão em 0. Lá quem
    # paga a conta não é quem manda o link, e é isso que muda tudo.
    # Os dois valem ao mesmo tempo e o que estourar primeiro barra: 10 vídeos de
    # 2h custam 20x mais que 10 de 6min, então contar só a quantidade não
    # protegeria a conta.
    public_quota_max_videos: int = 10
    public_quota_max_minutes: int = 300

    # Teto de duração de UM vídeo. Medido: a transcrição inteira entra no
    # prompt sem truncagem, e 12h dão ~252k tokens — acima dos 200k de contexto
    # do Sonnet, ou seja, o job falharia depois de já ter pago o download e a
    # transcrição. 120min ≈ 43k tokens, com folga larga.
    # A conferência é feita ANTES do download, com uma chamada de metadados.
    # 0 = sem teto (o padrão da versão pessoal, onde quem paga escolhe).
    max_source_minutes: int = 0
    # Teto do build público, aplicado quando max_source_minutes é 0.
    public_max_source_minutes: int = 120
    # Tempo máximo da consulta de metadados. Ela roda na frente do usuário, na
    # resposta do POST /jobs, então não pode pendurar a tela.
    probe_timeout: float = 30.0

    # Jobs processando ao mesmo tempo, no servidor inteiro. Cada um roda FFmpeg
    # e MediaPipe; sem teto, dez jobs simultâneos derrubam a máquina e todos
    # ficam lentos em vez de uns poucos ficarem rápidos. Os que passarem do
    # limite esperam a vez em "queued".
    max_concurrent_jobs: int = 2

    # ── Retenção (TTL) ────────────────────────────────────────────────────────
    # Depois de quantos dias o ARQUIVO do clipe é apagado. A linha no banco
    # fica: nota, eixos da rubrica e desempenho real alimentam o few-shot, e
    # apagá-los destruiria o aprendizado para economizar bytes que não são deles.
    clip_ttl_days: int = 14
    # O vídeo de ORIGEM sai bem antes: é o que ocupa GB de verdade e só serve
    # para re-renderizar. Depois disso, "Retomar" ainda funciona — só volta a
    # baixar.
    #
    # Um dia, não três. Um vídeo longo ocupa alguns GB e o disco é o recurso que
    # PARA o sistema quando acaba, não o que o deixa lento. Um dia cobre a
    # janela real em que alguém baixa os clipes, vê um problema e pede
    # correção; passado isso, re-baixar custa tempo e nada mais.
    download_ttl_days: int = 1
    # 0 em qualquer um dos dois desliga aquela limpeza.
    # De quanto em quanto tempo a faxina roda dentro do servidor. 0 desliga —
    # é o que se faz quando ela vira um cron (ver docs/DEPLOY.md).
    cleanup_interval_hours: int = 6

    # ── yt-dlp ────────────────────────────────────────────────────────────────
    # Num servidor de datacenter o YouTube responde "Sign in to confirm you're
    # not a bot" para QUALQUER vídeo — o bloqueio é por faixa de IP. Numa
    # máquina doméstica nada disso é necessário e as duas ficam vazias.
    #
    # Cookies exportados de um navegador logado. Use conta descartável: o
    # YouTube suspende contas que associa a tráfego de datacenter.
    ytdlp_cookies_file: str = ""
    # Proxy (residencial, se for para baixar vídeo — datacenter é bloqueado
    # igual). Cobrado por GB, então pesa: um vídeo de 2h passa de 1 GB.
    ytdlp_proxy: str = ""

    # Storage
    storage_dir: str = "./storage"

    # ── Banco ─────────────────────────────────────────────────────────────────
    # Um só endereço para os dois bancos que o projeto usa:
    #
    #   sqlite+aiosqlite:///./clipmint.db          — versão pessoal e testes
    #   postgresql+psycopg://user:senha@host/base  — build público
    #
    # Manter o SQLite não é preguiça: a versão pessoal roda no WSL2 e é usada
    # todo dia; exigir um Postgres no laptop para clipar um vídeo seria custo
    # sem contrapartida. O build público, esse, RECUSA subir em SQLite (ver
    # app/main.py) — servidor multiusuário com um arquivo só dá corrupção sob
    # escrita concorrente.
    database_url: str = "sqlite+aiosqlite:///./clipmint.db"

    # Nome antigo da mesma coisa. Continua lido para um .env existente não
    # parar de funcionar, e VENCE quando os dois estão preenchidos: um .env que
    # já funcionava não pode trocar de banco porque uma variável nova apareceu.
    # A consequência prática, na hora de migrar para Postgres: definir
    # DATABASE_URL não basta, é preciso APAGAR o SQLITE_URL do .env. Ver a
    # propriedade `db_url` abaixo e test_sqlite_url_antigo_continua_valendo.
    sqlite_url: str = ""

    # Banco do build PÚBLICO quando ele roda NESTA máquina, ao lado da versão
    # pessoal (`make serve-public`). Quem consome esta variável é o Makefile,
    # que a passa como DATABASE_URL só para o processo público — o app nunca a
    # lê. Ela está declarada aqui porque o Settings recusa chave desconhecida no
    # .env, e sem o campo o backend nem chega a subir. No servidor, onde só
    # existe o build público, ela fica vazia e vale a DATABASE_URL de cima.
    public_database_url: str = ""

    # ── Mercado Pago ──────────────────────────────────────────────────────────
    # Credenciais do gateway. NUNCA no código: as duas saem do .env, e sem elas
    # o build público recusa criar cobrança (ver services/mercadopago.py).
    #
    # O access token começa com APP_USR no ambiente de produção e com TEST no
    # sandbox — é a mesma variável, e é ela que decide contra qual ambiente as
    # chamadas vão. Não existe flag separada de sandbox de propósito: uma flag
    # que discordasse do token seria uma forma nova de cobrar de verdade
    # achando que era teste.
    mercadopago_access_token: str = ""
    # Segredo da assinatura do webhook, gerado no painel do Mercado Pago em
    # "Suas integrações > Webhooks > Configurar notificação". Sem ele o endpoint
    # de webhook recusa TUDO — é a única coisa que separa uma notificação do
    # gateway de alguém postando "pagamento aprovado" na sua API.
    mercadopago_webhook_secret: str = ""
    mercadopago_api_base: str = "https://api.mercadopago.com"
    mercadopago_timeout: float = 20.0

    # Endereço público desta instalação, ex.: https://clipmint.com.br
    #
    # É para onde o Mercado Pago devolve a pessoa depois de ela autorizar a
    # assinatura no site dele (`back_url`). Sem isto configurado, assinar é
    # RECUSADO com mensagem clara — mandar alguém para o gateway sem caminho de
    # volta deixaria a pessoa presa lá com o cartão já autorizado.
    public_base_url: str = ""

    # Minutos até a cobrança Pix expirar. Curto o bastante para o QR não ficar
    # vivo eternamente, longo o bastante para quem foi buscar o celular.
    pix_expiration_minutes: int = 30

    # Tamanho do pool de conexões. Só vale no Postgres — o SQLite não usa pool.
    # 10 cobre com folga a concorrência de jobs que o servidor vai permitir.
    db_pool_size: int = 10
    db_max_overflow: int = 5

    # Pipeline
    virality_threshold: float = 7.0
    max_clip_duration: int = 90
    min_clip_duration: int = 15
    # Faixa preferida de duração (sweet spot de alcance/viralização). Os limites
    # hard continuam em min/max_clip_duration; isto só orienta a escolha do corte.
    preferred_clip_min: int = 25
    preferred_clip_max: int = 40
    # Face tracking: quando desligado, o crop 9:16 fica estático no centro do
    # frame e o MediaPipe nem chega a rodar (render bem mais rápido).
    face_tracking_enabled: bool = False

    # ── Modo streamer (facecam empilhada sobre o gameplay) ────────────────────
    # Full HD vertical: 1080x1920 — o padrão das plataformas de vertical, e o
    # arquivo sai numa fração do tempo e do tamanho do 4K. Subir para 2160 só
    # compensa com fonte 1440p+, e ainda assim a facecam continua sendo upscale
    # (a caixa da cam é pequena na fonte).
    streamer_output_width: int = 1080
    # Fração da altura do canvas ocupada por cada painel (o gameplay leva o resto)
    streamer_facecam_frac: float = 0.35
    streamer_bar_frac: float = 0.029
    # Zoom da fatia de gameplay: 1.0 = altura cheia da fonte. Acima disso a
    # fatia é menor (imagem mais fechada) e sobra espaço para ela desviar da
    # facecam sem chegar perto da moldura.
    streamer_game_zoom: float = 1.06
    # ── Banner de título do modo streamer ─────────────────────────────────────
    # Um título parado nos primeiros segundos: a legenda passa palavra a palavra
    # e muitas vezes não chega a ser lida, então ele é a única coisa na tela que
    # diz do que se trata o clipe antes de a fala chegar lá.
    # 0 desliga o banner sem mexer no resto do layout.
    streamer_banner_hold: float = 4.0
    # Duração da saída (o banner encolhe para dentro da faixa). Medida no
    # exemplo aprovado: ~0,16s. Abaixo de ~0,1s vira um corte seco.
    streamer_banner_exit: float = 0.18
    # Quadros por segundo da animação de saída. 30 já é fluido para um
    # movimento de 0,18s (5 a 6 quadros) e mantém a sequência pequena.
    streamer_banner_exit_fps: int = 30

    # A facecam da fonte é pequena (numa live 1080p pode ser 486x257) e sobe
    # ~1.4x a 2.2x para preencher o painel. O lanczos amplia sem inventar
    # detalhe, e o resultado sai macio; um unsharp leve depois da ampliação
    # devolve a impressão de foco. 0 desliga; acima de ~1.2 começa a marcar
    # halo em volta dos óculos e do contorno do cabelo.
    facecam_sharpen: float = 0.8

    # ── Marca d'água do clipe (storage/branding/<nicho>/clip_watermark.png) ───
    # Medidos por template matching sobre o clipe de referência enviado em
    # 15/08/2026 (casamento de 0.977): a arte ocupava 200px de largura num
    # canvas de 1080 e o centro dela ficava a 79.4% da altura, centralizada na
    # horizontal. Frações, e não pixels, para o mesmo enquadramento valer se a
    # saída deixar de ser 1080x1920.
    clip_watermark_width: float = 0.185     # largura, em frações da largura
    clip_watermark_center_y: float = 0.794  # centro vertical, em frações da altura
    clip_watermark_opacity: float = 0.70    # 1.0 = opaca; multiplica o alfa da arte

    @property
    def db_url(self) -> str:
        """O endereço do banco, respeitando o nome antigo da variável."""
        return self.sqlite_url or self.database_url

    @property
    def is_postgres(self) -> bool:
        return self.db_url.startswith("postgresql")

    @property
    def downloads_dir(self) -> Path:
        return Path(self.storage_dir) / "downloads"

    @property
    def clips_dir(self) -> Path:
        return Path(self.storage_dir) / "clips"

    @property
    def transcripts_dir(self) -> Path:
        return Path(self.storage_dir) / "transcripts"

    @property
    def branding_dir(self) -> Path:
        return Path(self.storage_dir) / "branding"

    @property
    def references_dir(self) -> Path:
        return Path(self.storage_dir) / "references"

    @property
    def video_enhance_dir(self) -> Path:
        """Vídeos enviados e tratados da aba Melhorar vídeo."""
        return Path(self.storage_dir) / "video_enhance"

    @property
    def locks_dir(self) -> Path:
        """PID de quem está processando cada job (ver workers/joblock.py)."""
        return Path(self.storage_dir) / "locks"

    def ensure_dirs(self) -> None:
        """Cria os diretórios de storage se não existirem."""
        for d in [self.downloads_dir, self.clips_dir, self.transcripts_dir, self.branding_dir, self.references_dir, self.video_enhance_dir, self.locks_dir]:
            d.mkdir(parents=True, exist_ok=True)


settings = Settings()
