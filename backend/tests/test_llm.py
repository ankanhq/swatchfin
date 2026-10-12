"""The language models (app/llm.py): Claude, Groq, Gemini, and FallbackLLM, which asks them in turn.

Each model is tested against a fake of its provider's API: an httpx2
transport that answers like the real one, so these tests never use the
network or spend money. tests/test_llm_live.py calls the real APIs
(pytest -m live).
"""

import asyncio
import json
import logging
from collections.abc import Callable
from typing import Any

import anthropic
import httpx2
import pytest
from pydantic import BaseModel, ConfigDict, SecretStr, ValidationError

from app.config import Settings
from app.llm import ATTEMPT_TIME_LIMIT, AnthropicLLM, FallbackLLM, GeminiLLM, GroqLLM, LLMError, LLMUsage
from app.main import language_models
from tests.fake_llm import FakeLLM

pytestmark = pytest.mark.anyio


class Colour(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    hex: str


def message(text: str, *, stop_reason: str = "end_turn", thinking: bool = True) -> dict[str, Any]:
    """An answer from the Messages API, in its JSON shape."""
    content: list[dict[str, Any]] = [{"type": "thinking", "thinking": "", "signature": "sig"}] if thinking else []
    content.append({"type": "text", "text": text})
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-5-5",
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 9_000, "output_tokens": 2_000},
    }


def error(status: int, kind: str) -> httpx2.Response:
    return httpx2.Response(status, json={"type": "error", "error": {"type": kind, "message": "test"}})


def fake_llm(answer: Callable[[httpx2.Request], httpx2.Response], model: str = "claude-sonnet-5-5") -> AnthropicLLM:
    """An AnthropicLLM whose requests go to `answer` instead of Anthropic."""
    http = anthropic.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(answer))
    return AnthropicLLM(SecretStr("test-key"), model, http_client=http, max_retries=0)


async def ask(llm: AnthropicLLM) -> Any:
    return await llm.ask(system="Name a colour.", prompt="Coral.", answer=Colour, max_tokens=500, time_limit=5)


async def test_a_good_answer_is_parsed_into_the_answer_type_with_its_usage() -> None:
    sent: list[dict[str, Any]] = []

    def answer(request: httpx2.Request) -> httpx2.Response:
        sent.append(json.loads(request.content))
        return httpx2.Response(200, json=message('{"name": "Coral", "hex": "#FF5A1F"}'))

    result = await ask(fake_llm(answer))
    assert result.data == Colour(name="Coral", hex="#FF5A1F")
    assert (result.usage.api, result.usage.model, result.usage.input_tokens, result.usage.output_tokens) == (
        "anthropic",
        "claude-sonnet-5-5",
        9_000,
        2_000,
    )
    [body] = sent
    assert body["model"] == "claude-sonnet-5-5"
    assert body["system"] == "Name a colour."
    assert body["messages"] == [{"role": "user", "content": "Coral."}]
    assert body["thinking"] == {"type": "adaptive"}
    assert body["output_config"]["effort"] == "low"
    # Structured outputs: the answer's schema is sent, and nothing else may be added to it.
    schema = body["output_config"]["format"]
    assert schema["type"] == "json_schema"
    assert schema["schema"]["additionalProperties"] is False
    assert set(schema["schema"]["required"]) == {"name", "hex"}
    # No refusal fallback: a refused request isn't sent on to another model.
    assert "fallbacks" not in body


async def test_the_key_is_sent_as_a_header_and_never_in_the_body() -> None:
    headers: list[httpx2.Headers] = []

    def answer(request: httpx2.Request) -> httpx2.Response:
        headers.append(request.headers)
        assert b"test-key" not in request.content
        return httpx2.Response(200, json=message('{"name": "Ink", "hex": "#0B0F19"}'))

    await ask(fake_llm(answer))
    assert headers[0]["x-api-key"] == "test-key"


async def test_a_refusal_is_an_error_that_isnt_retried_and_still_reports_its_cost() -> None:
    llm = fake_llm(lambda _request: httpx2.Response(200, json=message("", stop_reason="refusal")))
    with pytest.raises(LLMError) as caught:
        await ask(llm)
    assert caught.value.reason == "Claude declined to analyse this website’s text"
    assert caught.value.retry is False
    assert caught.value.usage is not None and caught.value.usage.output_tokens == 2_000


