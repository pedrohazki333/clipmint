from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path

# Resolve .env relativo a este arquivo: backend/app/config.py → backend/../.env (raiz do projeto)
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_ENV_FILE), env_file_encoding="utf-8")

    # API Keys
    assemblyai_api_key: str = ""
    anthropic_api_key: str = ""

    # Claude
    claude_model: str = "claude-sonnet-4-6"
    claude_max_tokens: int = 8192

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

    # Acesso remoto: senha única compartilhada. Vazia = sem checagem (uso
    # puramente local). Preenchida, exige o header X-ClipMint-Token nas
    # requisições que não vêm do próprio host — ver app/main.py.
    clipmint_password: str = ""

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

    # Storage
    storage_dir: str = "./storage"

    # Database
    sqlite_url: str = "sqlite+aiosqlite:///./clipmint.db"

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
