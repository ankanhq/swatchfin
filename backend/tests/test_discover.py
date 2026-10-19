"""Steps 3 and 4: choosing the brand's pages (app/extract/discover.py) and reading them (app/extract/pages.py)."""

import json
from typing import Any
from urllib.parse import urlsplit

import httpx2
import pytest
from pydantic import SecretStr

from app.extract.discover import MAX_PAGES, ChosenPage, choose_pages, discover_pages, kind_labels
from app.extract.homepage import Homepage, PageLink
from app.extract.pages import read_pages
from app.tinyfish.client import TinyFishClient
from app.tinyfish.search import SearchResult

SITE = "https://www.larkspur.example"


def homepage(*links: PageLink, url: str = f"{SITE}/", language: str = "en") -> Homepage:
    return Homepage(
        requested_url=f"{SITE}/", url=url, host="www.larkspur.example", language=language, links=list(links)
    )


def link(path: str, text: str = "", place: str = "top") -> PageLink:
    url = path if path.startswith("http") else f"{SITE}{path}"
    return PageLink(url=url, text=text, place=place)  # type: ignore[arg-type]


def chosen_urls(home: Homepage, results: list[SearchResult] | None = None) -> list[str]:
    return [page.url for page in choose_pages(home, results or [])]


def test_kinds_come_from_the_address_and_the_link_words() -> None:
    pages = choose_pages(
        homepage(
            link("/about-us/", "Our story"),
            link("/our-mission", "Mission"),
            link("https://careers.larkspur.example/", "Join us", "footer"),
            link("/newsroom/", "Newsroom", "footer"),
            link("/journal/", "Journal"),
            link("/pricing", "Plans"),
            link("/shop/teaware", "Teaware"),
        ),
        [],
    )
    assert {page.url: page.kind for page in pages} == {
        f"{SITE}/about-us/": "about",
        f"{SITE}/our-mission": "mission",
        "https://careers.larkspur.example/": "careers",
        f"{SITE}/newsroom/": "press",
        f"{SITE}/journal/": "blog",
        f"{SITE}/pricing": "pricing",
    }
    assert kind_labels(pages) == ["About", "Mission and values", "Careers", "Press", "Blog", "Pricing"]
    assert all(page.origin == "link" for page in pages)


def test_a_newsroom_beats_a_subdomain_that_only_shares_the_word_press() -> None:
    # Like stripe.com: "Stripe Press" (press.stripe.com) publishes books; the press room is "Newsroom".
    pages = choose_pages(
        homepage(
            link("https://press.larkspur.example/", "Larkspur Press", "footer"),
            link("/newsroom", "Newsroom", "footer"),
        ),
        [],
    )
    assert [page.url for page in pages] == [f"{SITE}/newsroom"]


@pytest.mark.parametrize(
    ("path", "text"),
    [("/press-releases", "Press releases"), ("/media-centre", "Media centre"), ("/company/pressroom", "")],
)
def test_other_press_room_names_count_as_strongly(path: str, text: str) -> None:
    pages = choose_pages(homepage(link("https://press.larkspur.example/", "Press", "footer"), link(path, text)), [])
    assert [page.url for page in pages] == [f"{SITE}{path}"]


def test_most_useful_kinds_come_first_and_each_kind_is_limited() -> None:
    links = [link(f"/careers/{n}", "Careers") for n in range(5)] + [
        link("/careers", "Careers"),
        link("/brand", "Brand assets", "footer"),
        link("/about", "About"),
    ]
    pages = choose_pages(homepage(*links), [])
    assert [page.kind for page in pages] == ["brand", "about", "careers"]
    assert pages[2].url == f"{SITE}/careers"  # the Careers page, not one job advert


def test_no_more_than_nine_pages() -> None:
    kinds = ["about", "company", "mission", "values", "products", "careers", "press", "blog", "pricing", "brand"]
    pages = choose_pages(homepage(*[link(f"/{kind}", kind.title()) for kind in kinds]), [])
    assert len(pages) == MAX_PAGES


