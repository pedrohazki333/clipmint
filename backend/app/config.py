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

    @property
    def downloads_dir(self) -> Path:
        return Path(self.storage_dir) / "downloads"

    @property
    def clips_dir(self) -> Path:
        return Path(self.storage_dir) / "clips"

    @property
    def transcripts_dir(self) -> Path:
        return Path(self.storage_dir) / "transcripts"

    def ensure_dirs(self) -> None:
        """Cria os diretórios de storage se não existirem."""
        for d in [self.downloads_dir, self.clips_dir, self.transcripts_dir]:
            d.mkdir(parents=True, exist_ok=True)


settings = Settings()
