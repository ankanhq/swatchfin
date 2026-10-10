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

from pydantic import Field, SecretStr
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

    # API keys. Without the TinyFish key, guides stop with a message. Without the Anthropic key,
    # guides have no tone of voice or key messages, and their warnings say so.
    tinyfish_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    # The Claude model that reads a brand's text for its tone of voice (see llm.py), e.g. claude-opus-5-5.
    anthropic_model: str = Field("claude-sonnet-5-5", pattern=r"^[a-z0-9][a-z0-9.\-]{1,63}$")

    # Where the website files are, and where generated guides are saved.
    frontend_dir: Path = REPO_ROOT / "frontend"
    data_dir: Path = REPO_ROOT / "backend" / "data"

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # Jobs (see jobs.py).
    # How many guides are made at the same time. The rest wait their turn.
    max_running_jobs: int = Field(2, ge=1, le=20)
    # How many guides may wait for their turn before new ones are refused as "busy".
    max_waiting_jobs: int = Field(20, ge=0, le=500)
    # A guide that takes longer than this stops with a message. The guide
    # page waits 3 minutes, so this must stay below 180.
    job_timeout_seconds: float = Field(150, gt=0, lt=180)
    # Finished guides older than this are deleted when the server starts.
    guide_retention_days: int = Field(30, ge=1)

    # TinyFish Browser measures colours and fonts and costs wallet credit ($0.002 a minute, billed
    # by the second: about $0.001 a guide). USE_BROWSER=false leaves it out, e.g. while developing.
    use_browser: bool = True

    # Rate limits, per visitor (IP address). See ratelimit.py.
    new_guides_per_hour: int = Field(20, ge=1)
    api_requests_per_minute: int = Field(300, ge=1)


@lru_cache
def get_settings() -> Settings:
    """The settings, read once and then reused."""
    return Settings()
