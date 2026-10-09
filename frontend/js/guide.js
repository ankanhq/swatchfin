/**
 * Guide page (guide.html).
 *
 * The page is always in one of six states, kept in <main data-state="…">.
 * The CSS shows the right parts for each:
 *   loading  grey placeholders while the first answer is on its way
 *   running  the progress view: seven steps, elapsed time, TinyFish calls
 *   ready    the finished guide
 *   failed   the job stopped at a step: the steps, the reason, Try again
 *   error    nothing to show (guide not found, offline, unreadable data)
 *   empty    the address doesn't name a guide (no ?id= and no ?q=)
 *
 * What happens, in order:
 * 1. Read the address. ?q=… (from the start page's form) starts a new job,
 *    and the address changes to ?id=… so a reload follows the same job
 *    instead of starting another. ?id=… opens an existing job.
 * 2. Ask for the job's status every 1.5 seconds (api.js) and move the
 *    steps along. A guide that is already finished skips the progress view.
 * 3. When the job is complete, draw every section. Each section is drawn
 *    on its own, so if one fails the rest of the guide still shows.
 * 4. Switch on the extras: copy buttons, the "On this page" highlight and
 *    the Export menu.
 * guide-guard.js makes sure the loading state ends after 15 seconds at most.
 */

import { startGuide, watchGuide, isMockGuide, isSimulatedJob, GuideError } from './api.js';
import { observeMotion } from './motion.js';
import { showToast } from './toast.js';
import { copyText, parseQuery } from './utils.js';
import { emptyState } from './render/dom.js';
import { brandName, renderBrandHeader, renderHeaderError, renderNotice, renderToolbar } from './render/brand.js';
import { createProgressView } from './render/progress.js';
import { renderWarnings } from './render/warnings.js';
import { renderLogo } from './render/logo.js';
import { renderColors } from './render/colors.js';
import { renderContrast } from './render/contrast.js';
import { renderTypography } from './render/typography.js';
import { renderVoice } from './render/voice.js';
import { renderMessaging } from './render/messaging.js';
import { renderSources } from './render/sources.js';
import { setUpExports } from './render/exports.js';

/**
 * Section name (data-render="…" in guide.html) -> function that draws it.
 * Each function gets the guide and returns the section's content, or null
 * when there is nothing to show (the section is then hidden).
 * @type {Record<string, (guide: Record<string, any>) => Node | null>}
 */
const SECTIONS = {
  warnings: renderWarnings,
  logo: renderLogo,
  colours: renderColors,
  contrast: renderContrast,
  typography: renderTypography,
  voice: renderVoice,
  messaging: renderMessaging,
  sources: renderSources,
};

const SITE_NAME = 'Swatchfin';

const page = document.querySelector('[data-guide]');

if (page) {
  start(page);
}

/**
 * @param {HTMLElement} page
 */
async function start(page) {
  setUpCopyButtons(page);
  const request = readRequest();

  if (request.kind === 'empty') {
    showEmpty(page);
    return;
  }
  if (request.kind === 'invalid') {
    // The retry button goes back to the start page with the text in the box, to fix it there.
    const error = new GuideError('This search can’t be used', request.error, { retryLabel: 'Edit the search' });
    showError(page, error, { retryHref: `./?q=${encodeURIComponent(request.raw)}#generate` });
    return;
  }

  let id = request.id;
  if (request.kind === 'query') {
    try {
      ({ id } = await startGuide(request.query));
    } catch (error) {
      showError(page, error);
      return;
    }
    showJobInAddress(id);
  }

  const progress = createProgressView(page);
  let job;
  try {
    job = await watchGuide(id, {
      onUpdate: (update) => {
        // Only a job that is still being made gets the progress view.
        const working = update.status === 'queued' || update.status === 'running';
        if (working && page.dataset.state === 'loading') showRunning(page, update, progress);
        if (page.dataset.state === 'running') progress.update(update);
      },
    });
  } catch (error) {
    progress.stop();
    showError(page, error);
    return;
  }
  progress.stop();

  if (job.status === 'failed') {
    showFailed(page, job, progress);
    return;
  }
  if (page.dataset.state === 'running') await progress.finish();
  showGuide(page, job);
}

/**
 * Reads ?q= or ?id= from the address. ?q= wins when both are there.
 * @returns {{ kind: 'query', query: string } | { kind: 'id', id: string } | { kind: 'invalid', error: string, raw: string } | { kind: 'empty' }}
 */
function readRequest() {
  const params = new URLSearchParams(window.location.search);

  const query = params.get('q');
  if (query !== null && query.trim() !== '') {
    // The start page already checks the query, but this address can also be typed or shared.
    const result = parseQuery(query);
    return result.ok ? { kind: 'query', query: result.value } : { kind: 'invalid', error: result.error, raw: query };
  }

  const id = (params.get('id') ?? '').trim();
  return id ? { kind: 'id', id } : { kind: 'empty' };
}

