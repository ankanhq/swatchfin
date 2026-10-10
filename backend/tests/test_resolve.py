"""Checking queries (app/extract/resolve.py): the same rules as parseQuery() in utils.js."""

import pytest

from app.extract.resolve import MAX_QUERY_LENGTH, QueryError, parse_query


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
