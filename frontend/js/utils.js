/**
 * Small shared helpers for Swatchfin pages.
 * Pure functions where possible, so they are easy to test.
 */

/** Longest query we accept: a company name or one URL. */
export const MAX_QUERY_LENGTH = 200;

/** Path to the Lucide icon sprite, relative to the pages in /frontend. */
const ICON_SPRITE = 'assets/icons/icons.svg';

// "https://..." or "http://..." (any scheme followed by //).
const HAS_SCHEME = /^[a-z][a-z0-9+.-]*:\/\//i;
// Schemes that are never web pages, typed without "//" (e.g. "javascript:").
const UNSAFE_SCHEME = /^(javascript|data|vbscript|file|blob|mailto|ftp|tel):/i;
// Looks like a domain: no spaces, a dot, then at least two letters,
// optionally followed by a port or a path. Matches "stripe.com" and
// "www.stripe.com/about", but not "St. John's".
const DOMAIN_LIKE = /^[^\s/]+\.[a-z]{2,}(:\d+)?([/?#]\S*)?$/i;
// Company names: letters and numbers in any language, plus spaces and the
// punctuation real names use (Ben & Jerry's, Yahoo!, Marks & Spencer, L'Oréal).
const NAME_PATTERN = /^[\p{L}\p{N}][\p{L}\p{M}\p{N} &.,'’!+()-]*$/u;

/**
 * @typedef {{ ok: true, kind: 'url' | 'name', value: string }} QueryOk
 * @typedef {{ ok: false, error: string }} QueryError
 */

/**
 * Checks what the visitor typed into "Company name or URL".
 *
 * In plain English: trim the text, then decide if it is a web address
 * (has "://" or looks like "stripe.com") or a company name, and check it
 * against the rules for that kind. Returns either the cleaned value or a
 * message that explains what to fix.
 *
 * @param {unknown} raw The text from the input.
 * @returns {QueryOk | QueryError}
 */
export function parseQuery(raw) {
  // Trim and squeeze repeated spaces ("  Ben  &  Jerry's " -> "Ben & Jerry's").
  const value = String(raw ?? '').trim().replace(/\s+/g, ' ');

  if (value === '') {
    return { ok: false, error: 'Enter a company name or a website address.' };
  }
  if (value.length > MAX_QUERY_LENGTH) {
    return { ok: false, error: `Keep it under ${MAX_QUERY_LENGTH} characters: one company name or one URL.` };
  }

  if (HAS_SCHEME.test(value) || UNSAFE_SCHEME.test(value) || DOMAIN_LIKE.test(value)) {
    return parseUrl(value);
  }

  if (!NAME_PATTERN.test(value)) {
    return {
      ok: false,
      error: 'Company names can use letters, numbers, spaces and & . , \' ! + ( ) - only.',
    };
  }
  return { ok: true, kind: 'name', value };
}

/**
 * Checks a web address. Adds "https://" when the visitor left it out.
 * Only public http(s) addresses pass.
 * @param {string} value
 * @returns {QueryOk | QueryError}
 */
function parseUrl(value) {
  const withScheme = HAS_SCHEME.test(value) || UNSAFE_SCHEME.test(value) ? value : `https://${value}`;

  let url;
  try {
    url = new URL(withScheme);
  } catch {
    return { ok: false, error: 'That doesn’t look like a valid web address. Try something like stripe.com.' };
  }

  if (url.protocol !== 'http:' && url.protocol !== 'https:') {
    return { ok: false, error: 'Only website links that start with http:// or https:// work.' };
  }
  if (url.username || url.password) {
    return { ok: false, error: 'Remove the username or password from the link.' };
  }
  // A public site needs a dot in its host name ("localhost" or "intranet" won't do).
  if (!url.hostname.includes('.')) {
    return { ok: false, error: 'Use a public website address, like stripe.com.' };
  }
  return { ok: true, kind: 'url', value };
}

/**
 * Builds an icon element that points into the Lucide sprite, without using
 * innerHTML. Decorative by default (hidden from screen readers).
 *
 * @param {string} name Icon id in the sprite, e.g. "circle-alert".
 * @param {{ size?: 16 | 20 | 24, className?: string }} [options]
 * @returns {SVGSVGElement}
 */
export function createIcon(name, { size = 20, className = '' } = {}) {
  const SVG_NS = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(SVG_NS, 'svg');
  const classes = ['sf-icon'];
  if (size !== 20) classes.push(`sf-icon--${size}`);
  if (className) classes.push(className);
  svg.setAttribute('class', classes.join(' '));
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('focusable', 'false');

  const use = document.createElementNS(SVG_NS, 'use');
  use.setAttribute('href', `${ICON_SPRITE}#${name}`);
  svg.append(use);
  return svg;
}
