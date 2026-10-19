"""The /api/v1 endpoints, called the way the guide page and other tools call them."""

import base64
import json
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.schemas import STEP_NAMES, BrandGuide, Job, Step, TinyFishUsage
from tests.fake_llm import FakeLLM, larkspur_draft
from tests.fake_tinyfish import TINY_PNG, FakeTinyFish, browser_page

WaitForJob = Callable[..., dict[str, Any]]

MOCK_GUIDE = Path(__file__).resolve().parents[2] / "frontend" / "mock" / "MOCK_northwind-roasters.json"


def start(client: TestClient, query: str) -> str:
    response = client.post("/api/v1/guides", json={"query": query})
    assert response.status_code == 202, response.text
    return response.json()["id"]


def test_start_then_follow_a_guide_to_the_end(client: TestClient, wait_for_job: WaitForJob) -> None:
    response = client.post("/api/v1/guides", json={"query": "  Larkspur Tea "})
    assert response.status_code == 202
    created = response.json()
    assert created["status"] == "queued"
    assert response.headers["location"] == f"/api/v1/guides/{created['id']}"

    job = wait_for_job(client, created["id"])
    assert job["status"] == "complete"
    assert job["query"] == "Larkspur Tea"
    assert job["error"] is None
    # Steps 1–5 read the (fake) site; 6 needs a language model key (the tests have none); 7 grades the contrast.
    assert [step["status"] for step in job["steps"]] == ["done"] * 5 + ["skipped", "done"]
    assert job["guide"]["id"] == created["id"]
    assert job["guide"]["brand"]["domain"] == "larkspurtea.example"
    assert job["guide"]["tinyfish_usage"] == job["tinyfish_usage"]
    assert job["started_at"].endswith("Z")


def test_a_guide_with_a_tone_of_voice(settings: Settings, wait_for_job: WaitForJob) -> None:
    fake = FakeTinyFish()
    app = create_app(settings, http=fake.http, browser=fake.driver, llm=FakeLLM(larkspur_draft()))
    with TestClient(app) as client:
        job = wait_for_job(client, start(client, "Larkspur Tea"))
    assert [step["status"] for step in job["steps"]] == ["done"] * 7
    guide = job["guide"]
    assert [trait["name"] for trait in guide["voice"]["traits"]] == ["Plain-spoken", "Rooted"]
    assert guide["voice"]["traits"][0]["evidence"] == [
        {
            "quote": "Tea blended in small batches, shipped the week it is packed.",
            "source_url": "https://www.larkspurtea.example/",
            "verified": True,
        }
    ]
    assert guide["messaging"]["tagline"]["verified"] is True
    assert guide["contrast"][0] == {"fg": "#1A1A1A", "bg": "#FFFFFF", "ratio": 17.4, "wcag": "AAA"}
    # Nothing about the model's cost goes into the guide.
    assert "cost" not in json.dumps(guide)


def test_job_status_has_the_documented_shape(make_client: Callable[..., TestClient]) -> None:
    """The exact fields the progress view on guide.html is built against (CLAUDE.md, section 7)."""
    client = make_client(tinyfish=FakeTinyFish(delay=0.5))
    job = client.get(f"/api/v1/guides/{start(client, 'larkspur.example')}").json()
    assert set(job) == {"id", "status", "query", "started_at", "steps", "tinyfish_usage", "error", "guide"}
    assert set(job["steps"][0]) == {"name", "status", "detail", "started_at", "finished_at"}
    assert job["steps"][0]["status"] == "skipped"
    assert job["tinyfish_usage"] == {"search_calls": 0, "fetch_urls": 0, "browser_sessions": 0}
    assert job["guide"] is None


def test_an_address_that_cant_be_reached_fails_at_the_homepage(client: TestClient, wait_for_job: WaitForJob) -> None:
    job = wait_for_job(client, start(client, "nothing-here.invalid"))
    assert job["status"] == "failed"
    assert job["steps"][1]["status"] == "failed"
    assert job["error"] == {
        "title": "The website couldn’t be read",
        "message": "Swatchfin couldn’t read nothing-here.invalid: the site couldn’t be reached. Check the address "
        "and try again.",
    }


