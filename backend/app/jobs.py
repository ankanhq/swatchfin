"""Guide jobs: making a guide in the background while the guide page watches.

A guide takes 30 to 90 seconds to make, which is too long for one request. So:

1. POST /api/v1/guides calls JobManager.start(). It creates a job, starts
   the work in the background and answers straight away with the job's ID.
2. The work (the "pipeline", see pipeline.py) goes through the seven steps.
   Each step marks itself running, then done (or skipped, or failed), with
   a short line for people about what it found.
3. The guide page asks GET /api/v1/guides/{id} every 1.5 seconds and moves
   its progress view along.

Limits that keep it safe:
- At most `max_running_jobs` jobs work at once. The others wait as
  "queued". (Each job opens a paid TinyFish Browser session.)
- When too many jobs are already waiting, new ones are refused as "busy".
- Every job has a time limit. A job that runs over it fails with a message.
- DELETE /api/v1/guides/{id} cancels a job that is still queued or running.
  A finished guide can't be deleted: anyone with its link could do that.

Reuse (see reuse.py): a search for a site that has a complete guide from
the last 24 hours gets that guide (JobManager.reuse). Two people asking
for the same search at once share one job, which stops early only when
both cancel it. A company name that Search turns into a site with a recent
guide stops after step 1 and reuses that guide (JobRun.earlier_guide).

Finished jobs (complete or failed) are saved as JSON files in
backend/data/guides/, so a guide's link keeps working after a restart.
Logos copied from a website's code are saved next to them, in
backend/data/logos/ (LogoStore). A job that was still running when the
server stopped is lost. On a host that wipes its files on restart (like
Render's free plan), saved guides are lost then too.
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
from typing import ClassVar, Literal

from pydantic import ValidationError

from app.extract.resolve import ParsedQuery, QueryError, parse_query
from app.reuse import RecentGuides, query_key, site_key
from app.schemas import STEP_NAMES, BrandGuide, Job, JobError, Step, StepName, StepState, TinyFishUsage, is_mock

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
# Looks up a complete, recent guide by its key (see reuse.py).
FindRecent = Callable[[str], Awaitable[Job | None]]


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

    def __init__(
        self,
        job_id: str,
        query: str,
        *,
        key: str = "",
        find_recent: FindRecent | None = None,
        on_reused: Callable[[], None] | None = None,
    ) -> None:
        self.job = Job(
            id=job_id,
            status="queued",
            query=query,
            started_at=now(),
            steps=[Step(name=name) for name in STEP_NAMES],
            tinyfish_usage=TinyFishUsage(),
        )
        # The search's key (reuse.py), and the websites the pipeline read, for reusing this guide later.
        self.key = key
        self.sites: list[str] = []
        # How many people asked for this job: it stops early only when all of them cancel it.
        self.requesters = 1
        # The ID of the earlier guide this job reused, if it did.
        self.reused_from: str | None = None
        self._find_recent = find_recent
        # Called when the job ends by reusing an earlier guide, so the limits can give the guide back.
        self.on_reused = on_reused

    @property
    def finished(self) -> bool:
        return self.job.status in ("complete", "failed")

    async def earlier_guide(self, url: str) -> Job | None:
        """Called by the pipeline once it knows the website. Returns a recent complete guide for
        the same site, to reuse instead of reading the site again, or None."""
        self.sites.append(url)
        if self._find_recent is None:
            return None
        earlier = await self._find_recent(site_key(url))
        if earlier is not None:
            self.reused_from = earlier.id
        return earlier

    @asynccontextmanager
    async def step(self, name: StepName) -> AsyncIterator[Step]:
        """Runs one step of the pipeline:

            async with job.step("reading_pages") as step:
                ...                      # the step's work
                step.detail = "6 pages read"

        In plain English: on the way in, the step is marked "running". The
        code inside does the work and can set a detail line. On the way out
        the step is marked "done", or "failed" if the code raised an error
        (the error then carries on and stops the job). A step that couldn't
        do its work but lets the guide carry on calls job.skip() inside, and
        then stays "skipped".
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
        if step.status == "running":
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
        _write_file(self._path(job_id), text)

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
        return _remove_old_files(self.folder, "*.json", days)

    def saved_since(self, hours: float) -> list[Job]:
        """The jobs saved in the last `hours` hours, for rebuilding the reuse list after a restart."""
        if not self.folder.is_dir():
            return []
        cutoff = time.time() - hours * 60 * 60
        jobs: list[Job] = []
        for path in self.folder.glob("*.json"):
            try:
                if path.stat().st_mtime < cutoff:
                    continue
            except OSError:
                continue
            if is_valid_id(path.stem) and (job := self._read(path.stem)) is not None:
                jobs.append(job)
        return jobs


