"""The language models behind step 6: they read a brand's text and draft its tone of voice.

In plain English: the pipeline only knows the `LLM` shape below: "send
instructions and text, get back data of this shape". Three real models
have that shape, each through its own provider's API:

- AnthropicLLM: Claude (ANTHROPIC_MODEL, claude-sonnet-5-5 by default),
  through Anthropic's official SDK.
- GeminiLLM: Google's Gemini Flash (GEMINI_MODEL, gemini-3.8-flash by
  default), through Google's Gemini Interactions REST API.
- GroqLLM: an open model run by Groq (GROQ_MODEL, openai/gpt-oss-120b by
  default), through Groq's OpenAI-style REST API.

FallbackLLM puts the ones that have a key in a row (LLM_ORDER: Anthropic,
then Gemini, then Groq). It asks the first. When that gives no usable
answer, for any reason (an error, too slow, a rate limit, no credit left,
a refusal, an answer in the wrong shape), it asks the next one, with the
same instructions and the same text. The guide names the model that
answered. The tests use a fake model, so they never spend money.

Every model gets the same answer shape (a Pydantic class): each API's
structured outputs make the reply JSON in that shape, and Pydantic checks
it again here. Step 7 (verify.py) then checks every quote word for word,
whichever model wrote it.

Each call reports its token counts and what it costs in US dollars at the
provider's published prices. The pipeline logs that once per guide; the
guide itself doesn't mention cost. Groq's and Google's free tiers cost
nothing: for them the logged price is what the same call costs on their
paid tiers.

Every model thinks only a little ("low"): copying quotes and naming a voice
is reading work, not hard reasoning, and low effort keeps answers quick and
cheap.
"""

import asyncio
import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any, Generic, Literal, Protocol, TypeVar

import anthropic
import httpx2
from pydantic import BaseModel, SecretStr, ValidationError

log = logging.getLogger("swatchfin.llm")

AnswerT = TypeVar("AnswerT", bound=BaseModel)

# The APIs that can draft a tone of voice, as LLM_ORDER and the guide name them.
Api = Literal["anthropic", "groq", "gemini"]
APIS: tuple[Api, ...] = ("anthropic", "groq", "gemini")
# Each API in messages for people: "Groq’s rate limit was reached".
NAMES: dict[Api, str] = {"anthropic": "Anthropic", "groq": "Groq", "gemini": "Gemini"}

# US dollars per million tokens, (input, output). Thinking is billed as output. A model missing here
# still works; its cost is logged as unknown.
PRICES: dict[str, tuple[float, float]] = {
    # https://platform.claude.com/docs/en/about-claude/pricing (October 2026)
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
    "claude-haiku-5-5": (0.10, 0.50),
    # https://console.groq.com/docs/model/openai/gpt-oss-120b (October 2026). Free on Groq's free tier.
    "openai/gpt-oss-120b": (0.15, 0.60),
    # https://ai.google.dev/gemini-api/docs/pricing, paid tier until 31 December 2026 ($1.50 and $7.50
    # from 2027). Free on Google's free tier.
    "gemini-3.8-flash": (0.75, 3.75),
}
EFFORT = "low"

# FallbackLLM: each model but the last gets at most this long, so a slow one leaves time for the next.
# Measured answers took 8 to 9 s (Claude), 3 to 4 s (Groq) and 9 to 18 s (Gemini); out of step 6's 75 s, two
# slow failures still leave 15 s for the third model.
ATTEMPT_TIME_LIMIT = 30.0
# A model isn't asked with less time than this left.
MIN_ATTEMPT_TIME = 8.0

# Gemini's reasons for blocking an answer (https://ai.google.dev/gemini-api/docs/api-errors).
GEMINI_BLOCKED = frozenset(
    {"safety", "recitation", "language", "prohibited_content", "spii", "blocklist", "content_blocked"}
)


@dataclass(frozen=True)
class LLMUsage:
    """What one call used."""

    api: Api
    model: str
    input_tokens: int
    output_tokens: int
    seconds: float

    @property
    def cost_usd(self) -> float | None:
        """What the call costs in US dollars, or None for a model whose price isn't in PRICES."""
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
    # The models asked before this one that gave no usable answer, for the log:
    # "claude-sonnet-5-5: Anthropic’s rate limit was reached".
    failures: tuple[str, ...] = ()


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
    """What the pipeline needs from a language model: one model, or several in a row (FallbackLLM)."""

    async def ask(
        self, *, system: str, prompt: str, answer: type[AnswerT], max_tokens: int, time_limit: float
    ) -> LLMAnswer[AnswerT]:
        """Sends the instructions (`system`) and the text (`prompt`), and returns an answer of type `answer`.
        Raises LLMError when there is no usable answer within `time_limit` seconds."""
        ...


