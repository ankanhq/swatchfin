/**
 * Small shared helpers for Swatchfin pages.
 * Pure functions where possible, so they are easy to test.
 */

/** Longest query we accept: a company name or one URL. */
export const MAX_QUERY_LENGTH = 200;

/**
 * Full address of the Lucide icon sprite. It is worked out from where this
 * file lives (js/utils.js -> assets/icons/icons.svg), not from the page's
 * address, so icons also load on the 404 page, which the server can show
 * at any address, such as /some/old/link.
 */
const ICON_SPRITE = new URL('../assets/icons/icons.svg', import.meta.url).href;

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

/* --------------------------------------------------------------------------
   Helpers for showing website data safely (guide page).
   Everything in a brand guide comes from someone else's website, so it is
   treated as untrusted: URLs and colours are checked before they are used.
   -------------------------------------------------------------------------- */

const HEX_COLOR = /^#[0-9a-f]{6}$/i;

/**
 * Returns a full, safe link for a URL from the guide, or null.
 *
 * In plain English: turn the value into a full address (relative ones like
 * "mock/logo.svg" are resolved against this page), and only accept it if it
 * is an http or https address. Anything else, such as "javascript:...",
 * gives null so it never ends up in an href or src.
 *
 * @param {unknown} value
 * @returns {string | null}
 */
export function safeUrl(value) {
  if (typeof value !== 'string' || value.trim() === '') return null;
  try {
    const url = new URL(value, window.location.href);
    return url.protocol === 'http:' || url.protocol === 'https:' ? url.href : null;
  } catch {
    return null;
  }
}

/**
 * Shortens a URL for display: "https://www.example.com/about/" -> "example.com/about".
 * @param {string} href
 * @returns {string}
 */
export function displayUrl(href) {
  try {
    const url = new URL(href);
    const host = url.hostname.replace(/^www\./, '');
    const path = url.pathname.replace(/\/$/, '');
    return host + path + url.search;
  } catch {
    return href;
  }
}

/**
 * True for a six-digit hex colour such as "#B5532A". Colours are checked
 * with this before they are put into CSS.
 * @param {unknown} value
 * @returns {value is string}
 */
export function isHexColor(value) {
  return typeof value === 'string' && HEX_COLOR.test(value);
}

/**
 * Formats an ISO date such as "2026-10-09T10:24:00Z" for people,
 * e.g. "9 October 2026". Returns "" if the date is missing or invalid.
 * @param {unknown} iso
 * @param {{ withTime?: boolean }} [options] Also show the time, e.g. "10:24".
 * @returns {string}
 */
export function formatDate(iso, { withTime = false } = {}) {
  if (typeof iso !== 'string') return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  const options = withTime
    ? { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }
    : { day: 'numeric', month: 'long', year: 'numeric' };
  return new Intl.DateTimeFormat('en-GB', options).format(date);
}

/**
 * Turns a confidence score from 0 to 1 into a level people can read.
 * High is 0.8 and above, medium 0.5 and above, low below that.
 * @param {unknown} value
 * @returns {{ level: 'high' | 'medium' | 'low', label: string, percent: number } | null}
 */
export function confidenceLevel(value) {
  if (typeof value !== 'number' || Number.isNaN(value)) return null;
  const score = Math.min(Math.max(value, 0), 1);
  const percent = Math.round(score * 100);
  if (score >= 0.8) return { level: 'high', label: 'High', percent };
  if (score >= 0.5) return { level: 'medium', label: 'Medium', percent };
  return { level: 'low', label: 'Low', percent };
}

/**
 * Copies text to the clipboard. Resolves to true if it worked.
 * The Clipboard API only works on https or localhost, and the visitor's
 * browser can refuse it, so a failure is a normal outcome, not an error.
 * @param {string} text
 * @returns {Promise<boolean>}
 */
export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

/**
 * Makes a safe file name part: "Northwind Roasters" -> "northwind-roasters".
 * @param {unknown} value
 * @returns {string}
 */
export function slugify(value) {
  return String(value ?? '')
    .toLowerCase()
    .normalize('NFKD')
    .replace(/[^\w\s.-]/g, '')
    .trim()
    .replace(/[\s_.]+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '');
}
