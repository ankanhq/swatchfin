"""The BrandGuide and job shapes (app/schemas.py) match what the frontend reads."""

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.schemas import STEP_NAMES, BrandGuide, Job

MOCK_DIR = Path(__file__).resolve().parents[2] / "frontend" / "mock"
MOCK_GUIDES = ["MOCK_northwind-roasters.json", "MOCK_northwind-roasters-partial.json"]


def load_mock(name: str = MOCK_GUIDES[0]) -> dict[str, Any]:
    return json.loads((MOCK_DIR / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", MOCK_GUIDES)
def test_mock_guides_fit_the_schema_exactly(name: str) -> None:
    """The frontend was built against these files. Checking them and writing
    them back out must give the same JSON, so nothing is lost or renamed."""
    raw = load_mock(name)
    guide = BrandGuide.model_validate(raw)
    assert guide.model_dump(mode="json") == raw


def test_unknown_field_is_refused() -> None:
    raw = load_mock()
    raw["colours"] = raw["colors"]  # a typo'd field name
    with pytest.raises(ValidationError):
        BrandGuide.model_validate(raw)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("colors", 0, "role"), "highlight"),  # not one of the colour roles
        (("colors", 0, "hex"), "B5532A"),  # missing the #
        (("colors", 0, "rgb"), [181, 83]),  # only two channels
        (("colors", 0, "confidence"), 1.4),  # above 1
        (("contrast", 0, "wcag"), "AA+"),
        (("typography", 0, "role"), "display"),
        (("voice", "spectrum", "formal_casual"), 101),
        (("sources", 0, "api"), "crawler"),  # not a TinyFish API
        (("schema_version",), "2.0"),
    ],
)
def test_wrong_values_are_refused(path: tuple[str | int, ...], value: object) -> None:
    raw = copy.deepcopy(load_mock())
    target: Any = raw
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValidationError):
        BrandGuide.model_validate(raw)


def test_missing_parts_can_be_null() -> None:
    """Data that couldn't be found is null (with a warning), never invented."""
    raw = load_mock()
    raw["logo"]["primary"] = None
    raw["logo"]["favicon"] = None
    raw["brand"]["description"] = None
    raw["voice"]["summary"] = None
    raw["voice"]["spectrum"] = None
    raw["messaging"]["tagline"] = None
    BrandGuide.model_validate(raw)


def test_job_with_a_guide() -> None:
    job = Job.model_validate(
        {
            "id": "bg_7f3a9c",
            "status": "complete",
            "query": "Northwind Roasters",
            "started_at": "2026-10-10T12:00:00Z",
            "steps": [{"name": name, "status": "done"} for name in STEP_NAMES],
            "tinyfish_usage": {"search_calls": 1, "fetch_urls": 6, "browser_sessions": 1},
            "error": None,
            "guide": load_mock(),
        }
    )
    assert job.guide is not None
    assert job.model_dump(mode="json")["started_at"] == "2026-10-10T12:00:00Z"


def test_job_refuses_unknown_step_or_status() -> None:
    base = {"id": "bg_1", "query": "x", "steps": [], "tinyfish_usage": {}}
    with pytest.raises(ValidationError):
        Job.model_validate({**base, "status": "cancelled"})
    with pytest.raises(ValidationError):
        Job.model_validate({**base, "status": "running", "steps": [{"name": "crawling", "status": "done"}]})
