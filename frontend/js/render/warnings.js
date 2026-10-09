/**
 * Warnings section: what Swatchfin couldn't find or verify.
 * Returns null when there are no warnings, and guide.js hides the section.
 */

import { el, createIcon, list, text } from './dom.js';

/**
 * @param {Record<string, any>} guide
 * @returns {HTMLElement | null}
 */
export function renderWarnings(guide) {
  const warnings = list(guide.warnings).map(text).filter(Boolean);
  if (warnings.length === 0) return null;

  const title = warnings.length === 1 ? '1 thing to know about this guide' : `${warnings.length} things to know about this guide`;

  return el('div', { className: 'sf-callout sf-callout--warning' }, [
    createIcon('triangle-alert', { className: 'sf-callout__icon' }),
    el('div', { className: 'sf-callout__body' }, [
      el('p', { className: 'sf-callout__title', text: title }),
      el('ul', { className: 'sf-callout__list' }, warnings.map((warning) => el('li', { text: warning }))),
    ]),
  ]);
}