@pytest.mark.parametrize(
    "path",
    [
        "https://www.instagram.com/larkspur/about",  # another site
        "https://help.larkspur.example/about",  # a help desk
        "https://investors.larkspur.example/about",  # investor relations
        "/",  # the homepage itself
        "/account/about",
        "/privacy-policy",
        "/login?next=/about",
        "/about/brand-book.pdf",
        "/de/ueber-uns/about",  # the German copy of the site
        "/fr-fr/about",
        # Other people's words: Notion's template gallery, Figma's community files, customer stories.
        "/templates/category/free-company-mission-vision-templates",
        "/community/website-templates/about-us-page",
        "/customers/multiverse",
        "/case-studies/acme",
    ],
)
def test_pages_that_are_left_out(path: str) -> None:
    assert chosen_urls(homepage(link(path, "About"))) == []


@pytest.mark.parametrize(
    "path",
    [
        "/research/about",  # "research" is not "search"
        "/accountability",  # nor "account"
        "/us/press/123",  # "us" is a country here, not a language
        "/gb/en/about",  # the English copy for Britain
    ],
)
def test_pages_that_are_kept(path: str) -> None:
    home = homepage(link(path, "About" if "accountability" not in path else "Our impact"))
    assert len(chosen_urls(home)) == 1


@pytest.mark.parametrize(
    "url",
    [
        "https://community.larkspur.example/about",
        "https://techcommunity.larkspur.example/t/about",  # like techcommunity.microsoft.com
        "https://en.community.larkspur.example/about",  # the forum is the second part
        "https://communities.larkspur.example/about",
        "https://forums.larkspur.example/about",
        "https://devforum.larkspur.example/about",
        "https://discuss.larkspur.example/about",
        "https://discussions.larkspur.example/about",
        "https://answers.larkspur.example/about",  # like answers.microsoft.com
        "https://eu.help.larkspur.example/about",  # a help desk behind a region
        f"{SITE}/forums/about",
        f"{SITE}/communities/about",
        f"{SITE}/discussions/about",
    ],
)
def test_forums_are_left_out(url: str) -> None:
    assert chosen_urls(homepage(link(url, "About"))) == []


@pytest.mark.parametrize(
    "url",
    [
        "https://careers.larkspur.example/",
        "https://press.larkspur.example/",
        "https://commerce.larkspur.example/about",  # "commerce" is not "community"
        "https://uk.larkspur.example/about",
    ],
)
def test_subdomains_that_are_kept(url: str) -> None:
    assert len(chosen_urls(homepage(link(url, "About")))) == 1


def test_a_forum_found_by_search_is_left_out() -> None:
    """Microsoft's site-limited search for its About page finds its forum before its own pages."""
    home = Homepage(
        requested_url="https://www.microsoft.com/", url="https://www.microsoft.com/en-us", host="www.microsoft.com"
    )
    results = [
        SearchResult(
            position=1, url="https://techcommunity.microsoft.com/about", title="About Microsoft Tech Community"
        ),
        SearchResult(position=2, url="https://answers.microsoft.com/en-us/page/about", title="About Microsoft Q&A"),
        SearchResult(position=3, url="https://www.microsoft.com/en-us/about", title="About Microsoft"),
    ]
    assert chosen_urls(home, results) == ["https://www.microsoft.com/en-us/about"]


def test_on_a_site_in_one_language_its_own_copies_are_kept() -> None:
    home = homepage(link("/en-gb/about", "About"), link("/fr-fr/about", "About"), url=f"{SITE}/en-gb/")
    assert chosen_urls(home) == [f"{SITE}/en-gb/about"]


def test_a_bare_logo_in_a_link_is_not_the_brand_assets_page() -> None:
    # On nike.com, "ACG Logo" leads to a range of clothes.
    assert chosen_urls(homepage(link("/w/aja-wilson-4yj6f", "ACG Logo"))) == []
    assert [page.kind for page in choose_pages(homepage(link("/downloads", "Download our logos")), [])] == ["brand"]