class LogoStore:
    """Logos Swatchfin made its own copy of, one file each: backend/data/logos/<job id>-<number>.<svg|png>.

    A logo drawn with SVG code in the page is saved cleaned, as .svg. A logo
    drawn with a CSS background (Amazon's, cut from a picture of many) is
    saved as the browser photographed it, as .png. Served by
    GET /api/v1/guides/{id}/logos/{number}.svg or .png.
    """

    # Where a saved logo is served. The pipeline puts this address in the guide.
    URL = "/api/v1/guides/{job_id}/logos/{number}.{extension}"
    # A guide keeps at most this many logos (the main one and four others).
    MAX_PER_GUIDE = 5
    # The kinds of file kept, by file ending.
    MEDIA_TYPES: ClassVar[dict[str, str]] = {"svg": "image/svg+xml", "png": "image/png"}
    # A photographed logo must be a PNG file, and not a huge one.
    PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
    MAX_PNG_BYTES = 2_000_000

    def __init__(self, folder: Path) -> None:
        self.folder = folder

    def _path(self, job_id: str, number: int, extension: str) -> Path:
        # job_id has passed is_valid_id(), number is 1 to 5 and extension is svg or png, so the name can't
        # reach another folder.
        return self.folder / f"{job_id}-{number}.{extension}"

    def url(self, job_id: str, number: int, extension: str = "svg") -> str:
        return self.URL.format(job_id=job_id, number=number, extension=extension)

    @staticmethod
    def extension(content: str | bytes) -> str:
        """The file ending a copy is saved with: SVG code is text, a photographed logo is PNG bytes."""
        return "svg" if isinstance(content, str) else "png"

    async def save(self, job_id: str, number: int, content: str | bytes) -> None:
        """Saves a copy. Raises ValueError for bytes that aren't a PNG file of a sensible size."""
        if isinstance(content, bytes) and (
            not content.startswith(self.PNG_SIGNATURE) or len(content) > self.MAX_PNG_BYTES
        ):
            raise ValueError("not a PNG file of a logo's size")
        await asyncio.to_thread(_write_file, self._path(job_id, number, self.extension(content)), content)

    async def load(self, job_id: str, number: int, extension: str = "svg") -> str | bytes | None:
        if not is_valid_id(job_id) or not 1 <= number <= self.MAX_PER_GUIDE or extension not in self.MEDIA_TYPES:
            return None
        path = self._path(job_id, number, extension)
        try:
            if extension == "svg":
                return await asyncio.to_thread(path.read_text, encoding="utf-8")
            return await asyncio.to_thread(path.read_bytes)
        except FileNotFoundError:
            return None
        except OSError:
            log.warning("unreadable logo file id=%s number=%d", job_id, number, exc_info=True)
            return None

    def remove_older_than(self, days: int) -> int:
        """Deletes logo files last changed more than `days` days ago (with their guides). Returns how many."""
        return sum(_remove_old_files(self.folder, f"*.{extension}", days) for extension in self.MEDIA_TYPES)


