"""The language model wrapper (app/llm.py).

AnthropicLLM is tested against a fake Anthropic API: an httpx2 transport
that answers like the real one, so these tests never use the network or
spend money. tests/test_llm_live.py calls the real API (pytest -m live).
"""

import json
from collections.abc import Callable
from typing import Any

import anthropic
import httpx2
import pytest
from pydantic import BaseModel, ConfigDict, SecretStr

from app.llm import AnthropicLLM, LLMError, LLMUsage

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
    assert (result.usage.model, result.usage.input_tokens, result.usage.output_tokens) == (
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
    sonnet = LLMUsage("claude-sonnet-5-5", input_tokens=10_000, output_tokens=2_000, seconds=20)
    opus = LLMUsage("claude-opus-5-5", input_tokens=10_000, output_tokens=2_000, seconds=30)
    assert sonnet.cost_usd == pytest.approx(0.04)  # 10k × $2/M + 2k × $10/M
    assert opus.cost_usd == pytest.approx(0.08)
    assert sonnet.describe() == "claude-sonnet-5-5, 10,000 input + 2,000 output tokens, $0.0400, 20.0 s"


def test_a_model_without_a_listed_price_has_an_unknown_cost() -> None:
    usage = LLMUsage("claude-future-9", input_tokens=10, output_tokens=10, seconds=1)
    assert usage.cost_usd is None
    assert "cost unknown" in usage.describe()
