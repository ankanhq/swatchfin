"""Rate limits: how often visitors may use the API, and how many new guides Swatchfin makes a day.

Three limits apply (all can be changed in .env, see config.py):
- all API requests: 300 per minute per visitor, enough for a few open
  guide pages that each ask for their job's status every 1.5 seconds;
- new guides: 5 per visitor per day, because every guide costs TinyFish
  calls and a language model call;
- new guides for everyone together: 50 per day (UTC), so a busy day can't
  use up the free allowances or the credit (DailyLimit, below).
A guide reused from the last 24 hours (see reuse.py) counts toward neither
guide limit.

Who is a "visitor"? Their IP address. Behind a host's proxy (such as
Render), every request seems to come from the proxy, and the visitor's
address is in the X-Forwarded-For header instead. See Visitors, below.
"""

import logging
import math
import time
from collections import deque
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta

log = logging.getLogger("swatchfin.ratelimit")

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

    def give_back(self, visitor: str) -> None:
        """Un-counts the visitor's latest request, e.g. a guide that turned out to be reused."""
        times = self._hits.get(visitor)
        if times:
            times.pop()

    def _forget_old(self, times: deque[float], now: float) -> None:
        while times and times[0] <= now - self.window:
            times.popleft()

    def _forget_quiet_visitors(self, now: float) -> None:
        for visitor in list(self._hits):
            self._forget_old(self._hits[visitor], now)
            if not self._hits[visitor]:
                del self._hits[visitor]


class DailyLimit:
    """At most `limit` new guides a day for everyone together. Days are UTC days.

    In plain English: a counter that goes back to 0 at midnight UTC. The
    count lives in memory, so a restart would also set it back to 0. On a
    free server that sleeps when nobody visits, that would happen several
    times a day. So when the server starts, main.py asks TinyFish how many
    guides were made today (one Browser session each) and calls
    start_from() with that number.
    """

    def __init__(self, limit: int, clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self.limit = limit
        self._clock = clock  # the tests pass a fake clock
        self._day: date = clock().date()
        self._used = 0

    @property
    def used(self) -> int:
        self._new_day_check()
        return self._used

    def take(self) -> float | None:
        """Counts one new guide. Returns None if it is allowed, or the seconds until midnight UTC if not."""
        self._new_day_check()
        if self._used >= self.limit:
            now = self._clock()
            midnight = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), tzinfo=UTC)
            return (midnight - now).total_seconds()
        self._used += 1
        return None

    def give_back(self) -> None:
        """Un-counts one guide, e.g. one that turned out to be reused or couldn't start."""
        self._new_day_check()
        self._used = max(0, self._used - 1)

    def start_from(self, used_today: int) -> None:
        """Counts the guides already made today, before this server started."""
        self._new_day_check()
        self._used = max(self._used, used_today)

    def _new_day_check(self) -> None:
        today = self._clock().date()
        if today != self._day:
            self._day = today
            self._used = 0


class Visitors:
    """Works out a request's visitor: their IP address.

    On your computer the visitor is whoever connects to the server
    (`proxy_hops` = 0). On a host like Render, a proxy connects instead and
    writes the visitor's address in the X-Forwarded-For header. That header
    is a list, and each proxy adds the address it got the request from to
    the end of it. The visitor can send the header too, with any made-up
    addresses in it, and Render keeps them: so the first entry can't be
    trusted. Only the entries the proxies added can. With `proxy_hops`
    proxies in front of the app, the visitor's real address is the entry
    `proxy_hops` places from the end.

    The first time a request with the header arrives, the log says how many
    entries it had (never the addresses), so the right PROXY_HOPS can be
    checked after a deploy (see docs/deploy-render.md).
    """

    def __init__(self, proxy_hops: int) -> None:
        self.proxy_hops = proxy_hops
        self._logged = False

    def address(self, client_host: str | None, forwarded_for: str | None) -> str:
        """The visitor's address, from the connection and the X-Forwarded-For header."""
        if self.proxy_hops and forwarded_for:
            entries = [entry.strip() for entry in forwarded_for.split(",")]
            if not self._logged:
                self._logged = True
                log.info(
                    "X-Forwarded-For had %d entries; PROXY_HOPS=%d reads the one %d from the end",
                    len(entries),
                    self.proxy_hops,
                    self.proxy_hops,
                )
            # Fewer entries than proxies shouldn't happen; the first one is then the best there is.
            chosen = entries[-self.proxy_hops] if len(entries) >= self.proxy_hops else entries[0]
            if chosen:
                return chosen
        return client_host or "unknown"


def wait_words(seconds: float) -> str:
    """42 -> "42 seconds", 600 -> "10 minutes", 25_000 -> "7 hours"."""
    if seconds < 60:
        whole = max(1, math.ceil(seconds))
        return f"{whole} second{'s' if whole != 1 else ''}"
    if seconds < 60 * 60:
        minutes = math.ceil(seconds / 60)
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    hours = math.ceil(seconds / (60 * 60))
    return f"{hours} hour{'s' if hours != 1 else ''}"
