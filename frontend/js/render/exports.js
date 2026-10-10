/**
 * The Export menu in the guide toolbar.
 *
 * The menu itself is plain HTML in guide.html. This file:
 * 1. Opens and closes it (button click; closes on Esc, a click outside, or
 *    when keyboard focus leaves it), like the header's mobile menu.
 * 2. Runs the formats that work now: JSON (a download made in the browser
 *    from the loaded guide) and Print / Save as PDF. The other formats are
 *    marked aria-disabled until Phase 8, when the backend builds them;
 *    clicking one explains why instead of doing nothing.
 */

import { slugify } from '../utils.js';
import { showToast } from '../toast.js';
import { brandName } from './brand.js';

/**
 * @param {HTMLElement} page
 * @param {Record<string, any>} guide
 * @param {{ mock: boolean }} options
 */
export function setUpExports(page, guide, { mock }) {
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

    if (item.getAttribute('aria-disabled') === 'true') {
      showToast('This format isn’t available yet. JSON and Print / Save as PDF work now.', { icon: 'info' });
      return;
    }

    // Close first, so the open menu never ends up in the printout.
    setOpen(false, { returnFocus: true });
    const format = item.getAttribute('data-export-format');
    if (format === 'json') downloadJson(guide, { mock });
    if (format === 'print') window.print();
  });
}

/**
 * Saves the guide as pretty-printed JSON, the same as the API's JSON export.
 *
 * In plain English: turn the guide into text, wrap it in a temporary file
 * object in memory (a Blob), point a hidden link at it with a file name, and
 * click that link. The browser then saves it like any download.
 *
 * @param {Record<string, any>} guide
 * @param {{ mock: boolean }} options Mock guides get a MOCK_ file name.
 */
function downloadJson(guide, { mock }) {
  const filename = `${mock ? 'MOCK_' : ''}${slugify(brandName(guide)) || 'brand'}-brand-guide.json`;
  const blob = new Blob([`${JSON.stringify(withFullAddresses(guide), null, 2)}\n`], { type: 'application/json' });
  const url = URL.createObjectURL(blob);

  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  // Free the memory once the browser has started the download.
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);

  showToast(`Downloading ${filename}`, { icon: 'download' });
}

/**
 * A copy of the guide where logos Swatchfin copied from a page have their
 * whole address ("/api/v1/guides/…/logos/1.svg" becomes
 * "https://…/api/v1/guides/…/logos/1.svg"), so the file works outside Swatchfin.
 * @param {Record<string, any>} guide
 * @returns {Record<string, any>}
 */
function withFullAddresses(guide) {
  const copy = structuredClone(guide);
  for (const asset of [copy.logo?.primary, ...(copy.logo?.alternates ?? [])]) {
    if (typeof asset?.url === 'string' && asset.url.startsWith('/')) {
      asset.url = new URL(asset.url, window.location.origin).href;
    }
  }
  return copy;
}