def test_refused_query_says_what_to_fix(client: TestClient) -> None:
    response = client.post("/api/v1/guides", json={"query": "javascript:alert(1)"})
    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "title": "This search can’t be used",
            "message": "Only website links that start with http:// or https:// work.",
        }
    }


def test_badly_formed_requests_are_refused(client: TestClient) -> None:
    for request in (
        {"json": {}},
        {"json": {"query": 42}},
        {"json": {"query": "Duolingo", "extra": True}},
        {"content": "not json", "headers": {"Content-Type": "application/json"}},
        # A plain form post from another website can't start a guide.
        {"content": '{"query": "Duolingo"}', "headers": {"Content-Type": "text/plain"}},
    ):
        response = client.post("/api/v1/guides", **request)  # type: ignore[arg-type]
        assert response.status_code == 422, request
        assert response.json()["error"]["title"] == "Invalid request"


def test_oversized_request_is_refused(client: TestClient) -> None:
    response = client.post("/api/v1/guides", json={"query": "x" * 20_000})
    assert response.status_code == 413
    assert response.json()["error"]["title"] == "Request too large"
    assert response.headers["cache-control"] == "no-store"

    # Sent in pieces, without a length: Starlette counts the bytes, and the answer has the same shape.
    pieces = (b'{"query": "' + b"x" * 8_000 for _ in range(3))
    response = client.post("/api/v1/guides", content=pieces, headers={"Content-Type": "application/json"})
    assert response.status_code == 413
    assert response.json()["error"]["title"] == "Request too large"


def test_unknown_guide_is_404(client: TestClient) -> None:
    for job_id in ("bg_doesnotexist", "not%20an%20id", "x" * 100):
        response = client.get(f"/api/v1/guides/{job_id}")
        assert response.status_code == 404, job_id
        assert response.json()["error"]["title"] == "Guide not found"


def test_sample_guides(client: TestClient) -> None:
    job = client.get("/api/v1/guides/mock").json()
    assert job["status"] == "complete"
    assert job["guide"] == json.loads(MOCK_GUIDE.read_text(encoding="utf-8"))
    assert client.get("/api/v1/guides/mock-partial").json()["guide"]["colors"] == []


def test_production_serves_no_sample_or_mock_guide(make_client: Callable[..., TestClient], tmp_path: Path) -> None:
    # A guide marked MOCK left in the guides folder from before live generation (a run for "Duolingo"
    # once ended with the sample guide).
    leftover = Job(
        id="bg_0123456789abcdef",
        status="complete",
        query="Duolingo",
        steps=[Step(name=name, status="done") for name in STEP_NAMES],
        tinyfish_usage=TinyFishUsage(),
        guide=BrandGuide.model_validate_json(MOCK_GUIDE.read_text(encoding="utf-8")),
    )
    guides = tmp_path / "data" / "guides"
    guides.mkdir(parents=True)
    (guides / f"{leftover.id}.json").write_text(leftover.model_dump_json(), encoding="utf-8")

    client = make_client(sample_guides=False)  # the default, as in production
    for job_id in ("mock", "mock-partial", leftover.id):
        assert client.get(f"/api/v1/guides/{job_id}").status_code == 404, job_id
        assert client.get(f"/api/v1/guides/{job_id}/export?format=css").status_code == 404, job_id
    # Where sample guides are on (building the guide page, Lighthouse, tests), both are served.
    assert make_client().get(f"/api/v1/guides/{leftover.id}").status_code == 200


