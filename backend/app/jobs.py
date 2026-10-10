"""Guide jobs: making a guide in the background while the guide page watches.

A guide takes 30–90 seconds to make, which is too long for one request. So:

1. POST /api/v1/guides calls JobManager.start(). It creates a job, starts
   the work in the background and answers straight away with the job's ID.
2. The work (the "pipeline", see pipeline.py) goes through the seven steps.
   Each step marks itself running, then done (or skipped, or failed), with
   a short line for people about what it found.
3. The guide page asks GET /api/v1/guides/{id} every 1.5 seconds and moves
   its progress view along.

Limits that keep it safe:
- At most `max_running_jobs` jobs work at once. The others wait as
  "queued". (From Phase 6 each job opens a paid TinyFish Browser session.)
- When too many jobs are already waiting, new ones are refused as "busy".
- Every job has a time limit. A job that runs over it fails with a message.
- DELETE /api/v1/guides/{id} cancels a job that is still queued or running.
  A finished guide can't be deleted: anyone with its link could do that.

Finished jobs (complete or failed) are saved as JSON files in
backend/data/guides/, so a guide's link keeps working after a restart.
A job that was still running when the server stopped is lost.
"""

import asyncio
import logging
import os
import re
import secrets
import time
from collections import OrderedDict
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from app.extract.resolve import ParsedQuery
from app.schemas import STEP_NAMES, BrandGuide, Job, JobError, Step, StepName, StepState, TinyFishUsage

log = logging.getLogger("swatchfin.jobs")

# Job IDs: letters, digits, _ and - only (the same rule as schemas.Id).
VALID_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")

# How many finished jobs to keep in memory, so popular guides aren't read from disk every time.
FINISHED_IN_MEMORY = 200

# Longest wait for a cancelled job to stop, so DELETE always answers.
CANCEL_WAIT_SECONDS = 10

TIMEOUT_ERROR = JobError(
    title="This guide took too long",
    message="Swatchfin stopped before the guide was complete because the website was too slow to read. Try again, "
    "or start a new guide.",
)
CRASH_ERROR = JobError(
    title="The guide couldn’t be finished",
    message="Something went wrong on Swatchfin’s side while making this guide. Try again in a moment.",
)

CancelResult = Literal["cancelled", "finished", "not_found"]
UsageCounter = Literal["search_calls", "fetch_urls", "browser_sessions"]


def now() -> datetime:
    return datetime.now(UTC)


def new_job_id() -> str:
    """A new, hard-to-guess job ID, like "bg_3f9a1c0e7b2d4a68".

    Anyone with a guide's link can open it, so IDs are random (64 bits) rather than counted up.
    """
    return f"bg_{secrets.token_hex(8)}"


def is_valid_id(job_id: str) -> bool:
    return VALID_ID.fullmatch(job_id) is not None


class StepFailed(Exception):
    """Raise inside a step to stop the job with a message for people.

    title and message are shown on the guide page. detail is the short line
    under the step that failed (leave it out to keep the step's last line).
    """

    def __init__(self, title: str, message: str, detail: str | None = None) -> None:
        super().__init__(message)
        self.error = JobError(title=title, message=message)
        self.detail = detail


class JobsBusy(Exception):
    """Too many jobs are already waiting for their turn."""


