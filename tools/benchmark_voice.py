"""Compares the language models for step 6 (Claude, Gemini, Groq) on the same brand text.

Run it from the repo root, with the virtual environment turned on and the keys in .env:

    source .venv/bin/activate
    python tools/benchmark_voice.py stripe.com patagonia.com duolingo.com

For each site it:
1. reads the site once with the real pipeline (TinyFish Search, Fetch and
   Browser), and keeps the request step 6 would send (the instructions and
   the text) and the pages step 7 checks quotes against;
2. sends that same request to every model in LLM_ORDER that has a key. Each
   one is asked, one after the other, with 90 seconds each: this compares
   them, rather than stopping at the first answer like the real step 6;
3. runs step 7's word-for-word check on each answer, as a guide would.

It prints a Markdown table, and saves everything (the text read, each answer
and its checks) as JSON in the --out folder (a new temporary folder unless
given), for a closer look. Those files hold the brands' public website text
and are not part of the repo.

Cost: one TinyFish Browser session per site (about $0.001 of wallet credit),
Search and Fetch from the free allowance, and Claude at about $0.03 a site.
Groq's and Google's free tiers cost nothing; the table also shows what each
call would cost on their paid tiers.
"""

import argparse
import asyncio
import json
import logging
import sys
import tempfile
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import httpx2
from app import pipeline
from app.config import Settings
from app.extract.homepage import Homepage
from app.extract.pages import ReadPage
from app.extract.resolve import parse_query
from app.extract.verify import check_voice
from app.extract.voice import MAX_ANSWER_TOKENS, DraftVoice, SourcePage
from app.jobs import GuideStore, JobManager, LogoStore
from app.llm import AnswerT, LLMAnswer, LLMError, ProviderLLM
from app.main import language_models
from app.schemas import Job
from app.tinyfish.browser import PlaywrightDriver, wait_for_endings
from app.tinyfish.client import TinyFishClient

# Each model gets this long for each site: enough to see how long it really takes.
TIME_LIMIT = 90.0
# Groq's free tier counts tokens per minute, so a second round waits this long first.
ROUND_PAUSE = 65.0


class Recorder:
    """Stands in for the language model while a site is read: keeps the request and gives no answer."""

    def __init__(self) -> None:
        self.request: dict[str, str] | None = None

    async def ask(
        self,
        *,
        system: str,
        prompt: str,
        answer: type[AnswerT],
        max_tokens: int,
        time_limit: float,
    ) -> LLMAnswer[AnswerT]:
        self.request = {"system": system, "prompt": prompt}
        raise LLMError("kept for the benchmark")


async def read_site(
    query: str,
    settings: Settings,
    http: httpx2.AsyncClient,
    browser: PlaywrightDriver,
    data_dir: Path,
) -> tuple[Job, dict[str, str], list[SourcePage]]:
    """Runs steps 1 to 5 of the real pipeline for one site. Returns the job, step 6's request and step 7's pages."""
    recorder = Recorder()
    found: list[list[SourcePage]] = []
    original = pipeline.source_pages

    # The pages step 7 checks against are made inside the pipeline; this keeps a copy as they are made.
    def keep_pages(homepage: Homepage, pages: list[ReadPage]) -> list[SourcePage]:
        found.append(original(homepage, pages))
        return found[-1]

    pipeline.source_pages = keep_pages
    try:
        manager = JobManager(
            pipeline.brand_pipeline(
                TinyFishClient(settings.tinyfish_api_key, http),
                LogoStore(data_dir / "logos"),
                browser=browser if settings.use_browser else None,
                llm=recorder,
                time_limit=settings.job_timeout_seconds,
            ),
            store=GuideStore(data_dir / "guides"),
            max_running=1,
            max_waiting=0,
            timeout_seconds=settings.job_timeout_seconds,
        )
        job_id = manager.start(parse_query(query)).id
        while True:
            job = await manager.get(job_id)
            if job is None or job.status in ("complete", "failed"):
                break
            await asyncio.sleep(1)
        await manager.close()
    finally:
        pipeline.source_pages = original
    if job is None or job.status != "complete" or recorder.request is None or not found:
        reason = job.error.message if job and job.error else "step 6 was never reached"
        raise SystemExit(f"{query}: the site couldn’t be read: {reason}")
    return job, recorder.request, found[-1]