/**
 * Swaps ?q=… for ?id=… in the address bar, without loading a new page, so
 * reloading or sharing the address shows this job instead of starting a
 * new one.
 * @param {string} id
 */
function showJobInAddress(id) {
  const url = new URL(window.location.href);
  url.searchParams.delete('q');
  url.searchParams.set('id', id);
  window.history.replaceState(null, '', url);
}

/**
 * Switches to the progress view.
 * @param {HTMLElement} page
 * @param {Record<string, any>} job
 * @param {ReturnType<typeof createProgressView>} progress
 */
function showRunning(page, job, progress) {
  renderNotice(page, isSimulatedJob(job) ? 'simulated-run' : null); // MOCK: label simulated runs
  progress.show(job);
  // No message here: the progress view reads out the first step itself.
  setState(page, 'running');
  document.title = `Generating “${job.query}” · ${SITE_NAME}`;
}

/**
 * Draws the finished guide.
 * @param {HTMLElement} page
 * @param {Record<string, any>} job A complete job, with its guide.
 */
function showGuide(page, job) {
  // guide-guard.js may already have ended the wait ("This is taking too
  // long"). Keep that message rather than swapping the page under the reader.
  if (!isWaiting(page)) return;

  const guide = job.guide;
  const mock = isMockGuide(guide);
  const fromProgress = page.dataset.state === 'running';

  // MOCK: a simulated run says that the guide is the sample, not the query.
  let notice = mock ? 'sample' : null;
  if (mock && isSimulatedJob(job)) notice = 'simulated-result';
  renderNotice(page, notice, { query: job.query });

  const focused = document.activeElement;
  renderBrandHeader(page, guide, { mock });
  renderToolbar(page, guide);
  renderSections(page, guide);

  // The printed guide shows where to find it again.
  const printUrl = page.querySelector('[data-print-url]');
  if (printUrl) printUrl.textContent = window.location.href;

  setState(page, 'ready', `Brand guide for ${brandName(guide)} ${fromProgress ? 'is ready' : 'loaded'}.`);
  document.title = `${brandName(guide)} · Brand guide · ${SITE_NAME}`;

  if (fromProgress) {
    // The progress view is gone: start reading the guide from the top.
    window.scrollTo({ top: 0, behavior: 'instant' });
    keepFocus(page, focused);
  }

  observeMotion(page);
  setUpTableOfContents(page);
  setUpExports(page, guide, { mock });
}

/**
 * Shows a job that stopped at one of its steps.
 * @param {HTMLElement} page
 * @param {Record<string, any>} job
 * @param {ReturnType<typeof createProgressView>} progress
 */
function showFailed(page, job, progress) {
  if (!isWaiting(page)) return;
  const focused = document.activeElement;
  const query = typeof job.query === 'string' ? job.query : '';

  progress.update(job); // marks the failed step, and "Not started" after it
  renderNotice(page, isSimulatedJob(job) ? 'simulated-failure' : null); // MOCK

  const error = {
    title: typeof job.error?.title === 'string' && job.error.title ? job.error.title : 'The guide couldn’t be finished',
    message:
      typeof job.error?.message === 'string' && job.error.message
        ? job.error.message
        : 'Swatchfin stopped before the guide was complete. Try again, or start a new guide.',
  };
  renderHeaderError(page, error, {
    eyebrow: query ? `Guide for “${query}”` : 'Brand guide',
    // Try again starts a new job for the same query.
    retryHref: query ? `guide.html?q=${encodeURIComponent(query)}` : undefined,
  });

  setState(page, 'failed', `${error.title}. ${error.message}`);
  document.title = `${error.title} · ${SITE_NAME}`;
  keepFocus(page, focused);
}

/**
 * The address doesn't name a guide.
 * @param {HTMLElement} page
 */
function showEmpty(page) {
  page.querySelector('[data-brand-name]').textContent = 'No guide to show';
  setState(page, 'empty', 'No guide to show.');
  document.title = `No guide to show · ${SITE_NAME}`;
}

/**
 * Shows the error version of the page.
 * @param {HTMLElement} page
 * @param {unknown} error
 * @param {{ retryHref?: string }} [options] Where the retry button goes (default: this address again).
 */
function showError(page, error, { retryHref } = {}) {
  if (!isWaiting(page)) return; // the time limit already showed an error
  const shown =
    error instanceof GuideError
      ? error
      : new GuideError('Something went wrong', 'The guide couldn’t be shown. Try reloading the page.');
  if (!(error instanceof GuideError)) console.error('Swatchfin: unexpected error while loading the guide.', error);

  const focused = document.activeElement;
  renderNotice(page, null);
  renderHeaderError(page, shown, { retryHref });
  setState(page, 'error', shown.title);
  document.title = `${shown.title} · ${SITE_NAME}`;
  keepFocus(page, focused);
}

/**
 * True while the page is still waiting for a result (loading or running).
 * @param {HTMLElement} page
 * @returns {boolean}
 */
