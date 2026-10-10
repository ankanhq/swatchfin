"""The seven steps that make a guide (CLAUDE.md, section 5).

MOCK: in Phase 4 every step is a placeholder, and nothing reads a website.
- Each step waits a moment and says, in its detail line, that live reading
  isn't connected yet.
- TinyFish usage stays at 0, because no TinyFish calls are made.
- Every job ends with the sample guide for Northwind Roasters, a fictional
  brand (frontend/mock/MOCK_northwind-roasters.json), which the guide page
  labels as mock data.
- A web address ending in .invalid (a domain ending reserved so that it
  never exists) fails on purpose at "Reading the homepage", so the failed
  view can be checked. The message says so.
Phases 5–7 replace the placeholders one step at a time.

Also here: the sample jobs "mock" and "mock-partial", finished jobs that
show the two sample guides. The About and 404 pages link to the first.
"""

import asyncio
import json
from collections.abc import Callable
from pathlib import Path

from app.config import Settings
from app.extract.resolve import ParsedQuery
from app.jobs import JobRun, Pipeline, StepFailed
from app.schemas import STEP_NAMES, BrandGuide, Job, Step

PLACEHOLDER_DETAIL = "Placeholder: live reading with TinyFish isn’t connected yet."
SKIPPED_SEARCH_DETAIL = "You gave a web address, so no search was needed."

# MOCK: sample job ID -> sample guide file in frontend/mock.
SAMPLE_GUIDES = {
    "mock": "MOCK_northwind-roasters.json",
    "mock-partial": "MOCK_northwind-roasters-partial.json",
}

# MOCK: addresses ending in this fail on purpose (see above).
FAIL_ON_PURPOSE_SUFFIX = ".invalid"


def placeholder_pipeline(settings: Settings) -> Pipeline:
    """MOCK: the stand-in pipeline for Phase 4 (see the top of this file)."""
    mock_dir = settings.frontend_dir / "mock"
    step_seconds = settings.placeholder_step_seconds

    async def run(job: JobRun, query: ParsedQuery) -> BrandGuide:
        for name in STEP_NAMES:
            if name == "resolving" and query.kind == "url":
                job.skip(name, SKIPPED_SEARCH_DETAIL)
                continue

            async with job.step(name) as step:
                await asyncio.sleep(step_seconds)
                if name == "reading_homepage" and (query.host or "").endswith(FAIL_ON_PURPOSE_SUFFIX):
                    raise StepFailed(
                        title="The homepage couldn’t be read",
                        message="Live reading isn’t connected yet, and addresses ending in .invalid stop here on "
                        "purpose, so this view can be checked. No website was read.",
                        detail="Stopped on purpose: a .invalid address",
                    )
                step.detail = PLACEHOLDER_DETAIL

        return await asyncio.to_thread(load_guide, mock_dir / SAMPLE_GUIDES["mock"])

    return run


def sample_job_finder(settings: Settings) -> Callable[[str], Job | None]:
    """MOCK: returns a function that finds the sample jobs by ID (for JobManager)."""
    mock_dir = settings.frontend_dir / "mock"

    def find(job_id: str) -> Job | None:
        file_name = SAMPLE_GUIDES.get(job_id)
        if file_name is None:
            return None
        guide = load_guide(mock_dir / file_name)
        # A job that finished before anyone asked: every step done, and the guide.
        return Job(
            id=job_id,
            status="complete",
            query=guide.query,
            started_at=None,
            steps=[Step(name=name, status="done") for name in STEP_NAMES],
            tinyfish_usage=guide.tinyfish_usage,
            guide=guide,
        )

    return find


def load_guide(path: Path) -> BrandGuide:
    """Reads a guide file and checks it against the schema."""
    return BrandGuide.model_validate(json.loads(path.read_text(encoding="utf-8")))