def test_cancel_a_running_guide(make_client: Callable[..., TestClient], wait_for_job: WaitForJob) -> None:
    client = make_client(tinyfish=FakeTinyFish(delay=5))
    job_id = start(client, "Larkspur Tea")
    wait_for_job(client, job_id, until=("running",))

    started = time.monotonic()
    response = client.delete(f"/api/v1/guides/{job_id}")
    assert response.status_code == 204
    assert response.content == b""
    assert time.monotonic() - started < 2
    assert client.get(f"/api/v1/guides/{job_id}").status_code == 404
    assert client.delete(f"/api/v1/guides/{job_id}").status_code == 404


def test_a_finished_guide_cant_be_deleted(client: TestClient, wait_for_job: WaitForJob) -> None:
    job_id = start(client, "Larkspur Tea")
    wait_for_job(client, job_id)
    for finished_id in (job_id, "mock"):
        response = client.delete(f"/api/v1/guides/{finished_id}")
        assert response.status_code == 409
        assert response.json()["error"]["title"] == "This guide is already finished"
    assert client.get(f"/api/v1/guides/{job_id}").json()["status"] == "complete"


def test_export_json(client: TestClient) -> None:
    response = client.get("/api/v1/guides/mock/export?format=json")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.headers["content-disposition"] == 'attachment; filename="MOCK_northwind-roasters-brand-guide.json"'
    expected = json.loads(MOCK_GUIDE.read_text(encoding="utf-8"))
    # The sample's logos are files next to the guide page; a downloaded guide gets their whole address.
    logo = expected["logo"]
    for asset in [logo["primary"], *logo["alternates"]]:
        asset["url"] = f"http://testserver/{asset['url']}"
    logo["favicon"] = f"http://testserver/{logo['favicon']}"
    assert response.json() == expected
    # JSON is the default format.
    assert client.get("/api/v1/guides/mock/export").status_code == 200


def test_every_export_format(client: TestClient) -> None:
    formats = {
        "json": ("application/json", "MOCK_northwind-roasters-brand-guide.json", "{"),
        "css": ("text/css; charset=utf-8", "MOCK_northwind-roasters-brand.css", '@charset "UTF-8";\n/*\n'),
        "tailwind": ("text/css; charset=utf-8", "MOCK_northwind-roasters-tailwind.css", "/*\n"),
        "tokens": ("application/design-tokens+json", "MOCK_northwind-roasters-brand.tokens.json", "{"),
        "voice": ("text/markdown; charset=utf-8", "MOCK_northwind-roasters-voice-prompt.md", "# Write in the voice"),
    }
    for export_format, (media_type, filename, start) in formats.items():
        response = client.get(f"/api/v1/guides/mock/export?format={export_format}")
        assert response.status_code == 200, export_format
        assert response.headers["content-type"] == media_type
        assert response.headers["content-disposition"] == f'attachment; filename="{filename}"'
        # Saved, never shown; and if it is opened anyway, nothing in it runs.
        assert response.headers["content-security-policy"] == "default-src 'none'; sandbox"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["cache-control"] == "no-store"
        assert response.text.startswith(start), export_format
        if export_format != "json":
            assert "MOCK sample data for a fictional brand" in response.text, export_format

    css = client.get("/api/v1/guides/mock/export?format=css").text
    assert '--brand-logo: url("http://testserver/mock/MOCK_northwind-logo.svg");' in css


