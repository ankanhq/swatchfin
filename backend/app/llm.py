"""The language model behind step 6: it reads a brand's text and drafts its tone of voice.

In plain English: the pipeline only knows the `LLM` shape below: "send
instructions and text, get back data of this shape". `AnthropicLLM` is the
real one, using Anthropic's Claude API through its official SDK. The tests
use a fake one, so they never spend money. Another provider could be added
the same way.

The shape of the answer is a Pydantic class. Claude's structured outputs
make the reply JSON in that shape, and Pydantic checks it again here.

Each call reports its token counts and what it cost in US dollars, worked
out from Anthropic's published prices. The pipeline logs that once per
guide; the guide itself doesn't mention cost.

The model is the ANTHROPIC_MODEL setting (claude-sonnet-5-5 by default).
It thinks only as much as it needs at low effort: copying quotes and naming
a voice is reading work, not hard reasoning, and low effort keeps answers
quick and cheap. A request Claude refuses is not sent on to another model:
step 6 is then skipped, with a warning.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar

import anthropic
from pydantic import BaseModel, SecretStr, ValidationError

log = logging.getLogger("swatchfin.llm")

AnswerT = TypeVar("AnswerT", bound=BaseModel)

# US dollars per million tokens, (input, output), from https://platform.claude.com/docs/en/about-claude/pricing
# (October 2026). Thinking is billed as output. A model missing here still works; its cost is logged as unknown.
PRICES: dict[str, tuple[float, float]] = {
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
    "claude-haiku-5-5": (0.10, 0.50),
}
EFFORT = "low"


@dataclass(frozen=True)
class LLMUsage:
    """What one call used."""

    model: str
    input_tokens: int
    output_tokens: int
    seconds: float

    @property
    def cost_usd(self) -> float | None:
        """What the call cost in US dollars, or None for a model whose price isn't in PRICES."""
        price = PRICES.get(self.model)
        if price is None:
            return None
        return (self.input_tokens * price[0] + self.output_tokens * price[1]) / 1_000_000

    def describe(self) -> str:
        """For the log: "claude-sonnet-5-5, 9,812 input + 1,904 output tokens, $0.0387, 21.4 s"."""
        cost = "cost unknown" if self.cost_usd is None else f"${self.cost_usd:.4f}"
        return (
            f"{self.model}, {self.input_tokens:,} input + {self.output_tokens:,} output tokens, "
            f"{cost}, {self.seconds:.1f} s"
        )


@dataclass(frozen=True)
class LLMAnswer(Generic[AnswerT]):
    data: AnswerT
    usage: LLMUsage


class LLMError(Exception):
    """No usable answer.

    `reason` finishes the sentence "Tone of voice and key messaging weren’t
    analysed: …". `retry` is True when trying again later may work. `usage`
    is set when the model did answer but the answer couldn't be used: it is
    billed all the same.
    """

    def __init__(self, reason: str, *, retry: bool = True, usage: LLMUsage | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.retry = retry
        self.usage = usage


class LLM(Protocol):
    """What the pipeline needs from a language model."""

    model: str

    async def ask(
        self, *, system: str, prompt: str, answer: type[AnswerT], max_tokens: int, time_limit: float
    ) -> LLMAnswer[AnswerT]:
        """Sends the instructions (`system`) and the text (`prompt`), and returns an answer of type `answer`.
        Raises LLMError when there is no usable answer within `time_limit` seconds."""
        ...


class AnthropicLLM:
    """Claude, through Anthropic's official Python SDK."""

    def __init__(
        self,
        api_key: SecretStr,
        model: str,
        *,
        http_client: anthropic.DefaultAsyncHttpxClient | None = None,
        max_retries: int = 1,
    ) -> None:
        self.model = model
        # One retry for a busy moment (429, 529, 5xx); ask()'s time limit still holds.
        # The tests pass an http_client with a fake Anthropic behind it.
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key.get_secret_value(), max_retries=max_retries, http_client=http_client
        )

    async def close(self) -> None:
        await self._client.close()

    async def ask(
        self, *, system: str, prompt: str, answer: type[AnswerT], max_tokens: int, time_limit: float
    ) -> LLMAnswer[AnswerT]:
        started = time.monotonic()
        try:
            # The whole call, retry included, ends within the time limit.
            async with asyncio.timeout(time_limit):
                message = await self._client.messages.create(
                    model=self.model,
                    max_tokens=max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": prompt}],
                    thinking={"type": "adaptive"},
                    output_config={
                        "effort": EFFORT,
                        "format": {"type": "json_schema", "schema": anthropic.transform_schema(answer)},
                    },
                    timeout=time_limit,
                )
        except (TimeoutError, anthropic.APITimeoutError) as error:
            raise LLMError("Claude took too long to answer") from error
        except anthropic.APIError as error:
            raise self._failure(error) from error

        usage = LLMUsage(
            model=self.model,
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
            seconds=time.monotonic() - started,
        )
        log.debug(
            "anthropic request %s: %s, stop reason %s", message._request_id, usage.describe(), message.stop_reason
        )
        if message.stop_reason == "refusal":
            raise LLMError("Claude declined to analyse this website’s text", retry=False, usage=usage)
        if message.stop_reason == "max_tokens":
            raise LLMError("Claude’s answer was too long and was cut off", usage=usage)
        text = "".join(block.text for block in message.content if block.type == "text")
        try:
            data = answer.model_validate_json(text)
        except ValidationError as error:
            log.warning("anthropic answer in an unexpected shape: %s", error)
            raise LLMError("Claude’s answer wasn’t in the expected shape", usage=usage) from error
        return LLMAnswer(data=data, usage=usage)

    def _failure(self, error: anthropic.APIError) -> LLMError:
        """An API error as an LLMError with words for people. The details go to the log (never the key)."""
        log.warning("anthropic api error: %s: %s", type(error).__name__, error)
        if isinstance(error, anthropic.AuthenticationError):
            return LLMError("this Swatchfin server’s Anthropic API key was refused", retry=False)
        if isinstance(error, anthropic.PermissionDeniedError):
            return LLMError(f"this Swatchfin server’s Anthropic API key may not use {self.model}", retry=False)
        if isinstance(error, anthropic.NotFoundError):
            return LLMError(f"the Claude model set on this Swatchfin server ({self.model}) wasn’t found", retry=False)
        if isinstance(error, anthropic.RateLimitError):
            return LLMError("Anthropic’s rate limit was reached")
        if isinstance(error, anthropic.BadRequestError):
            return LLMError("Anthropic’s API refused the request", retry=False)
        if isinstance(error, anthropic.APIConnectionError):
            return LLMError("Anthropic’s API couldn’t be reached")
        return LLMError("Anthropic’s API was busy or unavailable")