class JobRun:
    """One job while it is being made. The pipeline reports its progress here."""

    def __init__(self, job_id: str, query: str) -> None:
        self.job = Job(
            id=job_id,
            status="queued",
            query=query,
            started_at=now(),
            steps=[Step(name=name) for name in STEP_NAMES],
            tinyfish_usage=TinyFishUsage(),
        )

    @property
    def finished(self) -> bool:
        return self.job.status in ("complete", "failed")

    @asynccontextmanager
    async def step(self, name: StepName) -> AsyncIterator[Step]:
        """Runs one step of the pipeline:

            async with job.step("reading_pages") as step:
                ...                      # the step's work
                step.detail = "6 pages read"

        In plain English: on the way in, the step is marked "running". The
        code inside does the work and can set a detail line. On the way out
        the step is marked "done", or "failed" if the code raised an error
        (the error then carries on and stops the job).
        """
        step = self._find(name)
        step.status = "running"
        step.started_at = now()
        try:
            yield step
        except StepFailed as error:
            _finish(step, "failed", error.detail)
            raise
        except Exception:
            _finish(step, "failed", "Something went wrong in this step.")
            raise
        _finish(step, "done")

    def skip(self, name: StepName, detail: str) -> None:
        """Marks a step as not needed, e.g. no search when a web address was given."""
        step = self._find(name)
        step.started_at = now()
        _finish(step, "skipped", detail)

    def count(self, counter: UsageCounter, amount: int = 1) -> None:
        """Adds TinyFish calls to the job's running totals, e.g. count("fetch_urls", 6)."""
        usage = self.job.tinyfish_usage
        setattr(usage, counter, getattr(usage, counter) + amount)

    def start_running(self) -> None:
        self.job.status = "running"

    def complete(self, guide: BrandGuide) -> None:
        self.job.status = "complete"
        self.job.guide = guide

    def fail(self, error: JobError, running_step_detail: str | None = None) -> None:
        """Stops the job. A step that was still running is marked failed."""
        for step in self.job.steps:
            if step.status == "running":
                _finish(step, "failed", running_step_detail)
        self.job.status = "failed"
        self.job.error = error

    def _find(self, name: StepName) -> Step:
        return next(step for step in self.job.steps if step.name == name)


def _finish(step: Step, status: StepState, detail: str | None = None) -> None:
    step.status = status
    step.finished_at = now()
    if detail is not None:
        step.detail = detail


# The work that makes a guide: given the job (to report progress to) and the
# checked query, it returns the finished guide. See pipeline.py.
Pipeline = Callable[[JobRun, ParsedQuery], Awaitable[BrandGuide]]