async def test_an_answer_cut_off_by_the_token_limit_is_an_error() -> None:
    llm = fake_llm(lambda _request: httpx2.Response(200, json=message('{"name": "Co', stop_reason="max_tokens")))
    with pytest.raises(LLMError, match="too long") as caught:
        await ask(llm)
    assert caught.value.usage is not None


async def test_an_answer_in_the_wrong_shape_is_an_error() -> None:
    llm = fake_llm(lambda _request: httpx2.Response(200, json=message('{"colour": "coral"}', thinking=False)))
    with pytest.raises(LLMError, match="expected shape"):
        await ask(llm)


@pytest.mark.parametrize(
    ("status", "kind", "reason", "retry"),
    [
        (401, "authentication_error", "Anthropic API key was refused", False),
        (403, "permission_error", "may not use claude-sonnet-5-5", False),
        (404, "not_found_error", "(claude-sonnet-5-5) wasn’t found", False),
        (429, "rate_limit_error", "rate limit was reached", True),
        (400, "invalid_request_error", "refused the request", False),
        (402, "billing_error", "Anthropic account is out of credit", False),
        (413, "request_too_large", "refused the request", False),
        (529, "overloaded_error", "busy or unavailable", True),
        (500, "api_error", "busy or unavailable", True),
    ],
)
async def test_api_errors_become_words_for_people(status: int, kind: str, reason: str, retry: bool) -> None:
    with pytest.raises(LLMError) as caught:
        await ask(fake_llm(lambda _request: error(status, kind)))
    assert reason in caught.value.reason
    assert caught.value.retry is retry
    assert caught.value.usage is None


async def test_a_credit_balance_too_low_is_out_of_credit() -> None:
    def answer(_request: httpx2.Request) -> httpx2.Response:
        body = {"type": "invalid_request_error", "message": "Your credit balance is too low to access the API."}
        return httpx2.Response(400, json={"type": "error", "error": body})

    with pytest.raises(LLMError) as caught:
        await ask(fake_llm(answer))
    assert caught.value.reason == "this Swatchfin server’s Anthropic account is out of credit"
    assert caught.value.retry is False