def test_export_a_real_guide(client: TestClient, wait_for_job: WaitForJob) -> None:
    job = wait_for_job(client, start(client, "Larkspur Tea"))
    response = client.get(f"/api/v1/guides/{job['id']}/export")
    assert response.status_code == 200
    assert response.headers["content-disposition"] == 'attachment; filename="larkspurtea-brand-guide.json"'
    exported = response.json()
    # Inside the app a copied logo's address is a path on Swatchfin; a downloaded guide gets it in full.
    logo_path = f"/api/v1/guides/{job['id']}/logos/1.svg"
    assert job["guide"]["logo"]["primary"]["url"] == logo_path
    assert exported["logo"]["primary"]["url"] == f"http://testserver{logo_path}"
    exported["logo"]["primary"]["url"] = logo_path
    assert exported == job["guide"]

    # The other files hold the copied logo itself, so they keep working after the server forgets it,
    # and say which live site they came from.
    svg = client.get(logo_path).content
    embedded = "data:image/svg+xml;base64," + base64.b64encode(svg).decode()
    css = client.get(f"/api/v1/guides/{job['id']}/export?format=css")
    assert css.headers["content-disposition"] == 'attachment; filename="larkspurtea-brand.css"'
    assert f'--brand-logo: url("{embedded}");' in css.text
    assert "testserver" not in css.text
    assert f"Made by Swatchfin from the live site {job['guide']['brand']['url']} on " in css.text
    tokens = client.get(f"/api/v1/guides/{job['id']}/export?format=tokens").json()
    assert tokens["$extensions"]["io.github.ankanhq.swatchfin"]["logo"] == embedded
    # The tests have no language model key, so this guide has no tone of voice to write a prompt from.
    voice = client.get(f"/api/v1/guides/{job['id']}/export?format=voice")
    assert voice.status_code == 409
    assert voice.json()["error"]["title"] == "No tone of voice to export"


def test_an_export_without_its_copied_logo_file_uses_the_brands_own(
    client: TestClient, settings: Settings, wait_for_job: WaitForJob
) -> None:
    job = wait_for_job(client, start(client, "Larkspur Tea"))
    # The server forgot the copy (a restart on Render): the brand's next logo file on its own site is used.
    (settings.data_dir / "logos" / f"{job['id']}-1.svg").unlink()
    brand_file = "https://www.larkspurtea.example/apple-touch-icon.png"
    assert job["guide"]["logo"]["alternates"][0]["url"] == brand_file
    css = client.get(f"/api/v1/guides/{job['id']}/export?format=css").text
    assert f'--brand-logo: url("{brand_file}");' in css
    tokens = client.get(f"/api/v1/guides/{job['id']}/export?format=tokens").json()
    assert tokens["$extensions"]["io.github.ankanhq.swatchfin"]["logo"] == brand_file
    # The JSON export is still exactly the guide, with Swatchfin's address for the copy.
    exported = client.get(f"/api/v1/guides/{job['id']}/export?format=json").json()
    assert exported["logo"]["primary"]["url"] == f"http://testserver/api/v1/guides/{job['id']}/logos/1.svg"


def test_a_logo_copied_from_the_page_is_served_locked_down(client: TestClient, wait_for_job: WaitForJob) -> None:
    job = wait_for_job(client, start(client, "Larkspur Tea"))
    logo = job["guide"]["logo"]["primary"]
    assert (logo["method"], logo["format"]) == ("inline-svg", "svg")

    response = client.get(logo["url"])
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/svg+xml"
    assert response.headers["content-security-policy"] == "default-src 'none'; sandbox"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-disposition"] == 'inline; filename="larkspurtea-logo.svg"'
    assert response.headers["cache-control"] == "public, max-age=86400"
    assert response.text.startswith('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 24"')
    assert "<script" not in response.text and "aria-label" not in response.text


