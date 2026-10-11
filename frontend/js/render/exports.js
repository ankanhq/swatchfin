/**
 * The Export menu in the guide toolbar.
 *
 * The menu itself is plain HTML in guide.html. This file:
 * 1. Opens and closes it (button click; closes on Esc, a click outside, or
 *    when keyboard focus leaves it), like the header's mobile menu.
 * 2. Greys out the formats this guide has nothing for (CSS without colours
 *    or fonts, a voice prompt without a tone of voice) and says why.
 * 3. Downloads the chosen format from the API and saves it, or opens the
 *    print dialog for Print / Save as PDF.
 */

import { getExport, GuideError } from '../api.js';
import { showToast } from '../toast.js';

/** How long an error toast shows: long enough to read two sentences. */
const MESSAGE_TOAST_MS = 7000;

const NO_STYLES = 'This guide has no colours or fonts.';
const NO_VOICE = 'This guide has no tone of voice or key messages.';

/**
 * What each format needs from the guide, and what to say when it isn't there.
 * The server checks the same things, and says so if it disagrees.
 * @type {Record<string, { has: (guide: Record<string, any>) => boolean, reason: string }>}
 */
const NEEDS = {
  css: { has: hasStyles, reason: NO_STYLES },
  tailwind: { has: hasStyles, reason: NO_STYLES },
  tokens: { has: hasStyles, reason: NO_STYLES },
  voice: { has: hasVoice, reason: NO_VOICE },
};

/**
 * @param {HTMLElement} page
 * @param {Record<string, any>} guide
 * @param {{ jobId: string, mock: boolean }} options jobId: the ID in the page address, which the API knows the guide by.
 */
export function setUpExports(page, guide, { jobId, mock }) {
  const menu = page.querySelector('[data-export]');
  const toggle = menu?.querySelector('[data-export-toggle]');
  const panel = menu?.querySelector('[data-export-panel]');
  if (!menu || !toggle || !panel) return;

  const isOpen = () => toggle.getAttribute('aria-expanded') === 'true';

  /**
   * @param {boolean} open
   * @param {{ returnFocus?: boolean }} [options] Put focus back on the Export button.
   */
  const setOpen = (open, { returnFocus = false } = {}) => {
    toggle.setAttribute('aria-expanded', String(open));
    menu.classList.toggle('sf-export--open', open);
    if (!open && returnFocus) toggle.focus();
  };

  markUnavailable(panel, guide);
  const note = panel.querySelector('[data-export-note]');
  if (mock && note) note.textContent = 'This is a sample guide, so every file says it is MOCK data.';

  // The button starts disabled in the HTML, until there is a guide to export.
  toggle.disabled = false;
  toggle.addEventListener('click', () => setOpen(!isOpen()));

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && isOpen()) setOpen(false, { returnFocus: true });
  });

  document.addEventListener('click', (event) => {
    if (isOpen() && event.target instanceof Node && !menu.contains(event.target)) setOpen(false);
  });

  menu.addEventListener('focusout', (event) => {
    const next = event.relatedTarget;
    if (isOpen() && next instanceof Node && !menu.contains(next)) setOpen(false);
  });

  panel.addEventListener('click', (event) => {
    const item = event.target instanceof Element ? event.target.closest('[data-export-format]') : null;
    if (!item) return;
    const format = item.getAttribute('data-export-format') ?? '';

    if (item.getAttribute('aria-disabled') === 'true') {
      const reason = NEEDS[format]?.reason ?? 'This format isn’t available.';
      showToast(`${reason} The warnings at the top of the guide say why.`, { icon: 'info', duration: MESSAGE_TOAST_MS });
      return;
    }

    // Close first, so the open menu never ends up in the printout.
    setOpen(false, { returnFocus: true });
    if (format === 'print') {
      window.print();
    } else {
      download(item, jobId, format);
    }
  });
}

/**
 * Greys out each format the guide has nothing for, with the reason as its
 * description. aria-disabled (not disabled) keeps the button focusable, so
 * keyboard and screen reader users can still find out why.
 * @param {HTMLElement} panel
 * @param {Record<string, any>} guide
 */
function markUnavailable(panel, guide) {
  for (const [format, { has, reason }] of Object.entries(NEEDS)) {
    if (has(guide)) continue;
    const item = panel.querySelector(`[data-export-format="${format}"]`);
    const description = item?.querySelector('[data-export-desc]');
    item?.setAttribute('aria-disabled', 'true');
    if (description) description.textContent = reason;
  }
}

/**
 * Asks the API for one format and saves the file it sends.
 * @param {Element} item The menu item, marked busy while the file is on its way.
 * @param {string} jobId
 * @param {string} format
 * @returns {Promise<void>}
 */
async function download(item, jobId, format) {
  if (item.getAttribute('aria-busy') === 'true') return; // already on its way
  item.setAttribute('aria-busy', 'true');
  try {
    const { blob, filename } = await getExport(jobId, format);
    saveFile(blob, filename);
    showToast(`Downloading ${filename}`, { icon: 'download' });
  } catch (error) {
    const message = error instanceof GuideError ? `${error.title}. ${error.message}` : 'The file couldn’t be downloaded. Try again.';
    showToast(message, { icon: 'circle-alert', tone: 'danger', duration: MESSAGE_TOAST_MS });
  } finally {
    item.removeAttribute('aria-busy');
  }
}

/**
 * Saves a file the page has in memory.
 *
 * In plain English: point a hidden link at the file (a Blob) with a file
 * name, and click that link. The browser then saves it like any download.
 *
 * @param {Blob} blob
 * @param {string} filename
 */
function saveFile(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  // Free the memory once the browser has started the download.
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/**
 * True when the guide has a colour or a named font: what CSS, Tailwind and tokens are made of.
 * @param {Record<string, any>} guide
 * @returns {boolean}
 */
function hasStyles(guide) {
  const colours = Array.isArray(guide.colors) ? guide.colors : [];
  const fonts = Array.isArray(guide.typography) ? guide.typography : [];
  return colours.length > 0 || fonts.some((font) => typeof font?.family === 'string' && font.family.trim() !== '');
}

/**
 * True when the guide has anything for a voice prompt: a summary, a trait
 * with a quote found on the site, the tone scales, do / don't, or a key
 * message found on the site.
 * @param {Record<string, any>} guide
 * @returns {boolean}
 */
function hasVoice(guide) {
  const voice = guide.voice ?? {};
  const messaging = guide.messaging ?? {};
  const found = (/** @type {any} */ item) => item?.verified === true;
  const filled = (/** @type {unknown} */ list) => Array.isArray(list) && list.length > 0;
  return Boolean(
    (typeof voice.summary === 'string' && voice.summary.trim()) ||
      (Array.isArray(voice.traits) && voice.traits.some((trait) => Array.isArray(trait?.evidence) && trait.evidence.some(found))) ||
      voice.spectrum ||
      filled(voice.do) ||
      filled(voice.dont) ||
      found(messaging.tagline) ||
      found(messaging.mission) ||
      (Array.isArray(messaging.value_props) && messaging.value_props.some(found)) ||
      filled(messaging.audience),
  );
}
