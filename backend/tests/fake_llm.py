"""A fake language model for the tests: it answers at once, with an answer given in advance.

In plain English: FakeLLM has the same ask() as the real AnthropicLLM
(app/llm.py), but it never calls Anthropic. It returns the answer it was
built with, or raises the LLMError it was given, and keeps every request
in `calls` so a test can check what would have been sent.

larkspur_draft() is an answer for the fake TinyFish's Larkspur Tea site.
"""

import asyncio
from typing import Any

from pydantic import BaseModel

from app.extract.voice import DraftQuote, DraftSpectrum, DraftStatement, DraftTrait, DraftValueProp, DraftVoice
from app.llm import AnswerT, LLMAnswer, LLMError, LLMUsage


class FakeLLM:
    model = "fake-model"

    def __init__(self, answer: BaseModel | LLMError | None = None, *, delay: float = 0) -> None:
        self.answer = answer
        self.delay = delay
        self.calls: list[dict[str, Any]] = []

    async def ask(
        self, *, system: str, prompt: str, answer: type[AnswerT], max_tokens: int, time_limit: float
    ) -> LLMAnswer[AnswerT]:
        self.calls.append({"system": system, "prompt": prompt, "max_tokens": max_tokens, "time_limit": time_limit})
        if self.delay:
            await asyncio.sleep(self.delay)
        if isinstance(self.answer, LLMError):
            raise self.answer
        if not isinstance(self.answer, answer):
            raise LLMError("the fake model has no answer of this type")
        return LLMAnswer(data=self.answer, usage=LLMUsage(self.model, 9_000, 2_000, 0.1))


def larkspur_draft(**changes: Any) -> DraftVoice:
    """A draft for the fake TinyFish's Larkspur Tea site, in which every quote is on its pages
    (see fake_tinyfish.py). Pass fields to change it."""
    home, about = "https://www.larkspurtea.example/", "https://www.larkspurtea.example/about"
    fields: dict[str, Any] = {
        "summary": "Plain and unhurried: short sentences about how the tea is made.",
        "traits": [
            DraftTrait(
                name="Plain-spoken",
                description="Says what happens, in everyday words.",
                evidence=[
                    DraftQuote(quote="Tea blended in small batches, shipped the week it is packed.", source_url=home)
                ],
            ),
            DraftTrait(
                name="Rooted",
                description="Points to how long the company has been doing this.",
                evidence=[
                    DraftQuote(
                        quote="Larkspurtea has blended loose-leaf tea in small batches since 2014.", source_url=about
                    )
                ],
            ),
        ],
        "spectrum": DraftSpectrum(formal_casual=55, serious_playful=30, technical_simple=80, reserved_bold=25),
        "do": ["Say when the tea was packed."],
        "dont": ["Don’t hurry the reader."],
        "tagline": DraftStatement(text="Tea blended in small batches, shipped the week it is packed.", source_url=home),
        "mission": None,
        "value_props": [
            DraftValueProp(
                title="Small batches",
                quote="Larkspurtea has blended loose-leaf tea in small batches since 2014.",
                source_url=about,
            )
        ],
        "audience": [],
    }
    return DraftVoice(**{**fields, **changes})
