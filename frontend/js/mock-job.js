/**
 * MOCK: simulated guide jobs. Delete this file in Phase 4.
 *
 * The real backend generates a guide as a background job, and the guide
 * page asks for the job's status every 1.5 seconds (see api.js). Until that
 * backend exists, this file plays its part, so the progress view can be
 * built and reviewed:
 *
 *   guide.html?q=…              a 10-second timed run that ends on the
 *                                Northwind Roasters sample guide
 *   guide.html?id=mock-failed    a run that stops at "Reading the homepage"
 *   guide.html?id=mock           the finished sample guide
 *   guide.html?id=mock-partial   a finished guide without colours or fonts
 *
 * Nothing here reads a website. The detail lines describe Northwind
 * Roasters, a fictional brand, and the page labels every simulated run.
 * The jobs it returns have exactly the shape the real backend will send
 * ("Job status" in CLAUDE.md, section 7).
 */

import { parseQuery } from './utils.js';

const SAMPLE_GUIDE_URL = 'mock/MOCK_northwind-roasters.json';
const PARTIAL_GUIDE_URL = 'mock/MOCK_northwind-roasters-partial.json';

/** Finished mock guides: job ID -> guide file. */
const FINISHED_GUIDES = { mock: SAMPLE_GUIDE_URL, 'mock-partial': PARTIAL_GUIDE_URL };

const RUN_PREFIX = 'mock-run-';
const FAILED_RUN_ID = 'mock-failed';
const STORAGE_PREFIX = 'sf-mock-run:';

/** How long a new run waits in the queue before the first step starts. */
const QUEUED_MS = 400;

/**
 * The seven steps, in order: how long each takes in the simulation, the
 * detail line while it runs and once it is done, and the TinyFish calls it
 * adds (at the start of the step, or when it is done).
 */
const STEPS = [
  { name: 'resolving', ms: 1200, done: 'Found northwind-roasters.example', usageWhenDone: { search_calls: 1 } },
  { name: 'reading_homepage', ms: 1400, done: 'Found the logo, favicon, theme colour and 42 links', usageWhenDone: { fetch_urls: 1 } },
  { name: 'discovering_pages', ms: 800, done: 'Picked 6 pages: About, Coffee, Subscriptions, Journal, Careers and Press' },
  { name: 'reading_pages', ms: 2000, running: 'Reading 6 pages', done: '5 of 6 pages read. Press was blocked by an anti-bot check.', usageWhenDone: { fetch_urls: 5 } },
  { name: 'reading_styles', ms: 2200, running: 'Browser session open', done: '8 colours and 3 fonts measured', usageAtStart: { browser_sessions: 1 } },
  { name: 'analysing_voice', ms: 1600, done: '3 traits and 4 value propositions drafted' },
  { name: 'verifying', ms: 800, done: '1 quote dropped, 12 contrast pairs scored' },
];

const SKIPPED_SEARCH_DETAIL = 'You gave a web address, so no search was needed.';

/** How the mock-failed run ends. */
const FAILURE = {
  step: 'reading_homepage',
  afterMs: 1600,
  detail: 'Blocked by an anti-bot check',
  error: {
    title: 'The homepage couldn’t be read',
    message:
      'northwind-roasters.example turned away both TinyFish Fetch and the browser with an anti-bot check, so there was nothing to build a guide from. Try again later, or paste the address of another page on the same site.',
  },
};

/**
 * @typedef {{ id: string, query: string, skipSearch: boolean, startedAt: number, fails: boolean }} MockRun
 */

/** Runs started on this page, by ID. Also kept in sessionStorage, so a reload carries on. */
const runs = new Map();

/** The mock-failed run starts again on every page load. */
let failedRun = null;

/**
 * Starts a simulated run for a query (already checked with parseQuery).
 * @param {string} query
 * @returns {{ id: string }}
 */
export function startMockRun(query) {
  const parsed = parseQuery(query);
  /** @type {MockRun} */
  const run = {
    id: `${RUN_PREFIX}${Date.now().toString(36)}`,
    query,
    skipSearch: parsed.ok && parsed.kind === 'url',
    startedAt: Date.now(),
    fails: false,
  };
  saveRun(run);
  return { id: run.id };
}

/**
 * True for the IDs of simulated runs (not the finished mock guides).
 * @param {string} id
 * @returns {boolean}
 */
export function isMockRunId(id) {
  return id === FAILED_RUN_ID || id.startsWith(RUN_PREFIX);
}

/**
 * The status of a mock job, in the same shape the backend will send, or
 * null if there is no mock job with this ID.
 *
 * @param {string} id
 * @param {(url: string) => Promise<any>} loadGuide Downloads a guide file (api.js passes its fetchJson).
 * @returns {Promise<Record<string, any> | null>}
 */
export async function getMockJob(id, loadGuide) {
  if (Object.hasOwn(FINISHED_GUIDES, id)) {
    const guide = await loadGuide(FINISHED_GUIDES[id]);
    return finishedJob(id, guide);
  }

  const run = id === FAILED_RUN_ID ? getFailedRun() : loadRun(id);
  if (!run) return null;

  const job = jobAt(run, Date.now());
  if (job.status === 'complete') job.guide = await loadGuide(SAMPLE_GUIDE_URL);
  return job;
}

