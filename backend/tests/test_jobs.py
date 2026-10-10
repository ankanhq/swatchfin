"""The job system (app/jobs.py) and the placeholder pipeline (app/pipeline.py)."""

import asyncio
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from app.config import Settings
from app.extract.resolve import ParsedQuery, parse_query
from app.jobs import GuideStore, JobManager, JobRun, JobsBusy, Pipeline, StepFailed
from app.pipeline import PLACEHOLDER_DETAIL, SKIPPED_SEARCH_DETAIL, placeholder_pipeline, sample_job_finder
from app.schemas import STEP_NAMES, BrandGuide, Job

pytestmark = pytest.mark.anyio


def make_manager(settings: Settings, pipeline: Pipeline | None = None, **overrides: Any) -> JobManager:
    options = {
        "store": GuideStore(settings.data_dir / "guides"),
        "max_running": settings.max_running_jobs,
        "max_waiting": settings.max_waiting_jobs,
        "timeout_seconds": settings.job_timeout_seconds,
        "sample_job": sample_job_finder(settings),
    }
    return JobManager(pipeline or placeholder_pipeline(settings), **{**options, **overrides})


async def finished(manager: JobManager, job_id: str) -> Job:
    """Waits until the job is complete or failed."""
    for _ in range(500):
        job = await manager.get(job_id)
        assert job is not None
        if job.status in ("complete", "failed"):
            return job
        await asyncio.sleep(0.01)
    raise AssertionError(f"job {job_id} never finished")


def statuses(job: Job) -> dict[str, str]:
    return {step.name: step.status for step in job.steps}


async def test_a_company_name_goes_through_all_seven_steps(settings: Settings) -> None:
    manager = make_manager(settings)
    job = manager.start(parse_query("Duolingo"))
    assert job.status == "queued"
    assert job.id.startswith("bg_")
    assert [step.name for step in job.steps] == list(STEP_NAMES)

    job = await finished(manager, job.id)
    assert job.status == "complete"
    assert set(statuses(job).values()) == {"done"}
    assert all(step.detail == PLACEHOLDER_DETAIL for step in job.steps)
    assert all(step.started_at and step.finished_at for step in job.steps)
    # MOCK: the placeholder makes no TinyFish calls, and ends with the sample guide.
    assert job.tinyfish_usage.model_dump() == {"search_calls": 0, "fetch_urls": 0, "browser_sessions": 0}
    assert job.guide is not None
    assert job.guide.id == "bg_MOCK_northwind"
    assert job.query == "Duolingo"
    await manager.close()


async def test_a_web_address_skips_the_search(settings: Settings) -> None:
    manager = make_manager(settings)
    job = await finished(manager, manager.start(parse_query("stripe.com")).id)
    assert job.status == "complete"
    assert job.steps[0].status == "skipped"
    assert job.steps[0].detail == SKIPPED_SEARCH_DETAIL
    await manager.close()


async def test_invalid_address_fails_on_purpose_at_the_homepage(settings: Settings) -> None:
    manager = make_manager(settings)
    job = await finished(manager, manager.start(parse_query("https://fail.invalid")).id)
    assert job.status == "failed"
    assert statuses(job) == {
        "resolving": "skipped",
        "reading_homepage": "failed",
        "discovering_pages": "pending",
        "reading_pages": "pending",
        "reading_styles": "pending",
        "analysing_voice": "pending",
        "verifying": "pending",
    }
    assert job.error is not None
    assert job.error.title == "The homepage couldn’t be read"
    assert "No website was read" in job.error.message
    assert job.guide is None
    await manager.close()


async def test_a_step_that_crashes_fails_the_job_with_a_general_message(settings: Settings) -> None:
    async def broken(job: JobRun, _query: ParsedQuery) -> BrandGuide:
        async with job.step("resolving"):
            raise RuntimeError("bug")
        raise AssertionError("not reached")

    manager = make_manager(settings, broken)
    job = await finished(manager, manager.start(parse_query("Duolingo")).id)
    assert job.status == "failed"
    assert job.steps[0].status == "failed"
    assert job.steps[0].detail == "Something went wrong in this step."
    assert job.error is not None
    assert job.error.title == "The guide couldn’t be finished"
    await manager.close()


async def test_step_failed_keeps_its_own_message(settings: Settings) -> None:
    async def blocked(job: JobRun, _query: ParsedQuery) -> BrandGuide:
        job.skip("resolving", "Not needed")
        async with job.step("reading_homepage"):
            job.count("fetch_urls")
            raise StepFailed("Blocked", "The site turned Swatchfin away.", detail="Anti-bot check")
        raise AssertionError("not reached")

    manager = make_manager(settings, blocked)
    job = await finished(manager, manager.start(parse_query("stripe.com")).id)
    assert job.error is not None
    assert (job.error.title, job.error.message) == ("Blocked", "The site turned Swatchfin away.")
    assert job.steps[1].detail == "Anti-bot check"
    assert job.tinyfish_usage.fetch_urls == 1
    await manager.close()