def test_the_last_part_of_the_address_names_the_page() -> None:
    # Nike's logo page sits in its newsroom; a careers page under /about is a careers page.
    logos = SearchResult(position=1, url=f"{SITE}/newsroom/collections/larkspur-logos", title="Larkspur Logos")
    assert [page.kind for page in choose_pages(homepage(), [logos])] == ["brand"]
    assert [page.kind for page in choose_pages(homepage(link("/about/careers", "")), [])] == ["careers"]


def test_product_pages_need_the_word_in_their_address() -> None:
    home = homepage(link("/recall-of-infant-set", "Infant Product Recall"), link("/products", "Shop all"))
    assert chosen_urls(home) == [f"{SITE}/products"]


def test_about_in_a_title_counts_only_as_a_heading() -> None:
    results = [
        SearchResult(position=1, url=f"{SITE}/hub/design", title="Articles about design"),
        SearchResult(position=2, url="https://about.larkspur.example/", title="About Larkspur Tea"),
    ]
    assert chosen_urls(homepage(), results) == ["https://about.larkspur.example/"]


def test_a_browsing_history_page_is_not_the_company_history() -> None:
    # Like amazon.in: "Browsing History" links to /gp/history.
    assert chosen_urls(homepage(link("/gp/history", "Browsing History", "footer"))) == []
    assert chosen_urls(homepage(link("/history", "History", "footer"))) == [f"{SITE}/history"]
    assert chosen_urls(homepage(link("/company-history/", "Since 1973", "footer"))) == [f"{SITE}/company-history/"]


@pytest.mark.parametrize(
    ("path", "title"),
    [
        # Like amazon.in: the brand-guidelines search found a Kindle ebook about press kits.
        ("/Mastering-Perfect-Press-Kit-Relationships-ebook/dp/B0DR2BZTWP", "Mastering the Perfect Press Kit eBook"),
        ("/dp/B0DR2BZTWP", "Mastering the Perfect Press Kit"),
        ("/Mission-Impossible-Dead-Reckoning/dp/B0C8L3VQ2K", "Mission: Impossible – Dead Reckoning"),
        ("/Writing-Press-Releases-Guide/dp/B09XQ4M2T7", "Writing Press Releases: A Guide"),
        ("/itm/brand-guidelines-book/226512345678", "Brand guidelines book"),  # an auction
        ("/listing/1234567890/logo-design-brand-kit", "Logo design brand kit"),  # a shop's listing
    ],
)
def test_a_title_alone_cant_make_a_numbered_listing_one_of_the_brands_pages(path: str, title: str) -> None:
    assert chosen_urls(homepage(), [SearchResult(position=1, url=f"{SITE}{path}", title=title)]) == []
    # From the homepage's links too: a shop's homepage links to its products.
    assert chosen_urls(homepage(link(path, title))) == []


@pytest.mark.parametrize(
    ("path", "title", "kind"),
    [
        ("/media-resources", "Press kit", "brand"),
        ("/company/media-resources", "Press kit", "about"),  # "/company" is an About folder
        # Numbered, but its address says what it is.
        ("/newsroom/2024/123456/press-kit", "Larkspur press kit", "brand"),
        ("/about/12345678", "About Larkspur", "about"),
    ],
)
def test_real_press_kit_and_about_pages_are_kept(path: str, title: str, kind: str) -> None:
    pages = choose_pages(homepage(), [SearchResult(position=1, url=f"{SITE}{path}", title=title)])
    assert [(page.url, page.kind) for page in pages] == [(f"{SITE}{path}", kind)]


def test_search_results_join_the_links_and_query_strings_are_dropped() -> None:
    results = [
        SearchResult(position=1, url=f"{SITE}/brand-guidelines?utm_source=search", title="Larkspur brand guidelines"),
        SearchResult(position=2, url=f"{SITE}/about/", title="About Larkspur"),
    ]
    pages = choose_pages(homepage(link("/about", "About")), results)
    assert [(page.url, page.kind, page.origin) for page in pages] == [
        (f"{SITE}/brand-guidelines", "brand", "search"),
        (f"{SITE}/about", "about", "link"),  # the same page as /about/, and the homepage linked to it
    ]


def fake_tinyfish(answer: Any) -> tuple[TinyFishClient, list[httpx2.Request]]:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json=answer(request) if callable(answer) else answer)

    http = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    return TinyFishClient(SecretStr("test-key"), http), seen


