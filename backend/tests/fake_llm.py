"""A fake language model for the tests: it answers at once, with an answer given in advance.

In plain English: FakeLLM has the same ask() as the real AnthropicLLM
(app/llm.py), but it never calls Anthropic. It returns the answer it was
built with, or raises the LLMError it was given, and keeps every request
in `calls` so a test can check what would have been sent.
"""

import asyncio
from typing import Any

from pydantic import BaseModel

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
