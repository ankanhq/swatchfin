/**
 * Where the guide page gets its data: guide jobs from the Swatchfin backend.
 *
 * A guide takes 30–90 seconds to make, so the backend makes it as a
 * background job:
 *   startGuide(query)   POST /api/v1/guides       -> { id }
 *   watchGuide(id, …)   GET  /api/v1/guides/{id}  every 1.5 s, until the
 *                       job is complete (with the guide) or failed
 * The job's shape is "Job status" in CLAUDE.md, section 7.
 *
 * MOCK: there is no backend yet, so both go to mock-job.js, which simulates
 * jobs for Northwind Roasters, a fictional brand. Phase 4 changes only the
 * lines marked "MOCK" below, and deletes mock-job.js.
 */

import { getMockJob, isMockRunId, startMockRun } from './mock-job.js'; // MOCK

/** Longest wait for one answer from the server. guide-guard.js uses the same limit for the first one. */
const REQUEST_TIMEOUT_MS = 15000;

/** How often to ask for a job's status. */
const POLL_MS = 1500;

/** Failed status checks in a row (offline, timeout, server error) before giving up. */
const MAX_FAILED_CHECKS = 3;

/** Most guides take about a minute. After 3 minutes the page stops waiting and says so. */
const WATCH_LIMIT_MS = 3 * 60 * 1000;

/** This page understands schema 1.x (see CLAUDE.md, section 6). */
const SUPPORTED_MAJOR_VERSION = '1';

const JOB_STATUSES = ['queued', 'running', 'complete', 'failed'];

/**
 * An error the page can show to people as it is: a short title and a
 * sentence that explains what happened and what to do.
 */
export class GuideError extends Error {
  /**
   * @param {string} title
   * @param {string} message
   * @param {{ retryable?: boolean, retryLabel?: string }} [options]
   *   retryable: a passing problem (offline, timeout, busy server), so asking again may work.
   *   retryLabel: the text of the retry button under the message.
   */
  constructor(title, message, { retryable = false, retryLabel = 'Try again' } = {}) {
    super(message);
    this.name = 'GuideError';
    this.title = title;
    this.retryable = retryable;
    this.retryLabel = retryLabel;
  }
}

/**
 * Starts a new guide for a company name or URL (already checked with
 * parseQuery) and returns the new job's ID.
 * @param {string} query
 * @returns {Promise<{ id: string }>}
 */
export async function startGuide(query) {
  // MOCK: Phase 4 sends POST /api/v1/guides with { query } instead.
  return startMockRun(query);
}

/**
 * Follows a job until it is complete or failed, and returns its last status.
 *
 * In plain English: ask for the job's status, pass it to onUpdate (so the
 * page can move the steps along), and if it isn't finished, wait 1.5
 * seconds and ask again. A failed check (no connection, timeout, server
 * error) is retried up to three times, waiting a little longer each time,
 * before the page shows an error. After three minutes it stops waiting.
 *
 * @param {string} id
 * @param {{ onUpdate?: (job: Record<string, any>) => void }} [options]
 * @returns {Promise<Record<string, any>>}
 */
export async function watchGuide(id, { onUpdate = () => {} } = {}) {
  const watchStarted = Date.now();
  let failedChecks = 0;

  for (;;) {
    let job;
    try {
      job = await getJob(id);
      failedChecks = 0;
    } catch (error) {
      const retryable = error instanceof GuideError && error.retryable;
      failedChecks += 1;
      if (!retryable || failedChecks > MAX_FAILED_CHECKS) throw error;
      await wait(POLL_MS * 2 ** (failedChecks - 1)); // 1.5 s, then 3 s, then 6 s
      continue;
    }

    onUpdate(job);
    if (job.status === 'complete' || job.status === 'failed') return job;

    if (Date.now() - watchStarted > WATCH_LIMIT_MS) {
      throw new GuideError(
        'This is taking longer than usual',
        'Most guides are ready in about a minute, and this one is still being made. Keep waiting, or start again from the start page.',
        { retryable: true, retryLabel: 'Keep waiting' },
      );
    }
    await wait(POLL_MS);
  }
}