def test_a_logo_drawn_with_css_is_served_as_the_browsers_photo(
    make_client: Callable[..., TestClient], wait_for_job: WaitForJob
) -> None:
    # In the browser, the header logo is a CSS background (Amazon's sprite), not the SVG Fetch read.
    def answer(url: str, arg: Any) -> Any:
        result = browser_page(url, arg)
        if isinstance(arg, dict) and "structureSelectors" in arg:
            result["structure"] = re.sub(
                r"<svg .*?</svg>",
                '<span class="site-logo" data-sf-id="1" data-sf-background=""></span>',
                result["structure"],
                count=1,
                flags=re.S,
            )
            result["logos"] = [{"id": "1", "x": 24, "y": 18, "w": 120, "h": 24, "visible": True, "background": True}]
        return result

    tinyfish = FakeTinyFish()
    tinyfish.driver.answer = answer
    client = make_client(tinyfish=tinyfish)
    job = wait_for_job(client, start(client, "Larkspur Tea"))
    logo = job["guide"]["logo"]["primary"]
    assert (logo["method"], logo["format"], logo["url"]) == (
        "css-background",
        "png",
        f"/api/v1/guides/{job['id']}/logos/1.png",
    )
    assert tinyfish.driver.photos == ['[data-sf-id="1"]']
    assert job["guide"]["schema_version"] == "1.1"

    response = client.get(logo["url"])
    assert response.status_code == 200
    assert response.content == TINY_PNG
    assert response.headers["content-type"] == "image/png"
    assert response.headers["content-security-policy"] == "default-src 'none'; sandbox"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-disposition"] == 'inline; filename="larkspurtea-logo.png"'
    assert client.get(logo["url"].replace(".png", ".svg")).status_code == 404

    # Exports hold the photo itself.
    embedded = "data:image/png;base64," + base64.b64encode(TINY_PNG).decode()
    css = client.get(f"/api/v1/guides/{job['id']}/export?format=css").text
    assert f'--brand-logo: url("{embedded}");' in css


def test_logo_addresses_that_dont_exist(client: TestClient, wait_for_job: WaitForJob) -> None:
    job_id = wait_for_job(client, start(client, "Larkspur Tea"))["id"]
    for path in (
        f"/api/v1/guides/{job_id}/logos/2.svg",  # only one logo was copied
        f"/api/v1/guides/{job_id}/logos/6.svg",
        f"/api/v1/guides/{job_id}/logos/1.png",
        f"/api/v1/guides/{job_id}/logos/..%2F..%2Fguides%2F{job_id}.json",
        "/api/v1/guides/bg_nope/logos/1.svg",
        "/api/v1/guides/mock/logos/1.svg",
    ):
        response = client.get(path)
        assert response.status_code == 404, path
        assert response.json()["error"]["title"] in ("Logo not found", "Not found"), path


def test_export_errors(make_client: Callable[..., TestClient]) -> None:
    client = make_client(tinyfish=FakeTinyFish(delay=5))
    cases = {
        "/api/v1/guides/mock/export?format=pdf": (422, "Unknown export format"),
        # The partial sample has no colours or fonts (its browser step timed out).
        "/api/v1/guides/mock-partial/export?format=css": (409, "No colours or fonts to export"),
        "/api/v1/guides/mock-partial/export?format=tailwind": (409, "No colours or fonts to export"),
        "/api/v1/guides/mock-partial/export?format=tokens": (409, "No colours or fonts to export"),
        "/api/v1/guides/bg_nope/export": (404, "Guide not found"),
        f"/api/v1/guides/{start(client, 'Duolingo')}/export": (409, "The guide isn’t ready"),
    }
    for url, (status, title) in cases.items():
        response = client.get(url)
        assert (response.status_code, response.json()["error"]["title"]) == (status, title), url


def test_too_many_new_guides_for_one_visitor(make_client: Callable[..., TestClient]) -> None:
    client = make_client(new_guides_per_visitor_per_day=2)
    duolingo = start(client, "Duolingo")
    start(client, "Stripe")
    response = client.post("/api/v1/guides", json={"query": "Linear"})
    assert response.status_code == 429
    assert response.json()["error"] == {
        "title": "Too many guides for now",
        "message": "You can start 2 new guides a day, and you’ve reached that. Try again in 24 hours. "
        "A site that already has a guide from the last 24 hours still opens straight away.",
    }
    assert 86_000 < int(response.headers["retry-after"]) <= 86_400
    # A refused query doesn't use up the limit, a search already made still opens, and status checks still work.
    assert client.post("/api/v1/guides", json={"query": "Duolingo"}).json()["id"] == duolingo
    assert client.get("/api/v1/guides/mock").status_code == 200