class ProviderLLM(LLM, Protocol):
    """One provider's model."""

    api: Api
    model: str

    async def close(self) -> None: ...


# ---------------------------------------------------------------------------
# Anthropic: Claude
# ---------------------------------------------------------------------------


class AnthropicLLM:
    """Claude, through Anthropic's official Python SDK."""

    api: Api = "anthropic"

    def __init__(
        self,
        api_key: SecretStr,
        model: str,
        *,
        http_client: anthropic.DefaultAsyncHttpxClient | None = None,
        max_retries: int = 1,
    ) -> None:
        self.model = model
        # Retries for a busy moment (429, 529, 5xx); ask()'s time limit still holds. main.py turns them
        # off when another model comes next, so that one is asked straight away instead.
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
            api=self.api,
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
        return LLMAnswer(data=_parse(answer, text, "Claude", usage), usage=usage)

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
        # Out of credit: 402, or a 400 that says the credit balance is too low.
        if (isinstance(error, anthropic.APIStatusError) and error.status_code == 402) or (
            isinstance(error, anthropic.BadRequestError) and "credit balance" in str(error).lower()
        ):
            return LLMError(_out_of_credit("Anthropic"), retry=False)
        if isinstance(error, anthropic.BadRequestError | anthropic.RequestTooLargeError):
            return LLMError("Anthropic’s API refused the request", retry=False)
        if isinstance(error, anthropic.APIConnectionError):
            return LLMError("Anthropic’s API couldn’t be reached")
        return LLMError("Anthropic’s API was busy or unavailable")


# ---------------------------------------------------------------------------
# Groq: an open model
# ---------------------------------------------------------------------------


class GroqLLM:
    """A model run by Groq, through its OpenAI-style chat completions API.

    Called with httpx2, like TinyFish, rather than an SDK. GROQ_MODEL must be
    a reasoning model with strict structured outputs (openai/gpt-oss-120b,
    openai/gpt-oss-20b): https://console.groq.com/docs/structured-outputs.

    Groq's free tier allows 8,000 tokens a minute. A text longer than that
    is refused outright (HTTP 413), and a second guide within the same
    minute may hit the rate limit (429); either way the next model is asked.
    """

    api: Api = "groq"
    URL = "https://api.groq.com/openai/v1/chat/completions"

    def __init__(self, api_key: SecretStr, model: str, http: httpx2.AsyncClient) -> None:
        self.model = model
        self._api_key = api_key
        # Shared with TinyFish (one connection pool) and closed by main.py, so close() has nothing to do.
        self._http = http

    async def close(self) -> None:
        pass

    async def ask(
        self, *, system: str, prompt: str, answer: type[AnswerT], max_tokens: int, time_limit: float
    ) -> LLMAnswer[AnswerT]:
        started = time.monotonic()
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            # Strict: the reply is always JSON in the answer's shape.
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": answer.__name__, "strict": True, "schema": answer.model_json_schema()},
            },
            "reasoning_effort": EFFORT,
            # The model's thinking isn't needed, so it isn't sent back.
            "include_reasoning": False,
            "max_completion_tokens": max_tokens,
        }
        key = self._api_key.get_secret_value()
        data = await _post(self._http, self.URL, {"Authorization": f"Bearer {key}"}, body, self, key, time_limit)

        counts = data.get("usage") or {}
        usage = LLMUsage(
            api=self.api,
            model=self.model,
            input_tokens=int(counts.get("prompt_tokens") or 0),
            # Includes the thinking (completion_tokens_details.reasoning_tokens).
            output_tokens=int(counts.get("completion_tokens") or 0),
            seconds=time.monotonic() - started,
        )
        choice = (data.get("choices") or [{}])[0]
        finish = choice.get("finish_reason")
        log.debug("groq request: %s, finish reason %s", usage.describe(), finish)
        if finish == "length":
            raise LLMError("Groq’s answer was too long and was cut off", usage=usage)
        if finish == "content_filter":
            raise LLMError("Groq declined to analyse this website’s text", retry=False, usage=usage)
        text = (choice.get("message") or {}).get("content") or ""
        return LLMAnswer(data=_parse(answer, text, "Groq", usage), usage=usage)


