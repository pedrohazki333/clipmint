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
    def locks_dir(self) -> Path:
        """PID de quem está processando cada job (ver workers/joblock.py)."""
        return Path(self.storage_dir) / "locks"

    def ensure_dirs(self) -> None:
        """Cria os diretórios de storage se não existirem."""
        for d in [self.downloads_dir, self.clips_dir, self.transcripts_dir, self.branding_dir, self.references_dir, self.locks_dir]:
            d.mkdir(parents=True, exist_ok=True)


settings = Settings()
