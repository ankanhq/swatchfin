"""The connection to TinyFish, shared by Search and Fetch (and Browser from Phase 6).

In plain English: every TinyFish call goes through TinyFishClient.call().
It adds the API key header, waits no longer than a time limit, and tries
again (twice at most, after a short pause) when TinyFish is busy or has a
passing problem. When a call fails for good it raises TinyFishError, which
says what went wrong in words for people, ready for the guide page.

The key is kept as a "secret string" and only unwrapped to build the
header, so it never appears in a log or an error message.
"""

import asyncio
import logging
from typing import Any, Literal

import httpx2
from pydantic import SecretStr

log = logging.getLogger("swatchfin.tinyfish")

# Answers that mean "busy or a passing problem, try again shortly".
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
# The longest pause between tries, even if TinyFish asks for longer (Retry-After).
MAX_PAUSE_SECONDS = 5.0

ErrorKind = Literal["not_configured", "auth", "credits", "rate_limited", "unavailable", "bad_request"]

# What each kind of failure means, for people: (title, message).
ERROR_TEXT: dict[ErrorKind, tuple[str, str]] = {
    "not_configured": (
        "Swatchfin can’t read websites right now",
        "Swatchfin isn’t connected to TinyFish, the service it uses to read websites. Try again later.",
    ),
    "auth": (
        "Swatchfin can’t read websites right now",
        "TinyFish, the service Swatchfin uses to read websites, didn’t accept Swatchfin’s key. Try again later.",
    ),
    "credits": (
        "Swatchfin has reached today’s limit",
        "Swatchfin has used today’s free allowance from TinyFish, the service it uses to read websites. "
        "The allowance resets at midnight UTC. Try again then.",
    ),
    "rate_limited": (
        "Swatchfin is busy",
        "TinyFish, the service Swatchfin uses to read websites, got too many requests at once. Try again in a minute.",
    ),
    "unavailable": (
        "TinyFish didn’t answer",
        "TinyFish, the service Swatchfin uses to read websites, didn’t answer in time. Try again in a moment.",
    ),
    "bad_request": (
        "The guide couldn’t be finished",
        "Something went wrong on Swatchfin’s side while reading the website. Try again in a moment.",
    ),
}


class TinyFishError(Exception):
    """A whole TinyFish call failed. `title` and `message` are for people."""

    def __init__(self, kind: ErrorKind, detail: str = "") -> None:
        self.kind: ErrorKind = kind
        self.title, self.message = ERROR_TEXT[kind]
        # For the log only (e.g. "HTTP 503 from api.fetch.tinyfish.ai"). Never contains the key.
        self.detail = detail
        super().__init__(f"{kind}: {detail}" if detail else kind)


class TinyFishClient:
    """Calls the TinyFish APIs with Swatchfin's key.

    `http` is shared by every call and job (one connection pool), and is
    closed by main.py when the server stops. The tests pass in an http
    client with a fake TinyFish behind it, so they never use the network.
    """

    def __init__(
        self,
        api_key: SecretStr | None,
        http: httpx2.AsyncClient,
        *,
        retries: int = 2,
        pause_seconds: float = 1.0,
    ) -> None:
        self._api_key = api_key
        self._http = http
        self._retries = retries
        self._pause = pause_seconds

    @property
    def configured(self) -> bool:
        """True when there is a key to call TinyFish with."""
        return self._api_key is not None and bool(self._api_key.get_secret_value())

    async def call(
        self,
        method: Literal["GET", "POST"],
        url: str,
        *,
        time_limit: float,
        params: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
    ) -> Any:
        """Makes one TinyFish call and returns its JSON answer.

        In plain English: send the request. If TinyFish is busy (429) or has
        a passing problem (5xx, or the connection dropped), wait a moment and
        try again, up to `retries` more times. A slow answer is not retried:
        it has already used up its time. Any other failure raises
        TinyFishError straight away.
        """
        if self._api_key is None or not self.configured:
            raise TinyFishError("not_configured", "no TINYFISH_API_KEY")
        headers = {"X-API-Key": self._api_key.get_secret_value(), "Accept": "application/json"}
        host = httpx2.URL(url).host

        for attempt in range(self._retries + 1):
            last_try = attempt == self._retries
            try:
                response = await self._http.request(
                    method, url, params=params, json=body, headers=headers, timeout=time_limit
                )
            except httpx2.TimeoutException as error:
                raise TinyFishError("unavailable", f"timed out after {time_limit:.0f}s ({host})") from error
            except httpx2.TransportError as error:
                if last_try:
                    raise TinyFishError("unavailable", f"{type(error).__name__} ({host})") from error
                log.info("tinyfish connection problem host=%s, trying again", host)
                await asyncio.sleep(self._pause_before(attempt))
                continue

            status = response.status_code
            if status < 400:
                try:
                    return response.json()
                except ValueError as error:
                    raise TinyFishError("unavailable", f"answer wasn’t JSON ({host})") from error

            if status in RETRY_STATUSES and not last_try:
                log.info("tinyfish busy status=%d host=%s, trying again", status, host)
                await asyncio.sleep(self._pause_before(attempt, response.headers.get("Retry-After")))
                continue

            raise TinyFishError(_kind_for(status), f"HTTP {status} from {host}")

        # The loop always returns or raises; this line is never reached.
        raise TinyFishError("unavailable", f"no answer ({host})")

    def _pause_before(self, attempt: int, retry_after: str | None = None) -> float:
        """How long to wait before the next try: 1 s, then 2 s (or what TinyFish asks for, up to 5 s)."""
        pause = self._pause * (2**attempt)
        if retry_after is not None:
            try:
                pause = float(retry_after)
            except ValueError:
                pass
        return max(0.0, min(pause, MAX_PAUSE_SECONDS))


def _kind_for(status: int) -> ErrorKind:
    """Which kind of failure an HTTP status from TinyFish is (see the docs' error tables)."""
    if status == 401:
        return "auth"
    if status == 402:
        return "credits"
    if status == 429:
        return "rate_limited"
    if status == 403 or status >= 500:
        return "unavailable"
    return "bad_request"
