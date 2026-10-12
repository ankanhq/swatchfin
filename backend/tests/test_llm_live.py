"""The language models against the real APIs: Claude, Groq and Gemini.

One short question to each model set in .env, well under $0.01 in all
(Groq's and Google's free tiers cost nothing), so a normal `pytest` run
leaves them out. Run them on purpose with:

    pytest backend -m live

Each one is skipped when .env has no key for it.
"""

from collections.abc import Callable

import httpx2
import pytest
from pydantic import BaseModel, ConfigDict, SecretStr

from app.config import Settings
from app.llm import AnthropicLLM, GeminiLLM, GroqLLM, ProviderLLM

pytestmark = [pytest.mark.anyio, pytest.mark.live]


class Quote(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quote: str


async def ask_for_a_quote(llm: ProviderLLM) -> None:
    """The same small task for every model: copy one sentence exactly."""
    try:
        answer = await llm.ask(
            system="Copy the second sentence of the text exactly, as `quote`.",
            prompt="Tea worth slowing down for. Picked by hand in Darjeeling. Shipped on Mondays.",
            answer=Quote,
            max_tokens=1_000,
            time_limit=60,
        )
    finally:
        await llm.close()
    assert answer.data.quote.strip() == "Picked by hand in Darjeeling."
    assert (answer.usage.api, answer.usage.model) == (llm.api, llm.model)
    assert answer.usage.input_tokens > 0 and answer.usage.output_tokens > 0
    assert answer.usage.cost_usd is not None and answer.usage.cost_usd < 0.01


async def test_claude_answers_in_the_shape_asked_for() -> None:
    settings = Settings()
    if settings.anthropic_api_key is None:
        pytest.skip("no ANTHROPIC_API_KEY in .env")
    await ask_for_a_quote(AnthropicLLM(settings.anthropic_api_key, settings.anthropic_model))


@pytest.mark.parametrize(
    ("key_name", "make"),
    [
        ("groq_api_key", lambda key, settings, http: GroqLLM(key, settings.groq_model, http)),
        ("gemini_api_key", lambda key, settings, http: GeminiLLM(key, settings.gemini_model, http)),
    ],
    ids=["groq", "gemini"],
)
async def test_groq_and_gemini_answer_in_the_shape_asked_for(
    key_name: str, make: Callable[[SecretStr, Settings, httpx2.AsyncClient], ProviderLLM]
) -> None:
    settings = Settings()
    key = getattr(settings, key_name)
    if key is None:
        pytest.skip(f"no {key_name.upper()} in .env")
    async with httpx2.AsyncClient() as http:
        await ask_for_a_quote(make(key, settings, http))
