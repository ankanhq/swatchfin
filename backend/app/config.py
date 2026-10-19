"""Settings for the Swatchfin backend.

In plain English: every setting has a safe default, so the app starts even
without a .env file. A value in .env (in the repo root) or in a real
environment variable replaces the default; the names are the same in
capitals, e.g. LOG_LEVEL=DEBUG. API keys are kept as "secret strings", which
print as ********** so they can never end up in a log.
"""

import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/config.py -> the repo root, two folders up from backend/app.
REPO_ROOT = Path(__file__).resolve().parents[2]

# What a pasted API key can pick up that is never part of a key: spaces, tabs and line breaks (also
# the invisible ones: no-break, zero-width and byte-order marks) and quote marks ("…", '…', “…”, `…`).
KEY_NOISE = re.compile(r"[\s\u200b-\u200d\u2060\ufeff\"'`\u2018\u2019\u201c\u201d]")


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

    # API keys. Without the TinyFish key, guides stop with a message. The tone of voice and key
    # messages need at least one of the Anthropic, Gemini and Groq keys; without any, guides have
    # none, and their warnings say so.
    tinyfish_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None
    groq_api_key: SecretStr | None = None

    # The models that read a brand's text for its tone of voice (see llm.py).
    # Claude, e.g. claude-opus-5-5.
    anthropic_model: str = Field("claude-sonnet-5-5", pattern=r"^[a-z0-9][a-z0-9.\-]{1,63}$")
    # A Gemini model, e.g. gemini-3.6-flash.
    gemini_model: str = Field("gemini-3.8-flash", pattern=r"^[a-z0-9][a-z0-9.\-]{1,63}$")
    # A Groq model with strict structured outputs and low reasoning effort, e.g. openai/gpt-oss-20b.
    groq_model: str = Field("openai/gpt-oss-120b", pattern=r"^[a-z0-9][a-z0-9./\-]{1,63}$")
    # The order they are asked in: when one gives no usable answer, the next one is asked. Claude,
    # then Gemini, then Groq is the order the benchmark recommends (README, "Tone of voice"): Gemini
    # quoted as exactly as Claude but is sometimes busy; Groq always answered but quoted less exactly.
    # Leave one out to never use it. A model without a key is left out anyway.
    llm_order: str = Field(
        "anthropic,gemini,groq", pattern=r"^ *(anthropic|groq|gemini) *(, *(anthropic|groq|gemini) *){0,2}$"
    )

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

    # MOCK: serve the sample guides "mock" and "mock-partial" (Northwind Roasters, a fictional brand),
    # for building the guide page, Lighthouse runs and tests. Never turned on in production, where
    # no guide marked MOCK is ever served.
    sample_guides: bool = False

    # TinyFish Browser measures colours and fonts and costs wallet credit ($0.002 a minute, billed
    # by the second: about $0.001 a guide). USE_BROWSER=false leaves it out, e.g. while developing.
    use_browser: bool = True

    # Limits that protect the TinyFish allowance and the language model credit. See ratelimit.py.
    # New guides a day for everyone together (UTC days), DAILY_GUIDE_LIMIT. A guide reads 7 or 8 pages
    # with Fetch on average and at most 11, so the live site's 90 stay within Fetch's free 1,000 a day.
    daily_guide_limit: int = Field(50, ge=1)
    # New guides per visitor (IP address) in any 24 hours, VISITOR_DAILY_LIMIT. Its old name,
    # NEW_GUIDES_PER_VISITOR_PER_DAY, still works; when both are set, the new one counts.
    visitor_daily_limit: int = Field(
        5, ge=1, validation_alias=AliasChoices("visitor_daily_limit", "new_guides_per_visitor_per_day")
    )
    # API requests a minute per visitor.
    api_requests_per_minute: int = Field(300, ge=1)
    # A complete guide for the same search or website made within this many hours is reused
    # instead of made again (see reuse.py). 0 turns reuse off.
    reuse_hours: float = Field(24, ge=0, le=24 * 30)
    # How many entries the proxies in front of the app add to the X-Forwarded-For header (see ratelimit.Visitors).
    # 0 on your computer, where visitors connect directly. Render: see docs/deploy-render.md.
    proxy_hops: int = Field(0, ge=0, le=5)

    @field_validator("tinyfish_api_key", "anthropic_api_key", "gemini_api_key", "groq_api_key", mode="before")
    @classmethod
    def _clean_key(cls, value: Any) -> Any:
        """A key without the spaces, line breaks and quotes a paste can add. Nothing left counts as not set.

        In plain English: a key copied into Render's settings with a space or a
        line break at its end, or in quotes, is refused by the API it is for.
        Keys never contain these characters, so they are all taken out.
        """
        if isinstance(value, SecretStr):
            value = value.get_secret_value()
        if isinstance(value, str):
            return KEY_NOISE.sub("", value) or None
        return value

    @property
    def llm_apis(self) -> list[str]:
        """LLM_ORDER as a list, each name once: "anthropic, groq" -> ["anthropic", "groq"]."""
        return list(dict.fromkeys(name.strip() for name in self.llm_order.split(",")))


@lru_cache
def get_settings() -> Settings:
    """The settings, read once and then reused."""
    return Settings()