# ---------------------------------------------------------------------------
# Google: Gemini
# ---------------------------------------------------------------------------


class GeminiLLM:
    """Google's Gemini, through the Gemini Interactions API.

    Called with httpx2, like TinyFish, rather than an SDK. Each request is
    sent with store: false, so Google doesn't keep it as a conversation to
    continue: https://ai.google.dev/gemini-api/docs/interactions.
    """

    api: Api = "gemini"
    URL = "https://generativelanguage.googleapis.com/v1beta/interactions"

    def __init__(self, api_key: SecretStr, model: str, http: httpx2.AsyncClient) -> None:
        self.model = model
        self._api_key = api_key
        # Shared with TinyFish (one connection pool) and closed by main.py, so close() has nothing to do.
        self._http = http

    async def close(self) -> None:
        pass

    async def ask(
        self, *, system: str, prompt: str, answer: type[AnswerT], max_tokens: int, time_limit: float
    ) -> LLMAnswer[AnswerT]:
        started = time.monotonic()
        body = {
            "model": self.model,
            "system_instruction": system,
            "input": prompt,
            "store": False,
            # max_output_tokens counts the thinking too, as with Claude.
            "generation_config": {"thinking_level": EFFORT, "max_output_tokens": max_tokens},
            "response_format": {"type": "text", "mime_type": "application/json", "schema": answer.model_json_schema()},
        }
        key = self._api_key.get_secret_value()
        data = await _post(self._http, self.URL, {"x-goog-api-key": key}, body, self, key, time_limit)

        counts = data.get("usage") or {}
        usage = LLMUsage(
            api=self.api,
            model=self.model,
            input_tokens=int(counts.get("total_input_tokens") or 0),
            # The thinking is counted apart from the answer, and billed as output.
            output_tokens=int(counts.get("total_output_tokens") or 0) + int(counts.get("total_thought_tokens") or 0),
            seconds=time.monotonic() - started,
        )
        status = data.get("status")
        log.debug("gemini request: %s, status %s", usage.describe(), status)
        if status == "incomplete":
            raise LLMError("Gemini’s answer was too long and was cut off", usage=usage)
        if status != "completed":
            codes = {str(error.get("code")) for error in data.get("errors") or [] if isinstance(error, dict)}
            log.warning("gemini interaction %s: %s", status, sorted(codes))
            if codes & GEMINI_BLOCKED:
                raise LLMError("Gemini declined to analyse this website’s text", retry=False, usage=usage)
            raise LLMError("Gemini didn’t finish its answer", usage=usage)
        text = "".join(
            part.get("text") or ""
            for step in data.get("steps") or []
            if step.get("type") == "model_output"
            for part in step.get("content") or []
            if part.get("type") == "text"
        )
        return LLMAnswer(data=_parse(answer, text, "Gemini", usage), usage=usage)


# ---------------------------------------------------------------------------
# Several models in a row
# ---------------------------------------------------------------------------


class FallbackLLM:
    """Asks each model in turn until one gives a usable answer (see the top of this file).

    Every model but the last gets at most `attempt_time_limit` seconds, so a
    slow one leaves time for the next; the last one gets whatever is left.
    A model isn't asked with less than `min_attempt_time` seconds left.
    """

    def __init__(
        self,
        models: Sequence[ProviderLLM],
        *,
        attempt_time_limit: float = ATTEMPT_TIME_LIMIT,
        min_attempt_time: float = MIN_ATTEMPT_TIME,
    ) -> None:
        if not models:
            raise ValueError("FallbackLLM needs at least one model")
        self.models = list(models)
        self._attempt_time_limit = attempt_time_limit
        self._min_attempt_time = min_attempt_time

    async def close(self) -> None:
        for model in self.models:
            await model.close()

    async def ask(
        self, *, system: str, prompt: str, answer: type[AnswerT], max_tokens: int, time_limit: float
    ) -> LLMAnswer[AnswerT]:
        deadline = time.monotonic() + time_limit
        failures: list[tuple[ProviderLLM, LLMError]] = []
        for index, model in enumerate(self.models):
            left = deadline - time.monotonic()
            if left < self._min_attempt_time:
                untried = _join_or([NAMES[later.api] for later in self.models[index:]])
                failures.append((model, LLMError(f"there was no time left to ask {untried}")))
                break
            is_last = index == len(self.models) - 1
            try:
                result = await model.ask(
                    system=system,
                    prompt=prompt,
                    answer=answer,
                    max_tokens=max_tokens,
                    time_limit=left if is_last else min(left, self._attempt_time_limit),
                )
            except LLMError as error:
                failures.append((model, error))
            except Exception:
                # A bug in one provider's code mustn't stop the others from being asked.
                log.exception("%s crashed", model.model)
                failures.append((model, LLMError(f"something went wrong while asking {NAMES[model.api]}")))
            else:
                return replace(result, failures=tuple(f"{tried.model}: {error.reason}" for tried, error in failures))
            tried, error = failures[-1]
            billed = f" ({error.usage.describe()})" if error.usage else ""
            log.info("%s gave no usable answer: %s%s", tried.model, error.reason, billed)

        if len(failures) == 1:
            raise failures[0][1]
        reasons = "; ".join(error.reason for _model, error in failures)
        raise LLMError(
            f"no language model gave a usable answer ({reasons})",
            retry=any(error.retry for _model, error in failures),
        )


