"""Step 1, resolving (app/extract/resolve.py).

Checking queries (the same rules as parseQuery() in utils.js), telling
which site a web address belongs to, and choosing a company's official
website from search results.
"""

import httpx2
import pytest
from pydantic import SecretStr

from app.extract.resolve import (
    MAX_QUERY_LENGTH,
    QueryError,
    SiteNotFound,
    choose_official_site,
    find_official_site,
    main_label,
    name_match,
    parse_query,
    public_host,
    same_site,
    site_domain,
)
from app.tinyfish.client import TinyFishClient
from app.tinyfish.search import SearchResult


@pytest.mark.parametrize(
    ("raw", "text"),
    [
        ("Duolingo", "Duolingo"),
        ("  Ben  &  Jerry's ", "Ben & Jerry's"),
        ("L'Oréal", "L'Oréal"),
        ("Yahoo!", "Yahoo!"),
        ("Marks & Spencer", "Marks & Spencer"),
        ("St. John's", "St. John's"),  # a dot, but not a domain
        ("3M", "3M"),
        ("任天堂", "任天堂"),
    ],
)
def test_company_names(raw: str, text: str) -> None:
    query = parse_query(raw)
    assert (query.kind, query.text, query.url) == ("name", text, None)


@pytest.mark.parametrize(
    ("raw", "url", "host"),
    [
        ("stripe.com", "https://stripe.com/", "stripe.com"),
        ("www.stripe.com/about", "https://www.stripe.com/about", "www.stripe.com"),
        ("https://stripe.com/pricing?plan=pro#top", "https://stripe.com/pricing?plan=pro", "stripe.com"),
        ("HTTP://Stripe.COM:8080", "http://stripe.com:8080/", "stripe.com"),
        ("bücher.de", "https://xn--bcher-kva.de/", "xn--bcher-kva.de"),
        ("fail.invalid", "https://fail.invalid/", "fail.invalid"),
    ],
)
def test_web_addresses(raw: str, url: str, host: str) -> None:
    query = parse_query(raw)
    assert (query.kind, query.text, query.url, query.host) == ("url", raw.strip(), url, host)


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("", "Enter a company name or a website address."),
        ("   ", "Enter a company name or a website address."),
        ("x" * (MAX_QUERY_LENGTH + 1), "Keep it under 200 characters: one company name or one URL."),
        ("<script>", "Company names can use letters, numbers, spaces and & . , ' ! + ( ) - only."),
        ("localhost:3000", "Company names can use letters, numbers, spaces and & . , ' ! + ( ) - only."),
        ("javascript:alert(1)", "Only website links that start with http:// or https:// work."),
        ("ftp://files.example.com", "Only website links that start with http:// or https:// work."),
        ("https://user:secret@stripe.com", "Remove the username or password from the link."),
        ("http://intranet", "Use a public website address, like stripe.com."),
        ("http://127.0.0.1/admin", "Use a public website address, like stripe.com."),
        ("http://192.168.1.10", "Use a public website address, like stripe.com."),
        ("printer.local", "Use a public website address, like stripe.com."),
        ("https://exa mple.com", "That doesn’t look like a valid web address. Try something like stripe.com."),
        ("https://stripe.com:99999", "That doesn’t look like a valid web address. Try something like stripe.com."),
        ("https://stripe.com/\x00", "That doesn’t look like a valid web address. Try something like stripe.com."),
    ],
)
def test_refused_queries(raw: str, message: str) -> None:
    with pytest.raises(QueryError) as caught:
        parse_query(raw)
    assert caught.value.message == message


# --- Which site an address belongs to ---------------------------------------


@pytest.mark.parametrize(
    ("host", "domain", "label"),
    [
        ("www.patagonia.com", "patagonia.com", "patagonia"),
        ("wornwear.patagonia.com", "patagonia.com", "patagonia"),
        ("www.bbc.co.uk", "bbc.co.uk", "bbc"),
        ("shop.example.com.au", "example.com.au", "example"),
        ("monzo.com", "monzo.com", "monzo"),
        ("notion.so", "notion.so", "notion"),
        ("acme.myshopify.com", "acme.myshopify.com", "acme"),
        ("www.acme.github.io", "acme.github.io", "acme"),
    ],
)
def test_site_domain_and_main_label(host: str, domain: str, label: str) -> None:
    assert (site_domain(host), main_label(host)) == (domain, label)


