/**
 * The progress view on the guide page: seven steps that light up while a
 * guide is being made, the elapsed time and the TinyFish calls so far.
 *
 * The steps are plain HTML in guide.html (one <li data-step="…"> each).
 * This file only changes the parts that move:
 * - each step's data-status ("pending", "running", "done", "skipped" or
 *   "failed"), which the CSS uses for colours and the connecting line,
 * - the step's marker icon, its status word and the detail line from the
 *   backend (e.g. "Found duolingo.com"),
 * - the header: the query as the title, "Step 3 of 7" and the elapsed time,
 * - the TinyFish call counts and the Cancel link.
 * Screen readers hear each new step once, through the page's status region.
 */

import { el, createIcon, list, lookup, text } from './dom.js';

const STATUSES = ['pending', 'running', 'done', 'skipped', 'failed'];

/** Marker icon for each status. Waiting steps keep their own icon from the HTML. */
const STATUS_ICONS = { running: 'loader-circle', done: 'check', skipped: 'minus', failed: 'x' };

const STATUS_LABELS = { pending: 'Waiting', running: 'In progress', done: 'Done', skipped: 'Skipped', failed: 'Failed' };

/** Usage counter -> [one, many], e.g. "1 URL", "6 URLs". */
const USAGE_UNITS = {
  search_calls: ['call', 'calls'],
  fetch_urls: ['URL', 'URLs'],
  browser_sessions: ['session', 'sessions'],
};

/** Pause on the finished list before the guide replaces it, so the last tick is seen. */
const FINISH_PAUSE_MS = 600;

/**
 * Connects the progress view to the page and returns what guide.js needs:
 *   show(job)    fill in the header and start the elapsed-time clock
 *   update(job)  move the steps, counts and "Step 3 of 7" along
 *   finish()     wait a moment on the finished list (skipped with reduced motion)
 *   stop()       stop the clock
 *
 * In plain English: it finds the step elements once, remembers a few
 * things between updates (when the job started, which step was last read
 * out), and hands back four small functions that share that memory.
 *
 * @param {HTMLElement} page The <main> element.
 */
export function createProgressView(page) {
  const steps = [...page.querySelectorAll('[data-step]')].map((item) => ({
    item,
    name: item.getAttribute('data-step') ?? '',
    title: text(item.querySelector('[data-step-title]')?.textContent),
    // The step's own icon, e.g. "search", for the marker while it waits.
    icon: (item.querySelector('[data-step-marker] use')?.getAttribute('href') ?? '').split('#')[1] ?? '',
  }));
  const status = page.querySelector('[data-guide-status]');

  let startedAt = Date.now();
  let timer = 0;
  let announced = '';
  /** @type {{ step: HTMLElement, elapsed: HTMLElement } | null} */
  let facts = null;

  /** @param {Record<string, any>} job */
  function show(job) {
    const query = text(job.query);
    page.querySelector('[data-brand-eyebrow]').textContent = 'Generating brand guide';
    page.querySelector('[data-brand-name]').textContent = query || 'New brand guide';

    facts = { step: el('span'), elapsed: el('span') };
    page.querySelector('[data-brand-details]').replaceChildren(
      el('ul', { className: 'sf-guide-header__facts sf-guide-header__facts--progress' }, [
        el('li', { className: 'sf-guide-header__fact' }, [createIcon('list-checks', { size: 16 }), facts.step]),
        el('li', { className: 'sf-guide-header__fact' }, [createIcon('clock', { size: 16 }), facts.elapsed]),
        el('li', { className: 'sf-guide-header__fact', text: 'Most guides take about a minute' }),
      ]),
    );

    // Cancel goes back to the start page with the query still in the box.
    const cancel = page.querySelector('[data-progress-cancel]');
    if (cancel && query) cancel.setAttribute('href', `./?q=${encodeURIComponent(query)}#generate`);

    // The clock counts from the job's own start time, so it stays right after a reload.
    const started = Date.parse(job.started_at);
    startedAt = Number.isNaN(started) ? Date.now() : Math.min(started, Date.now());
    tick();
    window.clearInterval(timer);
    timer = window.setInterval(tick, 1000);
  }

  /** @param {Record<string, any>} job */
  function update(job) {
    const entries = list(job.steps);
    const failed = job.status === 'failed';

    steps.forEach((step) => {
      const entry = entries.find((candidate) => candidate?.name === step.name) ?? {};
      const state = STATUSES.includes(entry.status) ? entry.status : 'pending';
      setStepStatus(step, state, { failed });
      setStepDetail(step.item, text(entry.detail));
      setStepLabel(step.item, state, entry, { failed });
    });

    updateUsage(page, job.tinyfish_usage);
    updateStepFact(job);
    announceStep(job);
  }

  /** @returns {Promise<void>} */
  function finish() {
    const motion = document.documentElement.classList.contains('sf-motion');
    return new Promise((resolve) => window.setTimeout(resolve, motion ? FINISH_PAUSE_MS : 0));
  }

  function stop() {
    window.clearInterval(timer);
  }

  /** Updates "0:42 elapsed" once a second. */
  function tick() {
    if (facts) facts.elapsed.textContent = `${formatElapsed(Date.now() - startedAt)} elapsed`;
  }

  /**
   * "Step 3 of 7", "Starting" while queued, or "All 7 steps done".
   * @param {Record<string, any>} job
   */
  function updateStepFact(job) {
    if (!facts) return;
    const current = currentStepIndex();
    if (job.status === 'queued') facts.step.textContent = 'Starting';
    else if (current >= 0) facts.step.textContent = `Step ${current + 1} of ${steps.length}`;
    else if (job.status === 'complete') facts.step.textContent = `All ${steps.length} steps done`;
  }

  /**
   * Reads out the step that just started, once: "Step 4 of 7: Reading the pages."
   * The first message also says what is being generated.
   * @param {Record<string, any>} job
   */
  function announceStep(job) {
    const current = currentStepIndex();
    if (!status || current < 0 || steps[current].name === announced) return;

    const intro = announced === '' ? `Generating a brand guide for ${text(job.query) || 'your search'}. ` : '';
    announced = steps[current].name;
    status.textContent = `${intro}Step ${current + 1} of ${steps.length}: ${steps[current].title}.`;
  }

  /** @returns {number} Index of the running step, or -1. */
  function currentStepIndex() {
    return steps.findIndex((step) => step.item.getAttribute('data-status') === 'running');
  }

  return { show, update, finish, stop };
}