async def ask(
    model: ProviderLLM, request: dict[str, str], pages: list[SourcePage]
) -> dict[str, Any]:
    """Asks one model and checks its answer with step 7. Returns the numbers for the table."""
    result: dict[str, Any] = {"api": model.api, "model": model.model}
    started = time.monotonic()
    try:
        answer = await model.ask(
            system=request["system"],
            prompt=request["prompt"],
            answer=DraftVoice,
            max_tokens=MAX_ANSWER_TOKENS,
            time_limit=TIME_LIMIT,
        )
    except LLMError as error:
        result |= {
            "ok": False,
            "error": error.reason,
            "seconds": round(time.monotonic() - started, 1),
            "usage": asdict(error.usage) if error.usage else None,
        }
        return result

    draft = answer.data
    checked = check_voice(draft, pages)
    tagline, mission = checked.messaging.tagline, checked.messaging.mission
    return result | {
        "ok": True,
        "seconds": round(answer.usage.seconds, 1),
        "input_tokens": answer.usage.input_tokens,
        "output_tokens": answer.usage.output_tokens,
        "cost_usd": answer.usage.cost_usd,
        "quotes_checked": checked.quotes_checked,
        "quotes_verified": checked.quotes_verified,
        "traits_drafted": len(draft.traits),
        "traits_kept": [trait.name for trait in checked.voice.traits],
        "tagline_drafted": draft.tagline.text if draft.tagline else None,
        "tagline": tagline.text if tagline else None,
        "mission_drafted": draft.mission.text if draft.mission else None,
        "mission": mission.text if mission else None,
        "value_props_drafted": len(draft.value_props),
        "value_props_kept": [prop.title for prop in checked.messaging.value_props],
        "audience": checked.messaging.audience,
        "spectrum": draft.spectrum.model_dump(),
        "warnings": checked.warnings,
        "draft": draft.model_dump(),
    }


def table(results: list[dict[str, Any]]) -> str:
    """The results as a Markdown table, one row per site and model."""
    rows = [
        (
            "| Site | Model | Time | Tokens in + out | Cost (paid tier) | Quotes verified | Traits kept | "
            "Tagline | Mission | Value props kept |"
        ),
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for site in results:
        for run in site["runs"]:
            name = f"{run['model']} (round {run['round']})"
            if not run["ok"]:
                rows.append(
                    f"| {site['query']} | {name} | {run['seconds']} s | failed: {run['error']} |||||||"
                )
                continue
            cost = "?" if run["cost_usd"] is None else f"${run['cost_usd']:.4f}"
            rows.append(
                f"| {site['query']} | {name} | {run['seconds']} s | {run['input_tokens']:,} + "
                f"{run['output_tokens']:,} | {cost} | {run['quotes_verified']} of {run['quotes_checked']} | "
                f"{len(run['traits_kept'])} of {run['traits_drafted']} | {_shown(run, 'tagline')} | "
                f"{_shown(run, 'mission')} | {len(run['value_props_kept'])} of {run['value_props_drafted']} |"
            )
    return "\n".join(rows)


def _shown(run: dict[str, Any], what: str) -> str:
    """A tagline or mission for the table: found, dropped (not word for word) or none drafted."""
    if run[what]:
        return f"“{run[what]}”"
    return "dropped" if run[f"{what}_drafted"] else "none"


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "sites", nargs="+", help="company names or web addresses, e.g. stripe.com"
    )
    parser.add_argument(
        "--rounds",
        type=int,
        default=1,
        help="how many times to ask each model (default 1)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="folder for the JSON results (default: a new temporary folder)",
    )
    args = parser.parse_args()
    out = args.out or Path(tempfile.mkdtemp(prefix="swatchfin-benchmark-"))
    out.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s"
    )

    settings = Settings()
    browser = PlaywrightDriver()
    results: list[dict[str, Any]] = []
    async with httpx2.AsyncClient(
        headers={"User-Agent": "Swatchfin benchmark"}
    ) as http:
        models = language_models(settings, http)
        if models is None:
            raise SystemExit(
                "No ANTHROPIC_API_KEY, GROQ_API_KEY or GEMINI_API_KEY in .env"
            )
        print(
            "Models:",
            ", ".join(model.model for model in models.models),
            file=sys.stderr,
        )
        try:
            for query in args.sites:
                print(f"Reading {query} with TinyFish…", file=sys.stderr)
                job, request, pages = await read_site(
                    query, settings, http, browser, out / "data"
                )
                site: dict[str, Any] = {
                    "query": query,
                    "pages_sent": request["prompt"].count("<page "),
                    "characters_sent": len(request["prompt"]),
                    "tinyfish_usage": job.tinyfish_usage.model_dump(),
                    "runs": [],
                }
                for round_number in range(1, args.rounds + 1):
                    if round_number > 1:
                        await asyncio.sleep(ROUND_PAUSE)
                    for model in models.models:
                        print(
                            f"  asking {model.model} (round {round_number})…",
                            file=sys.stderr,
                        )
                        run = await ask(model, request, pages)
                        site["runs"].append({"round": round_number, **run})
                results.append(site)
                (out / f"{query.replace('/', '_')}.json").write_text(
                    json.dumps(
                        {
                            **site,
                            "request": request,
                            "pages": [asdict(page) for page in pages],
                        },
                        indent=2,
                    ),
                    encoding="utf-8",
                )
        finally:
            await models.close()
            await wait_for_endings(15)
            await browser.stop()

    (out / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(table(results))
    print(f"\nEverything is saved in {out}", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