async def test_a_job_over_the_time_limit_fails(settings: Settings) -> None:
    async def slow(job: JobRun, _query: ParsedQuery) -> BrandGuide:
        async with job.step("resolving"):
            await asyncio.sleep(10)
        raise AssertionError("not reached")

    manager = make_manager(settings, slow, timeout_seconds=0.05)
    job = await finished(manager, manager.start(parse_query("Duolingo")).id)
    assert job.status == "failed"
    assert job.steps[0].status == "failed"
    assert job.steps[0].detail == "Stopped: this step took too long."
    assert job.error is not None
    assert job.error.title == "This guide took too long"
    await manager.close()


async def test_cancel_stops_a_running_job_and_forgets_it(make_settings: Callable[..., Settings]) -> None:
    manager = make_manager(make_settings(placeholder_step_seconds=5))
    job = manager.start(parse_query("Duolingo"))
    await asyncio.sleep(0.05)
    assert (await manager.get(job.id)).status == "running"  # type: ignore[union-attr]

    started = time.monotonic()
    assert await manager.cancel(job.id) == "cancelled"
    assert time.monotonic() - started < 1  # it didn't wait for the 5-second step
    assert await manager.get(job.id) is None
    assert await manager.cancel(job.id) == "not_found"
    await manager.close()


async def test_cancel_refuses_finished_and_unknown_jobs(settings: Settings) -> None:
    manager = make_manager(settings)
    job = await finished(manager, manager.start(parse_query("Duolingo")).id)
    assert await manager.cancel(job.id) == "finished"
    assert await manager.cancel("mock") == "finished"
    assert await manager.cancel("bg_nope") == "not_found"
    await manager.close()


async def test_extra_jobs_wait_their_turn_and_too_many_are_refused(make_settings: Callable[..., Settings]) -> None:
    manager = make_manager(make_settings(placeholder_step_seconds=5, max_running_jobs=1, max_waiting_jobs=1))
    first = manager.start(parse_query("Duolingo"))
    await asyncio.sleep(0.05)  # lets the first job take the only slot
    second = manager.start(parse_query("Stripe"))
    await asyncio.sleep(0.05)
    assert (await manager.get(first.id)).status == "running"  # type: ignore[union-attr]
    assert (await manager.get(second.id)).status == "queued"  # type: ignore[union-attr]

    with pytest.raises(JobsBusy):
        manager.start(parse_query("Linear"))

    # Cancelling the first job frees the slot for the second.
    await manager.cancel(first.id)
    await asyncio.sleep(0.05)
    assert (await manager.get(second.id)).status == "running"  # type: ignore[union-attr]
    await manager.close()


async def test_finished_jobs_are_saved_and_found_after_a_restart(settings: Settings) -> None:
    manager = make_manager(settings)
    done = await finished(manager, manager.start(parse_query("Duolingo")).id)
    failed = await finished(manager, manager.start(parse_query("fail.invalid")).id)
    await manager.close()
    assert (settings.data_dir / "guides" / f"{done.id}.json").is_file()

    restarted = make_manager(settings)
    assert await restarted.get(done.id) == done
    assert await restarted.get(failed.id) == failed


async def test_ids_that_could_reach_other_files_are_never_looked_up(settings: Settings) -> None:
    manager = make_manager(settings)
    for job_id in ("../config", "..%2Fx", "a/b", "", "x" * 65):
        assert await manager.get(job_id) is None


async def test_sample_jobs(settings: Settings) -> None:
    manager = make_manager(settings)
    for job_id, guide_id in (("mock", "bg_MOCK_northwind"), ("mock-partial", "bg_MOCK_northwind_partial")):
        job = await manager.get(job_id)
        assert job is not None
        assert job.status == "complete"
        assert set(statuses(job).values()) == {"done"}
        assert job.guide is not None
        assert job.guide.id == guide_id


def test_old_guide_files_are_removed(tmp_path: Path) -> None:
    store = GuideStore(tmp_path)
    old, recent = tmp_path / "bg_old.json", tmp_path / "bg_new.json"
    old.write_text("{}")
    recent.write_text("{}")
    forty_days_ago = time.time() - 40 * 24 * 60 * 60
    os.utime(old, (forty_days_ago, forty_days_ago))

    assert store.remove_older_than(30) == 1
    assert not old.exists()
    assert recent.exists()
