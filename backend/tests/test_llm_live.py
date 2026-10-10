"""The Anthropic wrapper against the real Claude API.

One short question to the ANTHROPIC_MODEL in .env, well under $0.01, so a
normal `pytest` run leaves it out. Run it on purpose with:

    pytest backend -m live

It is skipped when .env has no ANTHROPIC_API_KEY.
"""

import pytest
from pydantic import BaseModel, ConfigDict

from app.config import Settings
from app.llm import AnthropicLLM

pytestmark = [pytest.mark.anyio, pytest.mark.live]


class Quote(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quote: str


async def test_claude_answers_in_the_shape_asked_for() -> None:
    settings = Settings()
    if settings.anthropic_api_key is None:
        pytest.skip("no ANTHROPIC_API_KEY in .env")
    llm = AnthropicLLM(settings.anthropic_api_key, settings.anthropic_model)
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
    assert answer.usage.model == settings.anthropic_model
    assert answer.usage.input_tokens > 0 and answer.usage.output_tokens > 0
    assert answer.usage.cost_usd is not None and answer.usage.cost_usd < 0.01
