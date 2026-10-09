"""Settings for the Swatchfin backend.

In plain English: every setting has a safe default, so the app starts even
without a .env file. A value in .env (in the repo root) or in a real
environment variable replaces the default; the names are the same in
capitals, e.g. LOG_LEVEL=DEBUG. API keys are kept as "secret strings", which
print as ********** so they can never end up in a log.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/config.py -> the repo root, two folders up from backend/app.
REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Everything the backend can be configured with."""

    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        # "TINYFISH_API_KEY=" with nothing after it counts as "not set".
        env_ignore_empty=True,
        # .env may hold settings for other tools; ignore the ones we don't know.
        extra="ignore",
    )

    # API keys. Not needed yet: Phase 5 starts calling TinyFish.
    tinyfish_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None

    # Where the website files are, and where generated guides are saved.
    frontend_dir: Path = REPO_ROOT / "frontend"
    data_dir: Path = REPO_ROOT / "backend" / "data"

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"


@lru_cache
def get_settings() -> Settings:
    """The settings, read once and then reused."""
    return Settings()