def _write_file(path: Path, content: str | bytes) -> None:
    """Writes to a temporary file, then renames it: a reader never sees half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    if isinstance(content, bytes):
        temporary.write_bytes(content)
    else:
        temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def _remove_old_files(folder: Path, pattern: str, days: int) -> int:
    if not folder.is_dir():
        return 0
    cutoff = time.time() - days * 24 * 60 * 60
    removed = 0
    for path in folder.glob(pattern):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            log.warning("couldn't remove old file %s", path.name, exc_info=True)
    return removed


class JobManager:
    """Starts, tracks, cancels and finds guide jobs.

    `sample_job` finds the built-in sample jobs ("mock", "mock-partial") by
    ID; see pipeline.py. MOCK: it is given only where sample guides are
    switched on (SAMPLE_GUIDES). Without it, as in production, no guide
    marked MOCK is served, not even one left in the guides folder.
    """

    def __init__(
        self,
        pipeline: Pipeline,
        *,
        store: GuideStore,
        max_running: int,
        max_waiting: int,
        timeout_seconds: float,
        reuse_hours: float = 0,
        sample_job: Callable[[str], Job | None] | None = None,
    ) -> None:
        self.store = store
        self._pipeline = pipeline
        self._max_running = max_running
        self._max_waiting = max_waiting
        self._timeout = timeout_seconds
        self._reuse_hours = reuse_hours
        self._sample_job = sample_job
        # Lets at most max_running jobs past at a time; the others wait at it.
        self._slots = asyncio.Semaphore(max_running)
        # Jobs that are queued or running, and the background task doing each one.
        self._active: dict[str, JobRun] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        # Recently finished jobs, oldest first.
        self._finished: OrderedDict[str, Job] = OrderedDict()
        # Complete guides that may be reused, by key (reuse.py).
        self._recent = RecentGuides(reuse_hours)

    def start(self, query: ParsedQuery, *, on_reused: Callable[[], None] | None = None) -> Job:
        """Creates a job for a checked query and starts it in the background.

        `on_reused` is called if the job ends by reusing an earlier guide
        (a company name whose site has one). Raises JobsBusy when every slot
        is taken and the waiting room is full.
        """
        if len(self._active) >= self._max_running + self._max_waiting:
            raise JobsBusy

        run = JobRun(new_job_id(), query.text, key=query_key(query), find_recent=self._find_recent, on_reused=on_reused)
        job_id = run.job.id
        self._active[job_id] = run
        task = asyncio.create_task(self._run(run, query), name=f"guide job {job_id}")
        self._tasks[job_id] = task
        task.add_done_callback(lambda _task: self._tasks.pop(job_id, None))
        log.info("job queued id=%s kind=%s", job_id, query.kind)
        return run.job

    async def reuse(self, query: ParsedQuery) -> Job | None:
        """A job to give someone instead of starting a new one, or None.

        In plain English: if a job for the same search is being made right
        now, the person joins it. Otherwise, if a complete guide for the
        same search or site was made recently, they get that one.
        """
        key = query_key(query)
        for run in self._active.values():
            if run.key == key and not run.finished:
                run.requesters += 1
                log.info("job joined id=%s", run.job.id)
                return run.job
        job = await self._find_recent(key)
        if job is not None:
            log.info("guide reused id=%s", job.id)
        return job

    async def remember_recent(self) -> int:
        """Rebuilds the reuse list from the saved guides, when the server starts. Returns how many."""
        if not self._reuse_hours:
            return 0
        jobs = await asyncio.to_thread(self.store.saved_since, self._reuse_hours)
        for job in jobs:
            try:
                key = query_key(parse_query(job.query))
            except QueryError:
                continue
            self._remember_guide(job, {key})
        return len(jobs)

    async def _find_recent(self, key: str) -> Job | None:
        """The complete guide made for this key in the last REUSE_HOURS hours, or None."""
        job_id = self._recent.find(key)
        if job_id is None:
            return None
        job = await self.get(job_id)
        if job is None or job.status != "complete" or job.guide is None:
            self._recent.forget(key)
            return None
        return job

    def _remember_guide(self, job: Job, keys: set[str]) -> None:
        """Adds a complete guide to the reuse list, under its keys and its website's key."""
        if job.status != "complete" or job.guide is None or is_mock(job.guide):
            return
        keys = {key for key in keys if key} | {site_key(job.guide.brand.url)}
        self._recent.remember(keys, job.id, job.guide.generated_at)

    async def get(self, job_id: str) -> Job | None:
        """The job with this ID: one in progress, a finished one, or a sample. None if there is none."""
        job = await self._find(job_id)
        if job is not None and job.guide is not None and is_mock(job.guide) and self._sample_job is None:
            log.warning("refused a guide marked MOCK id=%s: sample guides are off", job_id)
            return None
        return job

    async def _find(self, job_id: str) -> Job | None:
        if not is_valid_id(job_id):
            return None
        if (run := self._active.get(job_id)) is not None:
            return run.job
        if (job := self._finished.get(job_id)) is not None:
            self._finished.move_to_end(job_id)
            return job
        if self._sample_job is not None and (job := await asyncio.to_thread(self._sample_job, job_id)) is not None:
            return job
        if (job := await self.store.load(job_id)) is not None:
            self._remember(job)
        return job

    async def cancel(self, job_id: str) -> CancelResult:
        """Stops a job that is still queued or running, and forgets it.

        A job that several people asked for keeps going until the last of
        them cancels it, so one person can't stop another's guide.
        Returns "cancelled", or "finished" for a job that can no longer be
        cancelled, or "not_found".
        """
        run = self._active.get(job_id)
        if run is None or run.finished:
            return "finished" if await self.get(job_id) is not None else "not_found"
        if run.requesters > 1:
            run.requesters -= 1
            log.info("job left id=%s, still wanted by %d", job_id, run.requesters)
            return "cancelled"

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
        self._remember_guide(run.job, {run.key, *(site_key(url) for url in run.sites)})
        self._active.pop(job_id, None)
        if run.reused_from is not None and run.job.status == "complete" and run.on_reused is not None:
            run.on_reused()
        try:
            await self.store.save(run.job)
        except OSError:
            log.warning("couldn't save guide id=%s", job_id, exc_info=True)

    def _remember(self, job: Job) -> None:
        self._finished[job.id] = job
        self._finished.move_to_end(job.id)
        while len(self._finished) > FINISHED_IN_MEMORY:
            self._finished.popitem(last=False)