# ---------------------------------------------------------------------------
# Shared by the providers
# ---------------------------------------------------------------------------


def _parse(answer: type[AnswerT], text: str, name: str, usage: LLMUsage) -> AnswerT:
    """The answer's JSON checked against its shape. Raises LLMError when it doesn't fit."""
    try:
        return answer.model_validate_json(text)
    except ValidationError as error:
        log.warning("%s answer in an unexpected shape: %s", usage.api, error)
        raise LLMError(f"{name}’s answer wasn’t in the expected shape", usage=usage) from error


async def _post(
    http: httpx2.AsyncClient,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    caller: ProviderLLM,
    key: str,
    time_limit: float,
) -> dict[str, Any]:
    """One POST to Groq's or Gemini's API, its JSON answer back. Raises LLMError with words for people.

    Not retried: FallbackLLM asks the next model instead. The details of a
    failure go to the log, never the key: it is sent only in the headers,
    and taken out of any error message before that is logged.
    """
    api, model = caller.api, caller.model
    name = NAMES[api]
    try:
        async with asyncio.timeout(time_limit):
            response = await http.post(url, json=body, headers=headers, timeout=time_limit)
    except (TimeoutError, httpx2.TimeoutException) as error:
        raise LLMError(f"{name} took too long to answer") from error
    except httpx2.TransportError as error:
        log.warning("%s api couldn't be reached: %s", api, type(error).__name__)
        raise LLMError(f"{name}’s API couldn’t be reached") from error

    status = response.status_code
    if status >= 400:
        message = _error_message(response)
        log.warning("%s api error: HTTP %d: %s", api, status, message.replace(key, "[key]") if key else message)
        raise _status_failure(name, model, status)
    try:
        data = response.json()
    except ValueError as error:
        raise LLMError(f"{name}’s API was busy or unavailable") from error
    if not isinstance(data, dict):
        raise LLMError(f"{name}’s API was busy or unavailable")
    return data


def _status_failure(name: str, model: str, status: int) -> LLMError:
    """An HTTP error from Groq or Gemini as an LLMError (see each provider's error table)."""
    if status == 401:
        return LLMError(f"this Swatchfin server’s {name} API key was refused", retry=False)
    if status == 402:
        return LLMError(_out_of_credit(name), retry=False)
    if status == 403:
        return LLMError(f"this Swatchfin server’s {name} API key may not use {model}", retry=False)
    if status == 404:
        return LLMError(f"the {name} model set on this Swatchfin server ({model}) wasn’t found", retry=False)
    if status == 413:
        # Groq: the text is longer than the plan allows in a minute.
        return LLMError(f"the text was longer than this Swatchfin server’s {name} plan allows", retry=False)
    if status == 429:
        return LLMError(f"{name}’s rate limit was reached")
    if 400 <= status < 500:
        return LLMError(f"{name}’s API refused the request", retry=False)
    return LLMError(f"{name}’s API was busy or unavailable")


def _error_message(response: httpx2.Response) -> str:
    """The message in an error answer, short, for the log."""
    try:
        error = response.json().get("error") or {}
        message = str(error.get("message") or error)
    except (ValueError, AttributeError):
        message = response.text
    return message[:300]


def _out_of_credit(name: str) -> str:
    return f"this Swatchfin server’s {name} account is out of credit"


def _join_or(items: list[str]) -> str:
    """["a", "b", "c"] -> "a, b or c"."""
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} or {items[-1]}"