def test_new_guides_a_day_for_everyone(make_client: Callable[..., TestClient]) -> None:
    client = make_client(daily_guide_limit=1, new_guides_per_visitor_per_day=2)
    start(client, "Duolingo")
    for _ in range(2):
        # Refused by today's limit, which gives the visitor's guide back: so the second try is refused
        # by today's limit again, not by the visitor's.
        response = client.post("/api/v1/guides", json={"query": "Stripe"})
        assert response.status_code == 429
        error = response.json()["error"]
        assert error["title"] == "Swatchfin has reached today’s limit"
        assert error["message"].startswith(
            "Swatchfin makes up to 1 new guides a day, and today’s have all been made. Try again in "
        )
        assert 0 < int(response.headers["retry-after"]) <= 86_400


def test_todays_guides_are_counted_at_tinyfish_when_the_server_starts(make_client: Callable[..., TestClient]) -> None:
    """A server that slept or restarted doesn't forget today's guides: each one opened a Browser session."""
    fake = FakeTinyFish()
    now = datetime.now(UTC)
    yesterday = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(hours=1)
    fake.earlier_sessions = [now.isoformat(), now.isoformat(), yesterday.isoformat()]
    client = make_client(tinyfish=fake, daily_guide_limit=3)
    start(client, "Duolingo")
    response = client.post("/api/v1/guides", json={"query": "Stripe"})
    assert response.json()["error"]["title"] == "Swatchfin has reached today’s limit"


def test_the_visitor_is_read_from_the_proxys_entry(make_client: Callable[..., TestClient]) -> None:
    """Behind Render's proxy, a made-up first X-Forwarded-For entry doesn't dodge the visitor limit."""
    client = make_client(proxy_hops=1, new_guides_per_visitor_per_day=1)

    def post(query: str, forwarded_for: str) -> int:
        response = client.post("/api/v1/guides", json={"query": query}, headers={"X-Forwarded-For": forwarded_for})
        return response.status_code

    assert post("Duolingo", "198.51.100.20") == 202
    assert post("Stripe", "203.0.113.7, 198.51.100.20") == 429
    assert post("Stripe", "198.51.100.99") == 202


def test_the_same_search_reuses_the_guide(client: TestClient, wait_for_job: WaitForJob) -> None:
    first = wait_for_job(client, start(client, "larkspurtea.example"))
    for query in ("larkspurtea.example", "https://www.larkspurtea.example/", "HTTPS://LARKSPURTEA.example"):
        response = client.post("/api/v1/guides", json={"query": query})
        assert response.status_code == 202
        assert response.json() == {"id": first["id"], "status": "complete"}


def test_a_name_for_a_site_with_a_guide_reuses_it(
    make_client: Callable[..., TestClient], wait_for_job: WaitForJob
) -> None:
    fake = FakeTinyFish()
    client = make_client(tinyfish=fake, new_guides_per_visitor_per_day=2)
    first = wait_for_job(client, start(client, "https://www.larkspurtea.example/"))
    sessions = len(fake.sessions_opened)

    reused = wait_for_job(client, start(client, "Larkspur Tea"))
    assert reused["id"] != first["id"]
    assert reused["status"] == "complete"
    assert [step["status"] for step in reused["steps"]] == ["done"] + ["skipped"] * 6
    assert reused["steps"][1]["detail"] == "Reused the guide made a few minutes ago"
    # Only the search was made: no pages read, no browser opened.
    assert reused["tinyfish_usage"] == {"search_calls": 1, "fetch_urls": 0, "browser_sessions": 0}
    assert len(fake.sessions_opened) == sessions

    guide = reused["guide"]
    assert guide["id"] == reused["id"]
    assert guide["query"] == "Larkspur Tea"
    # It keeps its own date and sources: it never claims to be fresher than it is.
    assert guide["generated_at"] == first["guide"]["generated_at"]
    assert guide["sources"] == first["guide"]["sources"]
    # Swatchfin's copy of the SVG logo was copied to the new guide.
    logo_url = guide["logo"]["primary"]["url"]
    assert logo_url == f"/api/v1/guides/{reused['id']}/logos/1.svg"
    assert client.get(logo_url).text == client.get(first["guide"]["logo"]["primary"]["url"]).text

    # The reused guide didn't count toward the visitor's 2 a day.
    start(client, "Stripe")
    # And the name now opens the reused guide straight away.
    assert start(client, "larkspur tea") == reused["id"]