class GuideStore:
    """Finished jobs as JSON files, one per job: backend/data/guides/<id>.json."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder

    def _path(self, job_id: str) -> Path:
        # job_id has passed is_valid_id(), so it can't contain "/" or "..".
        return self.folder / f"{job_id}.json"

    async def save(self, job: Job) -> None:
        await asyncio.to_thread(self._write, job.id, job.model_dump_json())

    async def load(self, job_id: str) -> Job | None:
        return await asyncio.to_thread(self._read, job_id)

    def _write(self, job_id: str, text: str) -> None:
        # Write to a temporary file, then rename it: a reader never sees half a file.
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self._path(job_id)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, path)

    def _read(self, job_id: str) -> Job | None:
        path = self._path(job_id)
        try:
            return Job.model_validate_json(path.read_bytes())
        except FileNotFoundError:
            return None
        except (OSError, ValidationError):
            log.warning("unreadable guide file id=%s", job_id, exc_info=True)
            return None

    def remove_older_than(self, days: int) -> int:
        """Deletes guide files last changed more than `days` days ago. Returns how many."""
        if not self.folder.is_dir():
            return 0
        cutoff = time.time() - days * 24 * 60 * 60
        removed = 0
        for path in self.folder.glob("*.json"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
                    removed += 1
            except OSError:
                log.warning("couldn't remove old guide file %s", path.name, exc_info=True)
        return removed


class JobManager:
    """Starts, tracks, cancels and finds guide jobs.

    `sample_job` finds the built-in sample jobs ("mock", "mock-partial") by
    ID; see pipeline.py.
    """

    def __init__(
        self,
        pipeline: Pipeline,
        *,
        store: GuideStore,
        max_running: int,
        max_waiting: int,
        timeout_seconds: float,
        sample_job: Callable[[str], Job | None] = lambda _job_id: None,
    ) -> None:
        self.store = store
        self._pipeline = pipeline
        self._max_running = max_running
        self._max_waiting = max_waiting
        self._timeout = timeout_seconds
        self._sample_job = sample_job
        # Lets at most max_running jobs past at a time; the others wait at it.
        self._slots = asyncio.Semaphore(max_running)
        # Jobs that are queued or running, and the background task doing each one.
        self._active: dict[str, JobRun] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        # Recently finished jobs, oldest first.
        self._finished: OrderedDict[str, Job] = OrderedDict()

    def start(self, query: ParsedQuery) -> Job:
        """Creates a job for a checked query and starts it in the background.

        Raises JobsBusy when every slot is taken and the waiting room is full.
        """
        if len(self._active) >= self._max_running + self._max_waiting:
            raise JobsBusy

        run = JobRun(new_job_id(), query.text)
        job_id = run.job.id
        self._active[job_id] = run
        task = asyncio.create_task(self._run(run, query), name=f"guide job {job_id}")
        self._tasks[job_id] = task
        task.add_done_callback(lambda _task: self._tasks.pop(job_id, None))
        log.info("job queued id=%s kind=%s", job_id, query.kind)
        return run.job

    async def get(self, job_id: str) -> Job | None:
        """The job with this ID: one in progress, a finished one, or a sample. None if there is none."""
        if not is_valid_id(job_id):
            return None
        if (run := self._active.get(job_id)) is not None:
            return run.job
        if (job := self._finished.get(job_id)) is not None:
            self._finished.move_to_end(job_id)
            return job
        if (job := await asyncio.to_thread(self._sample_job, job_id)) is not None:
            return job
        if (job := await self.store.load(job_id)) is not None:
            self._remember(job)
        return job

    async def cancel(self, job_id: str) -> CancelResult:
        """Stops a job that is still queued or running, and forgets it.

        Returns "cancelled", or "finished" for a job that can no longer be
        cancelled, or "not_found".
        """
        run = self._active.get(job_id)
        if run is None or run.finished:
            return "finished" if await self.get(job_id) is not None else "not_found"

        del self._active[job_id]
        task = self._tasks.get(job_id)
        if task is not None:
            task.cancel()
            # Wait for it to stop, so anything it opened is closed before we answer.
            await asyncio.wait({task}, timeout=CANCEL_WAIT_SECONDS)
        log.info("job cancelled id=%s", job_id)
        return "cancelled"

    async def close(self) -> None:
        """Stops every job. Called when the server shuts down."""
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.wait(tasks, timeout=CANCEL_WAIT_SECONDS)

    async def _run(self, run: JobRun, query: ParsedQuery) -> None:
        """The background task for one job.

        In plain English: wait for a free slot, then run the pipeline with a
        time limit. However it ends (a guide, a step that failed, too slow,
        an unexpected error), record the result on the job and save it.
        Cancelling (DELETE) stops the task wherever it is; the job is then
        simply forgotten.
        """
        job_id = run.job.id
        async with self._slots:
            run.start_running()
            log.info("job running id=%s", job_id)
            try:
                async with asyncio.timeout(self._timeout):
                    guide = await self._pipeline(run, query)
            except StepFailed as error:
                run.fail(error.error)
            except TimeoutError:
                run.fail(TIMEOUT_ERROR, running_step_detail="Stopped: this step took too long.")
            except Exception:
                log.exception("job crashed id=%s", job_id)
                run.fail(CRASH_ERROR)
            else:
                run.complete(guide)

        log.info("job %s id=%s", run.job.status, job_id)
        self._remember(run.job)
        self._active.pop(job_id, None)
        try:
            await self.store.save(run.job)
        except OSError:
            log.warning("couldn't save guide id=%s", job_id, exc_info=True)

    def _remember(self, job: Job) -> None:
        self._finished[job.id] = job
        self._finished.move_to_end(job.id)
        while len(self._finished) > FINISHED_IN_MEMORY:
            self._finished.popitem(last=False)