/**
 * Sets data-status and the marker icon. The icon only changes when the
 * status does, so the spinner never restarts in the middle of a turn.
 * @param {{ item: HTMLElement, icon: string }} step
 * @param {string} state
 * @param {{ failed: boolean }} options failed: the whole job has failed.
 */
function setStepStatus(step, state, { failed }) {
  step.item.toggleAttribute('data-not-started', failed && state === 'pending');
  if (step.item.getAttribute('data-status') === state) return;

  step.item.setAttribute('data-status', state);
  const marker = step.item.querySelector('[data-step-marker]');
  const icon = lookup(STATUS_ICONS, state) ?? step.icon;
  if (marker && icon) marker.replaceChildren(createIcon(icon));
}

/**
 * The live detail line under the step's description, hidden when empty.
 * @param {HTMLElement} item
 * @param {string} detail
 */
function setStepDetail(item, detail) {
  const line = item.querySelector('[data-step-detail]');
  if (!line) return;
  line.textContent = detail;
  line.hidden = detail === '';
}

/**
 * The status word: "Waiting", "In progress", "Done · 2s", "Skipped",
 * "Failed", or "Not started" for steps after a failure.
 * @param {HTMLElement} item
 * @param {string} state
 * @param {Record<string, any>} entry
 * @param {{ failed: boolean }} options
 */
function setStepLabel(item, state, entry, { failed }) {
  const label = item.querySelector('[data-step-status]');
  if (!label) return;

  let words = failed && state === 'pending' ? 'Not started' : STATUS_LABELS[state];
  if (state === 'done') {
    const took = Date.parse(entry.finished_at) - Date.parse(entry.started_at);
    if (took >= 0) words += ` · ${Math.max(1, Math.round(took / 1000))}s`;
  }
  label.textContent = words;
}

/**
 * Fills in "TinyFish calls so far": "1 call", "6 URLs", "1 session".
 * @param {HTMLElement} page
 * @param {unknown} usage
 */
function updateUsage(page, usage) {
  page.querySelectorAll('[data-usage]').forEach((cell) => {
    const key = cell.getAttribute('data-usage') ?? '';
    const units = lookup(USAGE_UNITS, key);
    const value = usage && typeof usage === 'object' ? usage[key] : 0;
    const count = Number.isInteger(value) && value > 0 ? value : 0;
    if (units) cell.textContent = `${count} ${count === 1 ? units[0] : units[1]}`;
  });
}

/**
 * 42000 -> "0:42", 75000 -> "1:15".
 * @param {number} ms
 * @returns {string}
 */
export function formatElapsed(ms) {
  const seconds = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}
