"""Reusing a recent guide (app/reuse.py): which searches count as the same, and for how long."""

from datetime import UTC, datetime, timedelta

from app.extract.resolve import parse_query
from app.reuse import RecentGuides, ago, query_key, site_key


def test_the_same_site_written_differently_has_one_key() -> None:
    same = ["stripe.com", "https://stripe.com", "https://www.stripe.com/", "http://WWW.Stripe.com", "stripe.com/#top"]
    assert {query_key(parse_query(text)) for text in same} == {"site:stripe.com"}


def test_different_pages_ports_and_languages_are_different_sites() -> None:
    assert site_key("https://www.ikea.com/de/") == "site:ikea.com/de"
    assert site_key("https://www.ikea.com/de/?lang=en") == "site:ikea.com/de?lang=en"
    assert site_key("https://example.com:8443/") == "site:example.com:8443"
    assert site_key("https://shop.example.com/") == "site:shop.example.com"


def test_company_names_match_whatever_their_capitals() -> None:
    assert query_key(parse_query("Duolingo")) == query_key(parse_query("  duolingo ")) == "name:duolingo"
    assert query_key(parse_query("Ben & Jerry's")) == "name:ben & jerry's"
    # A name and a web address never share a key: the pipeline matches them by site once Search has found it.
    assert query_key(parse_query("Stripe")) != query_key(parse_query("stripe.com"))


def test_ago() -> None:
    now = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)
    assert ago(now - timedelta(minutes=20), now) == "a few minutes ago"
    assert ago(now - timedelta(minutes=61), now) == "1 hour ago"
    assert ago(now - timedelta(hours=23, minutes=59), now) == "23 hours ago"


def test_a_guide_is_found_until_it_is_too_old() -> None:
    recent = RecentGuides(hours=24)
    now = datetime.now(UTC)
    recent.remember({"site:stripe.com", "name:stripe"}, "bg_new", now - timedelta(hours=23))
    recent.remember({"site:old.example"}, "bg_old", now - timedelta(hours=25))
    assert recent.find("site:stripe.com") == "bg_new"
    assert recent.find("name:stripe") == "bg_new"
    assert recent.find("site:old.example") is None
    assert recent.find("site:other.example") is None


def test_the_newer_guide_wins() -> None:
    recent = RecentGuides(hours=24)
    now = datetime.now(UTC)
    recent.remember({"site:stripe.com"}, "bg_newer", now - timedelta(hours=1))
    recent.remember({"site:stripe.com"}, "bg_older", now - timedelta(hours=5))
    assert recent.find("site:stripe.com") == "bg_newer"
    recent.forget("site:stripe.com")
    assert recent.find("site:stripe.com") is None


def test_zero_hours_turns_reuse_off() -> None:
    recent = RecentGuides(hours=0)
    recent.remember({"site:stripe.com"}, "bg_new", datetime.now(UTC))
    assert recent.find("site:stripe.com") is None
