/**
 * Toasts: short confirmations such as "Copied #B5532A".
 *
 * The page has one toast region (role="status", aria-live="polite"), so
 * screen readers read each message out without moving focus. Only one toast
 * shows at a time; a new one replaces the old. Each disappears on its own.
 */

import { createIcon } from './utils.js';

const SHOW_MS = 2600;
const region = document.querySelector('[data-toast-region]');
let hideTimer = 0;

/**
 * Shows a toast.
 * @param {string} message
 * @param {{ icon?: string, tone?: 'default' | 'danger' }} [options]
 */
export function showToast(message, { icon = 'check', tone = 'default' } = {}) {
  if (!region) return;
  window.clearTimeout(hideTimer);

  const toast = document.createElement('div');
  toast.className = `sf-toast sf-toast--${tone}`;
  const text = document.createElement('span');
  text.textContent = message;
  toast.append(createIcon(icon, { size: 16 }), text);
  region.replaceChildren(toast);

  // Add the class on the next frame, so the CSS fade-in has a start state.
  window.requestAnimationFrame(() => toast.classList.add('is-visible'));

  hideTimer = window.setTimeout(() => {
    toast.classList.remove('is-visible');
    // Remove it once the fade-out (the slow duration token) has finished.
    window.setTimeout(() => toast.remove(), 400);
  }, SHOW_MS);
}
