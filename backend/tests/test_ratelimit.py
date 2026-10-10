"""Rate limits (app/ratelimit.py), with a fake clock instead of waiting."""

from app.ratelimit import RateLimiter


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_allows_the_limit_then_says_how_long_to_wait() -> None:
    clock = FakeClock()
    limiter = RateLimiter(limit=3, window_seconds=60, clock=clock)
    assert [limiter.hit("1.2.3.4") for _ in range(3)] == [None, None, None]

    clock.now += 20
    assert limiter.hit("1.2.3.4") == 40  # the first request stops counting 60 s after it was made


def test_requests_stop_counting_after_the_window() -> None:
    clock = FakeClock()
    limiter = RateLimiter(limit=1, window_seconds=60, clock=clock)
    assert limiter.hit("1.2.3.4") is None
    assert limiter.hit("1.2.3.4") is not None
    clock.now += 60
    assert limiter.hit("1.2.3.4") is None


def test_each_visitor_has_their_own_limit() -> None:
    limiter = RateLimiter(limit=1, window_seconds=60, clock=FakeClock())
    assert limiter.hit("1.2.3.4") is None
    assert limiter.hit("5.6.7.8") is None
    assert limiter.hit("1.2.3.4") is not None


def test_refused_requests_dont_count() -> None:
    clock = FakeClock()
    limiter = RateLimiter(limit=1, window_seconds=60, clock=clock)
    limiter.hit("1.2.3.4")
    for _ in range(5):
        clock.now += 10
        limiter.hit("1.2.3.4")  # refused, so it doesn't push the wait back
    clock.now += 10
    assert limiter.hit("1.2.3.4") is None