function isWaiting(page) {
  return page.dataset.state === 'loading' || page.dataset.state === 'running';
}

/**
 * Draws every section. A section that throws shows a short message instead,
 * so one bad field never blanks the whole guide.
 * @param {HTMLElement} page
 * @param {Record<string, any>} guide
 */
function renderSections(page, guide) {
  for (const [name, render] of Object.entries(SECTIONS)) {
    const body = page.querySelector(`[data-render="${name}"]`);
    const section = body?.closest('section');
    if (!body || !section) continue;

    let content;
    try {
      content = render(guide);
    } catch (error) {
      console.error(`Swatchfin: the ${name} section could not be drawn.`, error);
      content = emptyState('This section couldn’t be shown', 'Part of the guide data is in an unexpected format.');
    }

    if (content) {
      body.replaceChildren(content);
    } else {
      section.hidden = true;
      page.querySelector(`[data-toc-item="${name}"]`)?.setAttribute('hidden', '');
    }
  }

  const count = Array.isArray(guide.warnings) ? guide.warnings.length : 0;
  const counter = page.querySelector('[data-toc-warning-count]');
  if (counter && count > 0) counter.textContent = String(count);
}

/**
 * Sets data-state, which the CSS uses to show the right parts, and
 * announces the change to screen readers.
 * @param {HTMLElement} page
 * @param {'running' | 'ready' | 'failed' | 'error' | 'empty'} state
 * @param {string} [message] Read out by screen readers.
 */
function setState(page, state, message) {
  page.dataset.state = state;
  page.removeAttribute('aria-busy');
  const status = page.querySelector('[data-guide-status]');
  if (status && message) status.textContent = message;
}

/**
 * When a state change hides the element that had keyboard focus (say,
 * the Cancel button), focus would fall back to the top of the document.
 * Put it on the page title instead, so keyboard and screen reader users
 * carry on from the new content.
 * @param {HTMLElement} page
 * @param {Element | null} focused The element that had focus before the change.
 */
function keepFocus(page, focused) {
  // Nothing had focus (the visitor hasn't tabbed into the page yet): leave it.
  if (!focused || focused === document.body) return;
  // getClientRects() is empty for an element that is no longer displayed.
  if (focused.getClientRects().length > 0) return;
  const title = page.querySelector('[data-brand-name]');
  if (!title) return;
  title.setAttribute('tabindex', '-1'); // focusable by script only, not by Tab
  title.focus({ preventScroll: true });
}

/**
 * One click handler for every copy button ([data-copy]) on the page,
 * including ones drawn later. Shows a toast, and briefly swaps the copy
 * icon for a tick.
 * @param {HTMLElement} page
 */
function setUpCopyButtons(page) {
  page.addEventListener('click', async (event) => {
    const button = event.target instanceof Element ? event.target.closest('[data-copy]') : null;
    if (!button) return;

    const value = button.getAttribute('data-copy') ?? '';
    if (!(await copyText(value))) {
      showToast(`Couldn’t copy ${value}: the browser blocked the clipboard.`, { icon: 'circle-alert', tone: 'danger' });
      return;
    }

    showToast(`Copied ${value}`);
    const use = button.querySelector('.sf-copy__icon use, [data-copy-icon] use');
    if (use) {
      const original = use.getAttribute('href') ?? '';
      use.setAttribute('href', original.replace(/#.*$/, '#check'));
      window.setTimeout(() => use.setAttribute('href', original), 1500);
    }
  });
}

/**
 * Highlights the "On this page" link of the section being read.
 *
 * In plain English: the current section is the last one whose top edge has
 * scrolled above a line 30% down the window. At the very bottom of the page
 * the last section wins, even if it is too short to reach that line. The
 * matching link gets aria-current, which the CSS styles.
 * @param {HTMLElement} page
 */
function setUpTableOfContents(page) {
  const links = [...page.querySelectorAll('[data-toc] a[href^="#"]')];
  const targets = links
    .map((link) => document.getElementById(link.hash.slice(1)))
    .filter((target) => target && !target.hidden);
  if (targets.length === 0) return;

  let current = null;
  let queued = false;

  const update = () => {
    queued = false;
    const line = window.innerHeight * 0.3;
    const atBottom = window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2;

    let next = targets[0];
    if (atBottom) {
      next = targets[targets.length - 1];
    } else {
      for (const target of targets) {
        if (target.getBoundingClientRect().top <= line) next = target;
      }
    }

    if (next === current) return;
    current = next;
    links.forEach((link) => {
      if (link.hash === `#${current.id}`) link.setAttribute('aria-current', 'true');
      else link.removeAttribute('aria-current');
    });
  };

  // Work out the highlight at most once per frame while scrolling.
  const queue = () => {
    if (!queued) {
      queued = true;
      window.requestAnimationFrame(update);
    }
  };

  update();
  window.addEventListener('scroll', queue, { passive: true });
  window.addEventListener('resize', queue, { passive: true });
}
