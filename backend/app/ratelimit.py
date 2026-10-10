"""Rate limits: how often one visitor (one IP address) may use the API.

Two limits apply (both can be changed in .env, see config.py):
- new guides: 20 per hour, because every guide costs TinyFish calls;
- all API requests: 300 per minute, enough for a few open guide pages
  that each ask for their job's status every 1.5 seconds.

Note for deployment: behind a host's proxy (such as Render), every request
seems to come from the proxy's address. Uvicorn's --proxy-headers option
makes it read the visitor's real address instead.
"""

import time
from collections import deque
from collections.abc import Callable

# Above this many remembered visitors, forget the ones with no recent requests.
MAX_REMEMBERED = 10_000


class RateLimiter:
    """Allows each visitor `limit` requests in any `window_seconds`-long stretch of time.

    In plain English: it remembers when each visitor made their recent
    requests. A new request is allowed when fewer than `limit` of them
    happened in the last `window_seconds`. Otherwise it is refused, and
    hit() says how many seconds until the oldest one is old enough to stop
    counting.
    """

    def __init__(self, limit: int, window_seconds: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.limit = limit
        self.window = window_seconds
        self._clock = clock  # the tests pass a fake clock
        self._hits: dict[str, deque[float]] = {}

    def hit(self, visitor: str) -> float | None:
        """Counts one request. Returns None if it is allowed, or the seconds to wait if not."""
        now = self._clock()
        times = self._hits.setdefault(visitor, deque())
        self._forget_old(times, now)

        if len(times) >= self.limit:
            return times[0] + self.window - now
        times.append(now)

        if len(self._hits) > MAX_REMEMBERED:
            self._forget_quiet_visitors(now)
        return None

    def _forget_old(self, times: deque[float], now: float) -> None:
        while times and times[0] <= now - self.window:
            times.popleft()

    def _forget_quiet_visitors(self, now: float) -> None:
        for visitor in list(self._hits):
            self._forget_old(self._hits[visitor], now)
            if not self._hits[visitor]:
                del self._hits[visitor]