/**
 * Works out where a run is at a given moment.
 *
 * In plain English: walk through the steps on a clock that starts when the
 * run starts. A step that should have ended by `now` is done, the one the
 * clock is inside is running, and the ones after it are still waiting.
 * A skipped step takes no time. In the failing run, the failing step stops
 * the clock, and every step after it stays "pending".
 *
 * @param {MockRun} run
 * @param {number} now Milliseconds, like Date.now().
 * @returns {Record<string, any>}
 */
function jobAt(run, now) {
  const usage = { search_calls: 0, fetch_urls: 0, browser_sessions: 0 };
  const steps = [];
  let clock = run.startedAt + QUEUED_MS; // when the next step starts
  let status = now < clock ? 'queued' : 'running';

  for (const step of STEPS) {
    const skipped = step.name === 'resolving' && run.skipSearch;
    const fails = run.fails && step.name === FAILURE.step;
    const startsAt = clock;
    const endsAt = startsAt + (skipped ? 0 : fails ? FAILURE.afterMs : step.ms);

    if (status === 'failed' || now < startsAt) {
      steps.push(stepStatus(step.name, 'pending'));
    } else if (skipped) {
      steps.push(stepStatus(step.name, 'skipped', SKIPPED_SEARCH_DETAIL, startsAt, endsAt));
    } else if (now < endsAt) {
      steps.push(stepStatus(step.name, 'running', step.running, startsAt));
      addUsage(usage, step.usageAtStart);
    } else if (fails) {
      steps.push(stepStatus(step.name, 'failed', FAILURE.detail, startsAt, endsAt));
      addUsage(usage, step.usageAtStart);
      status = 'failed';
    } else {
      steps.push(stepStatus(step.name, 'done', step.done, startsAt, endsAt));
      addUsage(usage, step.usageAtStart);
      addUsage(usage, step.usageWhenDone);
    }
    clock = endsAt;
  }

  if (status === 'running' && steps.every((step) => step.status === 'done' || step.status === 'skipped')) {
    status = 'complete';
  }

  return {
    id: run.id,
    status,
    query: run.query,
    started_at: new Date(run.startedAt).toISOString(),
    steps,
    tinyfish_usage: usage,
    error: status === 'failed' ? FAILURE.error : null,
    guide: null,
  };
}

/**
 * A job that finished before the page asked: every step done, and the guide.
 * @param {string} id
 * @param {Record<string, any>} guide
 * @returns {Record<string, any>}
 */
function finishedJob(id, guide) {
  return {
    id,
    status: 'complete',
    query: typeof guide?.query === 'string' ? guide.query : '',
    started_at: null,
    steps: STEPS.map((step) => stepStatus(step.name, 'done')),
    tinyfish_usage: guide?.tinyfish_usage ?? null,
    error: null,
    guide,
  };
}

/**
 * One entry of a job's "steps" list.
 * @param {string} name
 * @param {'pending' | 'running' | 'done' | 'skipped' | 'failed'} status
 * @param {string} [detail]
 * @param {number} [startedAt]
 * @param {number} [finishedAt]
 */
function stepStatus(name, status, detail, startedAt, finishedAt) {
  return {
    name,
    status,
    detail: detail ?? null,
    started_at: startedAt === undefined ? null : new Date(startedAt).toISOString(),
    finished_at: finishedAt === undefined ? null : new Date(finishedAt).toISOString(),
  };
}

/**
 * Adds a step's TinyFish calls to the running totals.
 * @param {Record<string, number>} usage
 * @param {Record<string, number> | undefined} extra
 */
function addUsage(usage, extra) {
  for (const [key, value] of Object.entries(extra ?? {})) usage[key] += value;
}

/** @returns {MockRun} */
function getFailedRun() {
  failedRun ??= {
    id: FAILED_RUN_ID,
    query: 'https://northwind-roasters.example',
    skipSearch: true,
    startedAt: Date.now(),
    fails: true,
  };
  return failedRun;
}

/** @param {MockRun} run */
function saveRun(run) {
  runs.set(run.id, run);
  try {
    sessionStorage.setItem(STORAGE_PREFIX + run.id, JSON.stringify(run));
  } catch {
    // Storage blocked: the run still works until the page is reloaded.
  }
}

/**
 * @param {string} id
 * @returns {MockRun | null}
 */
function loadRun(id) {
  if (!id.startsWith(RUN_PREFIX)) return null;
  if (runs.has(id)) return runs.get(id);
  try {
    const run = JSON.parse(sessionStorage.getItem(STORAGE_PREFIX + id) ?? 'null');
    if (run && typeof run.query === 'string' && typeof run.startedAt === 'number') {
      runs.set(id, run);
      return run;
    }
  } catch {
    // Storage blocked or the saved run is damaged: treat it as not found.
  }
  return null;
}
