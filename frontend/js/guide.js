/**
 * Guide page (guide.html).
 *
 * What happens, in order:
 * 1. Read the address: ?id=… is a saved guide, ?q=… comes from the start
 *    page's form. Until the backend exists (Phase 4) both show the mock guide.
 * 2. Load the guide (api.js). The page shows grey placeholder blocks meanwhile.
 * 3. Fill each section. Each section is drawn on its own, so if one fails
 *    the rest of the guide still shows.
 * 4. Switch on the extras: copy buttons and the "On this page" highlight.
 * If loading fails, the header turns into a clear error with a way forward.
 */

import { loadGuide, isMockGuide, GuideError, MOCK_ID } from './api.js';
import { observeMotion } from './motion.js';
import { showToast } from './toast.js';
import { copyText } from './utils.js';
import { emptyState } from './render/dom.js';
import { brandName, renderBrandHeader, renderHeaderError, renderNotice, renderToolbar } from './render/brand.js';
import { renderWarnings } from './render/warnings.js';
import { renderLogo } from './render/logo.js';
import { renderColors } from './render/colors.js';
import { renderContrast } from './render/contrast.js';
import { renderTypography } from './render/typography.js';
import { renderVoice } from './render/voice.js';
import { renderMessaging } from './render/messaging.js';
import { renderSources } from './render/sources.js';

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

const page = document.querySelector('[data-guide]');

if (page) {
  start(page);
}

/**
 * @param {HTMLElement} page
 */
async function start(page) {
  const request = readRequest();
  setUpCopyButtons(page);

  let guide;
  try {
    guide = await loadGuide(request.id);
  } catch (error) {
    showError(page, error);
    return;
  }

  const mock = isMockGuide(guide);
  renderNotice(page, { mock, query: request.query });
  renderBrandHeader(page, guide, { mock });
  renderToolbar(page, guide);
  renderSections(page, guide);

  setState(page, 'ready', `Brand guide for ${brandName(guide)} loaded.`);
  observeMotion(page);
  setUpTableOfContents(page);
}

/**
 * Reads ?id= and ?q= from the address.
 * @returns {{ id: string, query: string }}
 */
function readRequest() {
  const params = new URLSearchParams(window.location.search);
  const query = (params.get('q') ?? '').trim().slice(0, 200);
  const id = (params.get('id') ?? '').trim();
  // A query can't be generated yet, so it shows the mock guide (with a notice).
  return { id: query || !id ? MOCK_ID : id, query };
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
 * Shows the error version of the page.
 * @param {HTMLElement} page
 * @param {unknown} error
 */
function showError(page, error) {
  const shown =
    error instanceof GuideError
      ? error
      : new GuideError('Something went wrong', 'The guide couldn’t be shown. Try reloading the page.');
  if (!(error instanceof GuideError)) console.error('Swatchfin: unexpected error while loading the guide.', error);

  renderHeaderError(page, shown);
  setState(page, 'error', shown.title);
}

/**
 * Sets data-state ("loading", "ready" or "error"), which the CSS uses to
 * show the right parts, and announces the change to screen readers.
 * @param {HTMLElement} page
 * @param {'ready' | 'error'} state
 * @param {string} message
 */
function setState(page, state, message) {
  page.dataset.state = state;
  page.removeAttribute('aria-busy');
  const status = page.querySelector('[data-guide-status]');
  if (status) status.textContent = message;
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