@pytest.mark.anyio
async def test_a_homepage_with_enough_links_needs_one_search() -> None:
    client, seen = fake_tinyfish({"results": [{"position": 1, "url": f"{SITE}/press-kit", "title": "Press kit"}]})
    home = homepage(link("/about", "About"), link("/careers", "Careers"), link("/press", "Press"))
    discovery = await discover_pages(client, home, "Larkspur Tea")

    assert discovery.search_calls == 1
    params = seen[0].url.params
    assert (params["query"], params["include_domains"]) == (
        "Larkspur Tea brand guidelines logo press kit",
        "larkspur.example",
    )
    assert discovery.pages[0].url == f"{SITE}/press-kit"
    assert discovery.found_by_search == 1


@pytest.mark.anyio
async def test_a_homepage_without_links_gets_a_second_search() -> None:
    def answer(request: httpx2.Request) -> dict[str, Any]:
        if "about us" in request.url.params["query"]:
            return {"results": [{"position": 1, "url": "https://careers.larkspur.example/", "title": "Careers"}]}
        return {"results": []}

    client, seen = fake_tinyfish(answer)
    discovery = await discover_pages(client, homepage(), "Larkspur Tea")

    assert discovery.search_calls == 2
    assert seen[1].url.params["query"] == "Larkspur Tea about us, mission, careers, press"
    assert [page.url for page in discovery.pages] == ["https://careers.larkspur.example/"]


@pytest.mark.anyio
async def test_read_pages_keeps_good_pages_and_says_why_others_were_skipped() -> None:
    long_text = "Larkspur Tea blends loose-leaf tea in small batches. " * 10

    def answer(request: httpx2.Request) -> dict[str, Any]:
        body = json.loads(request.content)
        assert (body["format"], body["ttl"], body["per_url_timeout_ms"]) == ("markdown", 0, 30_000)
        return {
            "results": [
                {"url": f"{SITE}/about", "final_url": f"{SITE}/about/", "title": "About", "text": long_text},
                {"url": f"{SITE}/careers", "final_url": "https://jobs.otherboard.example/larkspur", "text": long_text},
                {"url": f"{SITE}/blog", "final_url": f"{SITE}/", "text": long_text},
                {"url": f"{SITE}/mission", "final_url": f"{SITE}/mission", "text": "Menu\n\nFooter"},
            ],
            "errors": [{"url": f"{SITE}/press", "error": "bot_blocked"}],
        }

    client, _seen = fake_tinyfish(answer)
    home = homepage(
        link("/about", "About"), link("/careers", "Careers"), link("/blog", "Blog"),
        link("/mission", "Mission"), link("/press", "Press"),
    )  # fmt: skip
    result = await read_pages(client, home, choose_pages(home, []))

    assert [(page.url, page.kind, page.title) for page in result.pages] == [(f"{SITE}/about/", "about", "About")]
    assert {skipped.url: skipped.reason for skipped in result.skipped} == {
        f"{SITE}/careers": "it redirected to another website",
        f"{SITE}/blog": "it led to a page that was already read",
        f"{SITE}/mission": "it had almost no text",
        f"{SITE}/press": "the site blocked automated reading",
    }
    # Step 5's browser may read the empty and the blocked page; a redirect or a repeat it can't help.
    assert {skipped.url: (skipped.kind, skipped.retry) for skipped in result.skipped} == {
        f"{SITE}/careers": ("careers", False),
        f"{SITE}/blog": ("blog", False),
        f"{SITE}/mission": ("mission", True),
        f"{SITE}/press": ("press", True),
    }


