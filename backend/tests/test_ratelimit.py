"""Rate limits (app/ratelimit.py), with a fake clock instead of waiting."""

from datetime import UTC, datetime

from app.ratelimit import DailyLimit, RateLimiter, Visitors, wait_words


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


def test_give_back_uncounts_the_latest_request() -> None:
    limiter = RateLimiter(limit=1, window_seconds=60, clock=FakeClock())
    assert limiter.hit("1.2.3.4") is None
    limiter.give_back("1.2.3.4")
    assert limiter.hit("1.2.3.4") is None
    limiter.give_back("5.6.7.8")  # a visitor with nothing to give back is fine


class FakeDay:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 12, 17, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


def test_daily_limit_counts_to_the_limit_then_waits_for_midnight_utc() -> None:
    day = FakeDay()
    limit = DailyLimit(2, clock=day)
    assert [limit.take(), limit.take()] == [None, None]
    assert limit.take() == 7 * 60 * 60  # 17:00 -> midnight UTC

    limit.give_back()
    assert limit.take() is None
    assert limit.used == 2

    day.now = datetime(2026, 10, 13, 0, 0, 1, tzinfo=UTC)
    assert limit.used == 0
    assert limit.take() is None


def test_daily_limit_starts_from_the_guides_made_before_a_restart() -> None:
    limit = DailyLimit(3, clock=FakeDay())
    limit.start_from(2)
    assert limit.take() is None
    assert limit.take() is not None
    limit.start_from(1)  # never lowers the count
    assert limit.used == 3
    for _ in range(5):
        limit.give_back()
    assert limit.used == 0


def test_on_your_computer_the_visitor_is_whoever_connects() -> None:
    visitors = Visitors(proxy_hops=0)
    assert visitors.address("127.0.0.1", "203.0.113.7") == "127.0.0.1"
    assert visitors.address(None, None) == "unknown"


def test_behind_a_proxy_a_made_up_address_is_ignored() -> None:
    visitors = Visitors(proxy_hops=1)
    # The proxy adds the real address at the end; the visitor wrote the first one.
    assert visitors.address("10.0.0.5", "203.0.113.7, 198.51.100.20") == "198.51.100.20"
    assert visitors.address("10.0.0.5", "198.51.100.20") == "198.51.100.20"
    # No header: the connection is all there is.
    assert visitors.address("10.0.0.5", None) == "10.0.0.5"


def test_two_proxies_read_the_entry_two_from_the_end() -> None:
    visitors = Visitors(proxy_hops=2)
    assert visitors.address("10.0.0.5", "203.0.113.7, 198.51.100.20, 172.70.1.1") == "198.51.100.20"
    # Fewer entries than proxies: the first is the best there is.
    assert visitors.address("10.0.0.5", "198.51.100.20") == "198.51.100.20"


def test_wait_words() -> None:
    assert wait_words(0.2) == "1 second"
    assert wait_words(42) == "42 seconds"
    assert wait_words(600) == "10 minutes"
    assert wait_words(3599) == "60 minutes"
    assert wait_words(3600) == "1 hour"
    assert wait_words(7 * 60 * 60 - 30) == "7 hours"