def test_same_site() -> None:
    assert same_site("stripe.com", "stripe.com")
    assert same_site("blog.stripe.com", "stripe.com")
    assert not same_site("notstripe.com", "stripe.com")
    assert not same_site("max.com", "x.com")


def test_public_host() -> None:
    assert public_host("https://www.Patagonia.com/home/") == "www.patagonia.com"
    assert public_host("www.patagonia.com") is None  # search results always have a scheme
    assert public_host("javascript:alert(1)") is None
    assert public_host("http://10.0.0.1/") is None


# --- Choosing the official website -------------------------------------------


@pytest.mark.parametrize(
    ("name", "label", "score"),
    [
        ("Patagonia", "patagonia", 1.0),
        ("Marks & Spencer", "marksandspencer", 1.0),
        ("L'Oréal", "loreal", 1.0),
        ("Coca-Cola", "coca-cola", 1.0),
        ("Ben & Jerry's", "benjerry", 0.8),
        ("The North Face", "thenorthface", 0.8),
        ("Monzo Bank Ltd", "monzo", 0.8),
        ("Ben and Jerry", "benjerry", 0.7),
        ("Tate Gallery", "tate-modern", 0.4),
        ("Notion Labs Inc", "makenotion", 0.4),
        ("Patagonia", "wikipedia", 0.0),
        ("任天堂", "nintendo", 0.0),
        ("Go", "google", 0.0),
    ],
)
def test_name_match(name: str, label: str, score: float) -> None:
    assert name_match(name, label) == score


def result(position: int, url: str) -> SearchResult:
    return SearchResult(position=position, url=url, title=f"Result {position}")


def test_the_brands_own_homepage_beats_encyclopedias_and_social_sites() -> None:
    results = [
        result(1, "https://en.wikipedia.org/wiki/Patagonia,_Inc."),
        result(2, "https://www.instagram.com/patagonia/"),
        result(3, "https://wornwear.patagonia.com/"),
        result(4, "https://www.patagonia.com/home/"),
        result(5, "https://www.patagonia.com/shop/web-specials"),
    ]
    site = choose_official_site("Patagonia", results)
    assert site is not None
    assert (site.url, site.host, site.name_matches) == ("https://www.patagonia.com/", "www.patagonia.com", True)
    assert site.result.position == 4


def test_a_site_that_is_the_name_searched_for_is_allowed() -> None:
    site = choose_official_site("LinkedIn", [result(1, "https://www.linkedin.com/")])
    assert site is not None and site.host == "www.linkedin.com"


def test_without_a_name_match_the_top_result_is_chosen_but_flagged() -> None:
    results = [result(1, "https://www.nintendo.com/us/"), result(2, "https://www.nintendo.co.jp/")]
    site = choose_official_site("任天堂", results)
    assert site is not None
    assert (site.host, site.name_matches) == ("www.nintendo.com", False)


def test_nothing_usable_gives_none() -> None:
    results = [result(1, "https://en.wikipedia.org/wiki/Acme"), result(2, "ftp://acme.example/")]
    assert choose_official_site("Acme", results) is None
    assert choose_official_site("Acme", []) is None


@pytest.mark.anyio
async def test_find_official_site_asks_search_to_leave_out_other_sites() -> None:
    seen: list[httpx2.Request] = []

    def fake_search(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        if request.url.params["query"] == "Nobody Knows Co":
            return httpx2.Response(200, json={"results": [{"position": 1, "url": "https://en.wikipedia.org/wiki/X"}]})
        return httpx2.Response(200, json={"results": [{"position": 1, "url": "https://www.linkedin.com/"}]})

    client = TinyFishClient(SecretStr("test-key"), httpx2.AsyncClient(transport=httpx2.MockTransport(fake_search)))

    site = await find_official_site(client, "LinkedIn")
    assert site.url == "https://www.linkedin.com/"
    excluded = seen[0].url.params["exclude_domains"].split(",")
    assert "wikipedia.org" in excluded
    assert "linkedin.com" not in excluded  # the site searched for isn't left out
    assert "LinkedIn" in seen[0].url.params["purpose"]

    with pytest.raises(SiteNotFound):
        await find_official_site(client, "Nobody Knows Co")