/**
 * One status check.
 * @param {string} id
 * @returns {Promise<Record<string, any>>}
 */
async function getJob(id) {
  // MOCK: Phase 4 replaces the next two lines with
  //   const job = await fetchJson(`/api/v1/guides/${encodeURIComponent(id)}`);
  // and turns a 404 answer into notFound(id).
  const job = await getMockJob(id, fetchJson);
  if (!job) throw notFound(id);

  checkJob(job);
  return job;
}

/**
 * Downloads and parses JSON. Every problem becomes a GuideError.
 * @param {string} url
 * @returns {Promise<any>}
 */
async function fetchJson(url) {
  let response;
  try {
    // no-store: always ask the server, never reuse an old copy of a status.
    response = await fetch(url, {
      cache: 'no-store',
      headers: { Accept: 'application/json' },
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
  } catch (error) {
    throw requestError(error);
  }

  if (!response.ok) {
    // Busy or broken for a moment (408, 429, 5xx): worth asking again.
    const retryable = response.status === 408 || response.status === 429 || response.status >= 500;
    throw new GuideError('Couldn’t load the guide', `The server answered with an error (${response.status}). Try again in a moment.`, { retryable });
  }

  try {
    return await response.json();
  } catch (error) {
    if (error?.name === 'TimeoutError') throw requestError(error);
    throw new GuideError('This guide can’t be read', 'The guide data is damaged or incomplete.');
  }
}

/**
 * Turns a failed request into a message for people: too slow, or no connection.
 * @param {unknown} error
 * @returns {GuideError}
 */
function requestError(error) {
  if (error?.name === 'TimeoutError') {
    return new GuideError('This is taking too long', 'The server didn’t answer within 15 seconds. Check your connection and try again.', { retryable: true });
  }
  return new GuideError('Couldn’t load the guide', 'The connection failed. Check that you are online and try again.', { retryable: true });
}

/**
 * @param {string} id
 * @returns {GuideError}
 */
function notFound(id) {
  const shown = id.length > 40 ? `${id.slice(0, 40)}…` : id;
  return new GuideError(
    'Guide not found',
    `There is no guide with the ID “${shown}”. Guides are kept for a limited time, so it may have expired. Generate a new one from the start page.`,
  );
}

/**
 * Throws a GuideError unless the data looks like a job status, and, once
 * it is complete, carries a guide in a format this page understands.
 * @param {unknown} job
 */
function checkJob(job) {
  if (!job || typeof job !== 'object' || Array.isArray(job) || !JOB_STATUSES.includes(job.status)) {
    throw new GuideError('This guide can’t be read', 'The server sent something that isn’t a guide.');
  }
  if (job.status === 'complete') checkGuide(job.guide);
}

/**
 * Throws a GuideError unless the data looks like a guide in schema 1.x.
 * Individual sections are still checked when they are shown, because a
 * real guide can be partial.
 * @param {unknown} data
 */
function checkGuide(data) {
  if (!data || typeof data !== 'object' || Array.isArray(data)) {
    throw new GuideError('This guide can’t be read', 'The data is not a brand guide.');
  }
  const version = typeof data.schema_version === 'string' ? data.schema_version : '';
  if (version.split('.')[0] !== SUPPORTED_MAJOR_VERSION) {
    throw new GuideError(
      'Unsupported guide format',
      `This guide uses format ${version || '(unknown)'}, but this page only understands format 1. Reload the page to get the latest version.`,
    );
  }
}

/** @param {number} ms */
function wait(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

/**
 * True for the mock guides. Their IDs start with "bg_MOCK".
 * @param {Record<string, any>} guide
 * @returns {boolean}
 */
export function isMockGuide(guide) {
  return typeof guide?.id === 'string' && guide.id.startsWith('bg_MOCK');
}

/**
 * MOCK: true for a simulated run from mock-job.js, so the page can label
 * it. Phase 4 deletes this function and the notices that use it.
 * @param {Record<string, any>} job
 * @returns {boolean}
 */
export function isSimulatedJob(job) {
  return typeof job?.id === 'string' && isMockRunId(job.id);
}