@pytest.mark.anyio
async def test_a_redirect_to_another_of_the_brands_own_sites_is_followed() -> None:
    long_text = "Our mission is to organize the world’s information and make it universally accessible. " * 5
    google = "https://www.google.com"
    redirects = {
        "/about": "https://about.google/",  # the brand's own domain ending
        "/careers": "https://www.google.co.in/about/careers/",  # the same name in another country
        "/press": "https://blog.google/press/",
        "/mission": "https://about.google/signin?continue=mission",  # a sign-in page: not read
        "/journal": "https://blog.google.evil.example/journal",  # not the brand
        "/stories": "http://127.0.0.1/stories",  # not a public address
    }

    def answer(_request: httpx2.Request) -> dict[str, Any]:
        return {
            "results": [
                {"url": f"{google}{path}", "final_url": final, "title": path[1:].title(), "text": long_text}
                for path, final in redirects.items()
            ]
        }

    client, _seen = fake_tinyfish(answer)
    home = Homepage(requested_url=f"{google}/", url=f"{google}/", host="www.google.com", language="en")
    chosen = [ChosenPage(f"{google}{path}", "about", path[1:], "link", 1.0) for path in redirects]
    result = await read_pages(client, home, chosen)

    assert [page.url for page in result.pages] == [
        "https://about.google/",
        "https://www.google.co.in/about/careers/",
        "https://blog.google/press/",
    ]
    assert {skipped.url: (skipped.reason, skipped.elsewhere) for skipped in result.skipped} == {
        f"{google}/mission": ("it redirected to a page Swatchfin doesn’t read, such as a sign-in or legal page", None),
        f"{google}/journal": ("it redirected to another website", "blog.google.evil.example"),
        f"{google}/stories": ("it redirected to another website", "127.0.0.1"),
    }


def platform_home(host: str) -> Homepage:
    return Homepage(requested_url=f"https://{host}/", url=f"https://{host}/", host=host, language="en")


def test_on_a_platform_other_peoples_pages_are_left_out() -> None:
    # What a site-limited search for "X about us, mission, careers, press" really found (19 October 2026).
    results = [
        SearchResult(position=1, url="https://x.com/USUN", title="US Mission to the UN (@USUN) / X"),
        SearchResult(position=2, url="https://x.com/US2EU", title="US Mission to the EU (@US2EU) / X"),
        SearchResult(position=3, url="https://x.com/i/jf/stories/home", title="Stories / X"),
        SearchResult(position=4, url="https://about.x.com/en", title="About X"),
        SearchResult(position=5, url="https://x.com/en/about", title="About"),
        SearchResult(position=6, url="https://x.com/careers", title="Careers at X"),
    ]
    # X's own pages: on its subdomain, and on x.com when the address says what they are.
    assert sorted(chosen_urls(platform_home("x.com"), results)) == [
        "https://about.x.com/en",
        "https://x.com/careers",
        "https://x.com/en/about",
    ]


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/@SomeCreator/about",  # a channel
        "https://www.youtube.com/watch",
        "https://www.linkedin.com/company/microsoft",  # another company's page
        "https://medium.com/@someone/our-story-1a2b3c",
        "https://www.youtube.com/howyoutubeworks/our-mission/",
    ],
)
def test_on_a_platform_a_page_must_say_what_it_is_in_every_part_of_its_address(url: str) -> None:
    host = urlsplit(url).hostname or ""
    assert chosen_urls(platform_home(host), [SearchResult(position=1, url=url, title="About us")]) == []


def test_on_a_platform_its_own_sections_are_read() -> None:
    results = [
        SearchResult(position=1, url="https://www.youtube.com/about/press/", title="Press"),
        SearchResult(position=2, url="https://www.youtube.com/about/brand-resources/", title="Brand resources"),
    ]
    assert chosen_urls(platform_home("www.youtube.com"), results) == [
        "https://www.youtube.com/about/brand-resources/",
        "https://www.youtube.com/about/press/",
    ]


def test_an_ordinary_site_keeps_pages_its_title_names() -> None:
    # On a brand's own site a title still gives a kind: "/USUN" there would be the brand's page.
    results = [SearchResult(position=1, url=f"{SITE}/our-work", title="Our mission")]
    assert chosen_urls(homepage(), results) == [f"{SITE}/our-work"]


@pytest.mark.anyio
async def test_no_pages_means_no_call() -> None:
    client, seen = fake_tinyfish({"results": []})
    result = await read_pages(client, homepage(), [])
    assert (result.pages, result.skipped, seen) == ([], [], [])