async def test_no_connection_is_an_error() -> None:
    def answer(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("no route", request=request)

    with pytest.raises(LLMError, match="couldn’t be reached"):
        await ask(fake_llm(answer))


async def test_a_slow_answer_is_stopped_at_the_time_limit() -> None:
    def answer(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("slow", request=request)

    with pytest.raises(LLMError, match="too long to answer"):
        await ask(fake_llm(answer))


def test_cost_comes_from_the_published_prices() -> None:
    sonnet = LLMUsage("anthropic", "claude-sonnet-5-5", input_tokens=10_000, output_tokens=2_000, seconds=20)
    opus = LLMUsage("anthropic", "claude-opus-5-5", input_tokens=10_000, output_tokens=2_000, seconds=30)
    groq = LLMUsage("groq", "openai/gpt-oss-120b", input_tokens=10_000, output_tokens=2_000, seconds=3)
    gemini = LLMUsage("gemini", "gemini-3.8-flash", input_tokens=10_000, output_tokens=2_000, seconds=12)
    assert sonnet.cost_usd == pytest.approx(0.04)  # 10k × $2/M + 2k × $10/M
    assert opus.cost_usd == pytest.approx(0.08)
    assert groq.cost_usd == pytest.approx(0.0027)  # 10k × $0.15/M + 2k × $0.60/M (paid tier)
    assert gemini.cost_usd == pytest.approx(0.015)  # 10k × $0.75/M + 2k × $3.75/M (paid tier)
    assert sonnet.describe() == "claude-sonnet-5-5, 10,000 input + 2,000 output tokens, $0.0400, 20.0 s"


def test_a_model_without_a_listed_price_has_an_unknown_cost() -> None:
    usage = LLMUsage("anthropic", "claude-future-9", input_tokens=10, output_tokens=10, seconds=1)
    assert usage.cost_usd is None
    assert "cost unknown" in usage.describe()


# ---------------------------------------------------------------------------
# Groq and Gemini (REST APIs, called with httpx2)
# ---------------------------------------------------------------------------

RestLLM = GroqLLM | GeminiLLM


def groq(answer: Callable[[httpx2.Request], httpx2.Response]) -> GroqLLM:
    """A GroqLLM whose requests go to `answer` instead of Groq."""
    return GroqLLM(
        SecretStr("test-key"), "openai/gpt-oss-120b", httpx2.AsyncClient(transport=httpx2.MockTransport(answer))
    )


def gemini(answer: Callable[[httpx2.Request], httpx2.Response]) -> GeminiLLM:
    """A GeminiLLM whose requests go to `answer` instead of Google."""
    return GeminiLLM(
        SecretStr("test-key"), "gemini-3.8-flash", httpx2.AsyncClient(transport=httpx2.MockTransport(answer))
    )


def groq_reply(content: str, *, finish_reason: str = "stop") -> dict[str, Any]:
    """An answer from Groq's chat completions API, in its JSON shape."""
    return {
        "object": "chat.completion",
        "model": "openai/gpt-oss-120b",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": finish_reason}],
        "usage": {
            "prompt_tokens": 5_000,
            "completion_tokens": 900,
            "completion_tokens_details": {"reasoning_tokens": 120},
        },
    }


def gemini_reply(text: str, *, status: str = "completed", errors: list[dict[str, str]] | None = None) -> dict[str, Any]:
    """An answer from Gemini's Interactions API, in its JSON shape."""
    reply: dict[str, Any] = {
        "object": "interaction",
        "model": "gemini-3.8-flash",
        "status": status,
        "steps": [
            {"type": "thought", "signature": "sig"},
            {"type": "model_output", "content": [{"type": "text", "text": text}]},
        ],
        "usage": {"total_input_tokens": 5_000, "total_output_tokens": 700, "total_thought_tokens": 200},
    }
    if errors:
        reply["errors"] = errors
    return reply


async def ask_rest(llm: RestLLM, max_tokens: int = 4_000) -> Any:
    return await llm.ask(system="Name a colour.", prompt="Coral.", answer=Colour, max_tokens=max_tokens, time_limit=5)


async def test_groq_sends_the_same_instructions_and_a_strict_schema() -> None:
    sent: list[httpx2.Request] = []

    def answer(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        return httpx2.Response(200, json=groq_reply('{"name": "Coral", "hex": "#FF5A1F"}'))

    result = await ask_rest(groq(answer))
    assert result.data == Colour(name="Coral", hex="#FF5A1F")
    assert (result.usage.api, result.usage.model, result.usage.input_tokens, result.usage.output_tokens) == (
        "groq",
        "openai/gpt-oss-120b",
        5_000,
        900,
    )
    [request] = sent
    assert str(request.url) == "https://api.groq.com/openai/v1/chat/completions"
    # The key is sent as a header and never in the body.
    assert request.headers["authorization"] == "Bearer test-key"
    assert b"test-key" not in request.content
    body = json.loads(request.content)
    assert body["model"] == "openai/gpt-oss-120b"
    assert body["messages"] == [{"role": "system", "content": "Name a colour."}, {"role": "user", "content": "Coral."}]
    assert body["reasoning_effort"] == "low" and body["include_reasoning"] is False
    schema = body["response_format"]
    assert schema["type"] == "json_schema" and schema["json_schema"]["strict"] is True
    assert schema["json_schema"]["schema"]["additionalProperties"] is False
    assert set(schema["json_schema"]["schema"]["required"]) == {"name", "hex"}
    assert body["max_completion_tokens"] == 4_000


async def test_gemini_sends_the_same_instructions_and_isnt_stored() -> None:
    sent: list[httpx2.Request] = []

    def answer(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        return httpx2.Response(200, json=gemini_reply('{"name": "Coral", "hex": "#FF5A1F"}'))

    result = await ask_rest(gemini(answer), max_tokens=4_000)
    assert result.data == Colour(name="Coral", hex="#FF5A1F")
    # Thinking is billed as output, so it is counted with the answer.
    assert (result.usage.api, result.usage.model, result.usage.input_tokens, result.usage.output_tokens) == (
        "gemini",
        "gemini-3.8-flash",
        5_000,
        900,
    )
    [request] = sent
    assert str(request.url) == "https://generativelanguage.googleapis.com/v1beta/interactions"
    assert request.headers["x-goog-api-key"] == "test-key"
    assert b"test-key" not in request.content
    body = json.loads(request.content)
    assert body["model"] == "gemini-3.8-flash"
    assert body["system_instruction"] == "Name a colour."
    assert body["input"] == "Coral."
    assert body["store"] is False
    assert body["generation_config"] == {"thinking_level": "low", "max_output_tokens": 4_000}
    assert body["response_format"]["mime_type"] == "application/json"
    assert body["response_format"]["schema"]["additionalProperties"] is False


GROQ_AND_GEMINI = [pytest.param(groq, "Groq", id="groq"), pytest.param(gemini, "Gemini", id="gemini")]


@pytest.mark.parametrize(("make", "name"), GROQ_AND_GEMINI)
@pytest.mark.parametrize(
    ("status", "reason", "retry"),
    [
        (401, "this Swatchfin server’s {name} API key was refused", False),
        (402, "this Swatchfin server’s {name} account is out of credit", False),
        (403, "this Swatchfin server’s {name} API key may not use", False),
        (404, "the {name} model set on this Swatchfin server", False),
        (413, "the text was longer than this Swatchfin server’s {name} plan allows", False),
        (429, "{name}’s rate limit was reached", True),
        (400, "{name}’s API refused the request", False),
        (498, "{name}’s API refused the request", False),
        (500, "{name}’s API was busy or unavailable", True),
        (503, "{name}’s API was busy or unavailable", True),
    ],
)
async def test_http_errors_become_words_for_people(
    make: Callable[..., RestLLM], name: str, status: int, reason: str, retry: bool
) -> None:
    def answer(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(status, json={"error": {"message": "test", "code": "test"}})

    with pytest.raises(LLMError) as caught:
        await ask_rest(make(answer))
    assert reason.format(name=name) in caught.value.reason
    assert caught.value.retry is retry
    assert caught.value.usage is None


@pytest.mark.parametrize(("make", "name"), GROQ_AND_GEMINI)
async def test_the_key_never_reaches_the_log(
    make: Callable[..., RestLLM], name: str, caplog: pytest.LogCaptureFixture
) -> None:
    # Even if a provider put the key in its error message.
    def answer(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(401, json={"error": {"message": "API key test-key not valid."}})

    with caplog.at_level(logging.DEBUG, logger="swatchfin.llm"), pytest.raises(LLMError):
        await ask_rest(make(answer))
    assert caplog.records and "test-key" not in caplog.text
    assert "API key [key] not valid." in caplog.text


@pytest.mark.parametrize(("make", "name"), GROQ_AND_GEMINI)
async def test_slow_or_unreachable_apis_are_errors(make: Callable[..., RestLLM], name: str) -> None:
    def slow(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("slow", request=request)

    def unreachable(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("no route", request=request)

    with pytest.raises(LLMError, match=f"{name} took too long to answer"):
        await ask_rest(make(slow))
    with pytest.raises(LLMError, match=f"{name}’s API couldn’t be reached"):
        await ask_rest(make(unreachable))


async def test_groq_answers_in_the_wrong_shape_or_cut_off_are_errors_that_report_their_cost() -> None:
    for reply, reason in [
        (groq_reply('{"colour": "coral"}'), "Groq’s answer wasn’t in the expected shape"),
        (groq_reply('{"name": "Co', finish_reason="length"), "Groq’s answer was too long and was cut off"),
        (groq_reply("", finish_reason="content_filter"), "Groq declined to analyse this website’s text"),
    ]:
        with pytest.raises(LLMError) as caught:
            await ask_rest(groq(lambda _request, reply=reply: httpx2.Response(200, json=reply)))
        assert caught.value.reason == reason
        assert caught.value.usage is not None and caught.value.usage.output_tokens == 900


async def test_gemini_answers_in_the_wrong_shape_cut_off_or_blocked_are_errors() -> None:
    for reply, reason, retry in [
        (gemini_reply('{"colour": "coral"}'), "Gemini’s answer wasn’t in the expected shape", True),
        (gemini_reply('{"name": "Co', status="incomplete"), "Gemini’s answer was too long and was cut off", True),
        (
            gemini_reply("", status="failed", errors=[{"code": "safety", "message": "blocked"}]),
            "Gemini declined to analyse this website’s text",
            False,
        ),
        (
            gemini_reply("", status="failed", errors=[{"code": "api_error", "message": "oops"}]),
            "Gemini didn’t finish its answer",
            True,
        ),
    ]:
        with pytest.raises(LLMError) as caught:
            await ask_rest(gemini(lambda _request, reply=reply: httpx2.Response(200, json=reply)))
        assert caught.value.reason == reason
        assert caught.value.retry is retry
        assert caught.value.usage is not None and caught.value.usage.output_tokens == 900


# ---------------------------------------------------------------------------
# FallbackLLM: several models in a row
# ---------------------------------------------------------------------------

ANSWER = Colour(name="Coral", hex="#FF5A1F")


def claude_fake(answer: Any) -> FakeLLM:
    return FakeLLM(answer, api="anthropic", model="claude-sonnet-5-5")


def groq_fake(answer: Any) -> FakeLLM:
    return FakeLLM(answer, api="groq", model="openai/gpt-oss-120b")


def gemini_fake(answer: Any) -> FakeLLM:
    return FakeLLM(answer, api="gemini", model="gemini-3.8-flash")


async def ask_all(llm: FallbackLLM, time_limit: float = 75) -> Any:
    return await llm.ask(system="Name a colour.", prompt="Coral.", answer=Colour, max_tokens=500, time_limit=time_limit)


async def test_the_first_model_that_answers_is_used_and_the_rest_arent_asked() -> None:
    claude, gemini_model, groq_model = claude_fake(ANSWER), gemini_fake(ANSWER), groq_fake(ANSWER)
    result = await ask_all(FallbackLLM([claude, gemini_model, groq_model]))
    assert result.data == ANSWER
    assert (result.usage.api, result.usage.model) == ("anthropic", "claude-sonnet-5-5")
    assert result.failures == ()
    assert len(claude.calls) == 1 and gemini_model.calls == [] and groq_model.calls == []


@pytest.mark.parametrize(
    "failure",
    [
        LLMError("Anthropic’s API was busy or unavailable"),
        LLMError("Claude took too long to answer"),
        LLMError("Anthropic’s rate limit was reached"),
        LLMError("this Swatchfin server’s Anthropic account is out of credit", retry=False),
        LLMError(
            "Claude declined to analyse this website’s text",
            retry=False,
            usage=LLMUsage("anthropic", "claude-sonnet-5-5", 9_000, 10, 1.0),
        ),
    ],
    ids=["error", "timeout", "rate-limit", "out-of-credit", "refusal"],
)
async def test_any_failure_moves_on_to_the_next_model_with_the_same_request(failure: LLMError) -> None:
    claude, gemini_model = claude_fake(failure), gemini_fake(ANSWER)
    result = await ask_all(FallbackLLM([claude, gemini_model, groq_fake(ANSWER)]))
    assert (result.usage.api, result.usage.model) == ("gemini", "gemini-3.8-flash")
    assert result.failures == (f"claude-sonnet-5-5: {failure.reason}",)
    assert {key: claude.calls[0][key] for key in ("system", "prompt", "max_tokens")} == {
        key: gemini_model.calls[0][key] for key in ("system", "prompt", "max_tokens")
    }


async def test_a_crash_in_one_model_moves_on_too() -> None:
    class Broken(FakeLLM):
        async def ask(self, **kwargs: Any) -> Any:
            raise KeyError("choices")

    result = await ask_all(FallbackLLM([Broken(api="gemini", model="gemini-3.8-flash"), groq_fake(ANSWER)]))
    assert result.usage.api == "groq"
    assert result.failures == ("gemini-3.8-flash: something went wrong while asking Gemini",)


async def test_when_every_model_fails_the_error_gives_each_reason() -> None:
    models = FallbackLLM(
        [
            claude_fake(LLMError("this Swatchfin server’s Anthropic account is out of credit", retry=False)),
            gemini_fake(LLMError("Gemini’s rate limit was reached")),
            groq_fake(LLMError("the text was longer than this Swatchfin server’s Groq plan allows", retry=False)),
        ]
    )
    with pytest.raises(LLMError) as caught:
        await ask_all(models)
    assert caught.value.reason == (
        "no language model gave a usable answer (this Swatchfin server’s Anthropic account is out of credit; "
        "Gemini’s rate limit was reached; the text was longer than this Swatchfin server’s Groq plan allows)"
    )
    # Gemini's rate limit may have passed by the next try.
    assert caught.value.retry is True


async def test_with_only_one_model_its_own_error_is_raised() -> None:
    failure = LLMError("Claude declined to analyse this website’s text", retry=False)
    with pytest.raises(LLMError) as caught:
        await ask_all(FallbackLLM([claude_fake(failure)]))
    assert caught.value is failure


async def test_each_model_but_the_last_gets_a_share_of_the_time() -> None:
    claude = claude_fake(LLMError("Anthropic’s API was busy or unavailable"))
    gemini_model = gemini_fake(LLMError("Gemini’s API was busy or unavailable"))
    groq_model = groq_fake(ANSWER)
    await ask_all(FallbackLLM([claude, gemini_model, groq_model]), time_limit=75)
    assert claude.calls[0]["time_limit"] == ATTEMPT_TIME_LIMIT == 30
    assert gemini_model.calls[0]["time_limit"] == 30
    # The last model gets whatever is left.
    assert 74 < groq_model.calls[0]["time_limit"] <= 75


async def test_a_model_isnt_asked_without_enough_time_left() -> None:
    class Slow(FakeLLM):
        async def ask(self, **kwargs: Any) -> Any:
            self.calls.append(kwargs)
            await asyncio.sleep(0.2)
            raise LLMError("Claude took too long to answer")

    claude = Slow(api="anthropic", model="claude-sonnet-5-5")
    gemini_model, groq_model = gemini_fake(ANSWER), groq_fake(ANSWER)
    models = FallbackLLM([claude, gemini_model, groq_model], attempt_time_limit=0.2, min_attempt_time=0.1)
    with pytest.raises(LLMError) as caught:
        await ask_all(models, time_limit=0.25)
    assert caught.value.reason == (
        "no language model gave a usable answer (Claude took too long to answer; there was no time left to ask "
        "Gemini or Groq)"
    )
    assert gemini_model.calls == [] and groq_model.calls == []


async def test_closing_the_row_closes_every_model() -> None:
    models = [claude_fake(ANSWER), groq_fake(ANSWER)]
    await FallbackLLM(models).close()
    assert all(model.closed for model in models)


# ---------------------------------------------------------------------------
# Which models main.py puts in the row
# ---------------------------------------------------------------------------


def test_every_model_with_a_key_is_used_in_llm_order(make_settings: Callable[..., Settings]) -> None:
    settings = make_settings(anthropic_api_key="a-key", groq_api_key="g-key", gemini_api_key="m-key")
    # The default order, from the benchmark: Claude, then Gemini, then Groq.
    assert settings.llm_apis == ["anthropic", "gemini", "groq"]
    llm = language_models(settings, httpx2.AsyncClient())
    assert llm is not None
    assert [(model.api, model.model) for model in llm.models] == [
        ("anthropic", "claude-sonnet-5-5"),
        ("gemini", "gemini-3.8-flash"),
        ("groq", "openai/gpt-oss-120b"),
    ]
    # Claude doesn't wait to retry a busy moment when another model comes after it.
    claude = llm.models[0]
    assert isinstance(claude, AnthropicLLM) and claude._client.max_retries == 0


def test_llm_order_chooses_the_models_and_their_order(make_settings: Callable[..., Settings]) -> None:
    settings = make_settings(
        anthropic_api_key="a-key", groq_api_key="g-key", gemini_api_key="m-key", llm_order="gemini, anthropic"
    )
    llm = language_models(settings, httpx2.AsyncClient())
    assert llm is not None
    assert [model.api for model in llm.models] == ["gemini", "anthropic"]
    # Claude is last here, so it may retry once.
    assert isinstance(llm.models[1], AnthropicLLM) and llm.models[1]._client.max_retries == 1


def test_a_model_without_a_key_is_left_out(make_settings: Callable[..., Settings]) -> None:
    llm = language_models(make_settings(gemini_api_key="m-key"), httpx2.AsyncClient())
    assert llm is not None and [model.api for model in llm.models] == ["gemini"]
    assert language_models(make_settings(), httpx2.AsyncClient()) is None


def test_llm_order_must_name_known_models(make_settings: Callable[..., Settings]) -> None:
    assert make_settings(llm_order="groq,groq, gemini").llm_apis == ["groq", "gemini"]
    for order in ("openai", "anthropic,,groq", "", "anthropic;groq"):
        with pytest.raises(ValidationError):
            make_settings(llm_order=order)