def test_two_people_asking_at_once_share_a_job(
    make_client: Callable[..., TestClient], wait_for_job: WaitForJob
) -> None:
    client = make_client(tinyfish=FakeTinyFish(delay=5))
    job_id = start(client, "Larkspur Tea")
    assert start(client, "larkspur tea") == job_id
    wait_for_job(client, job_id, until=("running",))

    # One of them cancels: the other's guide carries on. When both have cancelled, it stops.
    assert client.delete(f"/api/v1/guides/{job_id}").status_code == 204
    assert client.get(f"/api/v1/guides/{job_id}").json()["status"] == "running"
    assert client.delete(f"/api/v1/guides/{job_id}").status_code == 204
    assert client.get(f"/api/v1/guides/{job_id}").status_code == 404


def test_failed_guides_and_reuse_turned_off_make_a_new_guide(
    make_client: Callable[..., TestClient], wait_for_job: WaitForJob
) -> None:
    client = make_client()
    failed = wait_for_job(client, start(client, "nothing-here.invalid"))
    assert failed["status"] == "failed"
    assert start(client, "nothing-here.invalid") != failed["id"]

    client = make_client(reuse_hours=0)
    first = wait_for_job(client, start(client, "Larkspur Tea"))
    assert start(client, "Larkspur Tea") != first["id"]


def test_too_many_requests(make_client: Callable[..., TestClient]) -> None:
    client = make_client(api_requests_per_minute=3)
    for _ in range(3):
        assert client.get("/api/v1/health").status_code == 200
    response = client.get("/api/v1/health")
    assert response.status_code == 429
    assert response.json()["error"]["title"] == "Too many requests"
    # The website itself isn't limited.
    assert client.get("/").status_code == 200


def test_busy(make_client: Callable[..., TestClient], wait_for_job: WaitForJob) -> None:
    client = make_client(tinyfish=FakeTinyFish(delay=5), max_running_jobs=1, max_waiting_jobs=0)
    wait_for_job(client, start(client, "Duolingo"), until=("running",))
    response = client.post("/api/v1/guides", json={"query": "Stripe"})
    assert response.status_code == 503
    assert response.json()["error"]["title"] == "Swatchfin is busy"
    assert response.headers["retry-after"] == "60"


def test_api_answers_are_never_cached(client: TestClient) -> None:
    for response in (client.get("/api/v1/guides/mock"), client.post("/api/v1/guides", json={"query": "x!"})):
        assert response.headers["cache-control"] == "no-store"


def test_api_docs_list_every_endpoint(client: TestClient) -> None:
    paths = client.get("/api/openapi.json").json()["paths"]
    assert set(paths) == {
        "/api/v1/guides",
        "/api/v1/guides/{job_id}",
        "/api/v1/guides/{job_id}/export",
        "/api/v1/guides/{job_id}/logos/{file_name}",
        "/api/v1/health",
    }
    assert set(paths["/api/v1/guides/{job_id}"]) == {"get", "delete"}


def test_other_websites_cant_use_the_api(client: TestClient) -> None:
    """No CORS headers: a browser lets only Swatchfin's own pages read the API."""
    other = {"Origin": "https://another-site.example"}
    assert "access-control-allow-origin" not in client.get("/api/v1/guides/mock", headers=other).headers
    preflight = client.options(
        "/api/v1/guides", headers={**other, "Access-Control-Request-Method": "DELETE"}
    )  # what a browser asks before a cross-site DELETE or JSON POST
    assert "access-control-allow-origin" not in preflight.headers
    assert "access-control-allow-methods" not in preflight.headers
