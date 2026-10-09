/**
 * Small building blocks shared by the guide page renderers.
 *
 * Every piece of text from a brand guide goes into the page through
 * textContent (via el() below), never innerHTML. That way, even if a
 * website's text contains HTML or a <script> tag, it is shown as plain
 * text and never runs.
 */

import { createIcon, confidenceLevel, displayUrl, safeUrl } from '../utils.js';

export { createIcon };

/**
 * Creates an element in one line.
 *
 *   el('p', { className: 'sf-x', text: 'Hello' })
 *   el('ul', {}, [el('li', { text: 'One' }), el('li', { text: 'Two' })])
 *
 * @param {string} tag
 * @param {{ className?: string, text?: string, attrs?: Record<string, string> }} [options]
 *   attrs: plain attributes such as href or aria-label. Never pass "on..." handlers.
 * @param {Array<Node | string | null | undefined | false>} [children] Falsy items are skipped.
 * @returns {HTMLElement}
 */
export function el(tag, { className, text, attrs } = {}, children = []) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  if (attrs) {
    for (const [name, value] of Object.entries(attrs)) node.setAttribute(name, value);
  }
  for (const child of children) {
    if (child) node.append(child);
  }
  return node;
}

/**
 * A badge such as "High confidence". The word is always shown, so the level
 * never depends on colour alone. Returns null when there is no score.
 * @param {unknown} value Confidence from 0 to 1.
 * @returns {HTMLElement | null}
 */
export function confidenceBadge(value) {
  const confidence = confidenceLevel(value);
  if (!confidence) return null;
  // The exact score shows on hover and is read out by screen readers.
  return el('span', {
    className: `sf-badge sf-confidence sf-confidence--${confidence.level}`,
    attrs: { title: `Confidence ${confidence.percent}%` },
  }, [
    `${confidence.label} confidence`,
    el('span', { className: 'visually-hidden', text: ` (${confidence.percent}%)` }),
  ]);
}

/**
 * "Verified" (found word for word in the fetched text) or "Unverified".
 * @param {unknown} verified
 * @returns {HTMLElement}
 */
export function verifiedBadge(verified) {
  const ok = verified === true;
  return el('span', { className: `sf-badge sf-verified ${ok ? 'sf-verified--yes' : 'sf-verified--no'}` }, [
    createIcon(ok ? 'badge-check' : 'circle-alert', { size: 16 }),
    ok ? 'Verified' : 'Unverified',
  ]);
}

/**
 * A link to the page a fact came from, shown short ("example.com/about").
 * Unsafe or missing URLs come back as plain text, or null.
 * @param {unknown} url
 * @param {{ label?: string }} [options] Text to show instead of the short URL.
 * @returns {HTMLElement | null}
 */
export function sourceLink(url, { label } = {}) {
  const href = safeUrl(url);
  if (!href) return null;
  const text = label ?? displayUrl(href);
  return el('a', { className: 'sf-source-link', attrs: { href, rel: 'noopener noreferrer' } }, [
    el('span', { text }),
    createIcon('arrow-up-right', { size: 16 }),
  ]);
}

/**
 * The "nothing here" message for a missing part of the guide.
 * @param {string} title What is missing, e.g. "No logo found".
 * @param {string} [text] Why, or what that means for the reader.
 * @returns {HTMLElement}
 */
export function emptyState(title, text) {
  return el('div', { className: 'sf-empty' }, [
    createIcon('info', { size: 20, className: 'sf-empty__icon' }),
    el('div', {}, [
      el('p', { className: 'sf-empty__title', text: title }),
      text ? el('p', { className: 'sf-empty__text', text }) : null,
    ]),
  ]);
}

/**
 * A copy button for a value such as a hex code. guide.js handles the click
 * for every [data-copy] button on the page in one place.
 * @param {string} value Text that is copied.
 * @param {string} label What it is, for screen readers, e.g. "HEX".
 * @returns {HTMLButtonElement}
 */
export function copyButton(value, label) {
  const button = el('button', {
    className: 'sf-copy',
    attrs: { type: 'button', 'data-copy': value, 'aria-label': `Copy ${label} ${value}` },
  }, [
    el('span', { className: 'sf-copy__value', text: value }),
    createIcon('copy', { size: 16, className: 'sf-copy__icon' }),
  ]);
  return /** @type {HTMLButtonElement} */ (button);
}

/**
 * A <dt>/<dd> pair for a facts list (<dl class="sf-facts">). Spread it:
 *   el('dl', { className: 'sf-facts' }, [...fact('Format', 'SVG')])
 * @param {string} term
 * @param {Node | string} value
 * @returns {HTMLElement[]}
 */
export function fact(term, value) {
  return [el('dt', { text: term }), el('dd', {}, [value])];
}

/**
 * A titled group inside a section, e.g. "Traits" or "Value propositions".
 * Returns null when there is no content, so callers can pass it straight
 * into el()'s children.
 * @param {string} title
 * @param {Array<Node | null | false>} children
 * @returns {HTMLElement | null}
 */
export function subsection(title, children) {
  const content = children.filter(Boolean);
  if (content.length === 0) return null;
  return el('div', { className: 'sf-subsection' }, [el('h3', { className: 'sf-subsection__title', text: title }), ...content]);
}

/**
 * Sentence case for labels from the data: "primary button background" ->
 * "Primary button background".
 * @param {string} text
 * @returns {string}
 */
export function sentenceCase(text) {
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : text;
}

/**
 * Looks up a key in one of our own label tables. Website data could contain
 * keys like "constructor" that every JavaScript object has, so only the
 * table's own entries count.
 * @template T
 * @param {Record<string, T>} table
 * @param {unknown} key
 * @returns {T | undefined}
 */
export function lookup(table, key) {
  return typeof key === 'string' && Object.hasOwn(table, key) ? table[key] : undefined;
}

/**
 * Returns the array if it is one, otherwise an empty array. Guide data can
 * be partial, so every list is read through this.
 * @template T
 * @param {T[] | unknown} value
 * @returns {T[]}
 */
export function list(value) {
  return Array.isArray(value) ? value : [];
}

/**
 * Returns the text if it is a non-empty string, otherwise "".
 * @param {unknown} value
 * @returns {string}
 */
export function text(value) {
  return typeof value === 'string' ? value.trim() : '';
}
