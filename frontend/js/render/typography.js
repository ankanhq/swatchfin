/**
 * Typography section: one card per font role (headings, body, interface,
 * code) with a live specimen, the weights and sizes the site uses, and the
 * fallback fonts.
 *
 * Showing the specimen in the real font:
 * 1. If this page already has the font (Swatchfin itself uses Inter), use it.
 * 2. Otherwise, if the family is on Google Fonts (checked against
 *    assets/data/google-fonts.json, built by `npm run fonts`), load just the
 *    weights it needs from there.
 * 3. Otherwise the specimen uses the site's fallback fonts, and says so.
 * The card always states which of these happened, so nobody mistakes a
 * fallback for the real thing.
 */

import { el, createIcon, confidenceBadge, emptyState, fact, list, lookup, text } from './dom.js';
import { brandName } from './brand.js';

const ROLE_LABELS = { heading: 'Headings', body: 'Body text', ui: 'Interface', mono: 'Code' };

const WEIGHT_NAMES = {
  100: 'Thin', 200: 'ExtraLight', 300: 'Light', 400: 'Regular', 500: 'Medium',
  600: 'SemiBold', 700: 'Bold', 800: 'ExtraBold', 900: 'Black',
};

const ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ abcdefghijklmnopqrstuvwxyz 0123456789';
const FONT_LIST_URL = 'assets/data/google-fonts.json';

// Font names may only contain letters, numbers, spaces, "-" and "_" before
// they go into CSS or a URL; fallback stacks may also contain commas and quotes.
const SAFE_FAMILY = /^[\p{L}\p{N} _-]{1,64}$/u;
const SAFE_STACK = /^[\p{L}\p{N} ,"'_-]{1,200}$/u;

/**
 * @param {Record<string, any>} guide
 * @returns {HTMLElement}
 */
export function renderTypography(guide) {
  const fonts = list(guide.typography).filter((font) => text(font?.family));
  if (fonts.length === 0) {
    return emptyState('No fonts found', 'This guide has no fonts read from the live homepage. The warnings at the top say why.');
  }
  const samples = sampleTexts(guide);
  return el('div', { className: 'sf-type-list' }, fonts.map((font) => fontCard(font, samples)));
}

/**
 * What each specimen says. Real words from the brand where the guide has
 * them (the verified tagline, a value proposition), otherwise the alphabet.
 * @param {Record<string, any>} guide
 * @returns {Record<string, string>}
 */
function sampleTexts(guide) {
  const tagline = guide.messaging?.tagline;
  const firstProp = list(guide.messaging?.value_props).find((prop) => prop?.verified === true && text(prop.quote));
  return {
    heading: (tagline?.verified === true && text(tagline.text)) || brandName(guide),
    body: text(firstProp?.quote) || ALPHABET,
    ui: ALPHABET,
    mono: ALPHABET,
  };
}

/**
 * @param {Record<string, any>} font
 * @param {Record<string, string>} samples
 * @returns {HTMLElement}
 */
function fontCard(font, samples) {
  const role = lookup(ROLE_LABELS, font.role) ? font.role : 'body';
  const family = text(font.family);
  const weights = validWeights(font.weights);
  const sizes = list(font.sizes_px).filter((size) => Number.isFinite(size) && size > 0);
  const fallback = text(font.fallback_stack);

  const status = el('p', { className: 'sf-type__status' });
  const specimen = el('div', { className: 'sf-type__specimen' }, [
    el('span', { className: 'sf-type__aa', text: 'Aa', attrs: { 'aria-hidden': 'true' } }),
    el('p', { className: 'sf-type__sample', text: samples[role] }),
  ]);

  // The specimen asks for the real font first, then the site's fallbacks.
  const safeFamily = SAFE_FAMILY.test(family) ? `"${family}"` : '';
  const safeStack = SAFE_STACK.test(fallback) ? fallback : role === 'mono' ? 'monospace' : 'sans-serif';
  specimen.style.setProperty('--sf-type-family', [safeFamily, safeStack].filter(Boolean).join(', '));
  specimen.style.setProperty('--sf-type-weight', String(weights[0] ?? 400));

  const card = el('article', { className: `sf-type sf-type--${role}` }, [
    specimen,
    el('div', { className: 'sf-type__info' }, [
      el('div', { className: 'sf-type__head' }, [
        el('p', { className: 'sf-type__role', text: ROLE_LABELS[role] }),
        el('h3', { className: 'sf-type__family', text: family }),
        confidenceBadge(font.confidence),
      ]),
      el('dl', { className: 'sf-facts' }, [
        ...fact('Weights', weights.length ? weights.map((w) => `${w} ${WEIGHT_NAMES[w]}`).join(', ') : 'Not detected'),
        ...fact('Sizes', sizes.length ? `${sizes.join(' · ')} px` : 'Not detected'),
        ...fact('Fallback', fallback ? el('code', { className: 'sf-type__stack', text: fallback }) : 'None given'),
        ...fact('Web font', font.is_webfont === true ? 'Yes, loaded by the site' : 'No, a system font'),
      ]),
      status,
    ]),
  ]);

  showInRealFont(specimen, status, family, weights);
  return card;
}

/**
 * Keeps whole-hundred weights from 100 to 900, sorted, without repeats.
 * @param {unknown} value
 * @returns {number[]}
 */
function validWeights(value) {
  const weights = list(value).filter((w) => Number.isInteger(w) && w >= 100 && w <= 900 && w % 100 === 0);
  return [...new Set(weights)].sort((a, b) => a - b);
}

/**
 * Tries to show the specimen in the real font and updates the status line.
 * @param {HTMLElement} specimen
 * @param {HTMLElement} status
 * @param {string} family
 * @param {number[]} weights
 */
async function showInRealFont(specimen, status, family, weights) {
  setStatus(status, 'loader-circle', `Checking whether ${family} can be shown here…`, 'checking');

  const result = SAFE_FAMILY.test(family) ? await loadFamily(family, weights) : null;

  if (result) {
    specimen.style.setProperty('--sf-type-weight', String(result.weight));
    const where = result.from === 'google' ? ', loaded from Google Fonts' : '';
    setStatus(status, 'circle-check', `Shown in ${family}${where}.`, 'ok');
  } else {
    setStatus(status, 'info', `${family} isn’t publicly available, so this sample uses the fallback fonts.`, 'fallback');
  }
}

/**
 * @param {HTMLElement} status
 * @param {string} icon
 * @param {string} message
 * @param {'checking' | 'ok' | 'fallback'} state
 */
function setStatus(status, icon, message, state) {
  status.dataset.state = state;
  status.replaceChildren(createIcon(icon, { size: 16 }), el('span', { text: message }));
}

/* --------------------------------------------------------------------------
   Font loading
   -------------------------------------------------------------------------- */

/** @type {Map<string, Promise<{ from: 'page' | 'google', weight: number } | null>>} */
const loads = new Map();
/** @type {Promise<Map<string, [string, number]>> | null} */
let fontList = null;

/**
 * Loads a family once, however many cards ask for it.
 * @param {string} family
 * @param {number[]} weights
 */
function loadFamily(family, weights) {
  const key = family.toLowerCase();
  if (!loads.has(key)) loads.set(key, findAndLoad(family, weights));
  return loads.get(key);
}

/**
 * In plain English: is the font already on this page? If not, is it on
 * Google Fonts, and with which of the weights we need? Load those, then
 * confirm the browser really has the font before saying so.
 * @param {string} family
 * @param {number[]} weights
 * @returns {Promise<{ from: 'page' | 'google', weight: number } | null>}
 */
async function findAndLoad(family, weights) {
  if (!document.fonts) return null;
  const first = weights[0] ?? 400;
  if (await hasFont(family, first)) return { from: 'page', weight: first };

  const catalogue = await googleFonts();
  const entry = catalogue.get(family.toLowerCase());
  if (!entry) return null;

  const [name, mask] = entry;
  const available = [100, 200, 300, 400, 500, 600, 700, 800, 900].filter((w) => mask & (1 << (w / 100 - 1)));
  let wanted = weights.filter((w) => available.includes(w));
  // None of the site's weights exist on Google: use the closest one that does.
  if (wanted.length === 0) {
    wanted = [available.reduce((best, w) => (Math.abs(w - first) < Math.abs(best - first) ? w : best))];
  }

  if (!(await addStylesheet(googleFontsUrl(name, wanted)))) return null;
  return (await hasFont(name, wanted[0])) ? { from: 'google', weight: wanted[0] } : null;
}

/**
 * True if the page has (or can now load) this font at this weight.
 * document.fonts.load() resolves to the font faces it found: none = not here.
 * @param {string} family
 * @param {number} weight
 * @returns {Promise<boolean>}
 */
async function hasFont(family, weight) {
  try {
    const faces = await document.fonts.load(`${weight} 1em "${family}"`);
    return faces.length > 0;
  } catch {
    return false;
  }
}

/**
 * Loads the Google Fonts family list once: lower-case name -> [name, weights].
 * If the list can't be loaded, no font is fetched (the fallback is shown).
 * @returns {Promise<Map<string, [string, number]>>}
 */
function googleFonts() {
  fontList ??= fetch(FONT_LIST_URL)
    .then((response) => (response.ok ? response.json() : {}))
    .catch(() => ({}))
    .then((data) => new Map(Object.entries(data).map(([name, mask]) => [name.toLowerCase(), [name, mask]])));
  return fontList;
}

/**
 * "Fraunces", [600] -> https://fonts.googleapis.com/css2?family=Fraunces:wght@600&display=swap
 * @param {string} family
 * @param {number[]} weights Sorted, each available for the family.
 * @returns {string}
 */
function googleFontsUrl(family, weights) {
  const name = encodeURIComponent(family).replace(/%20/g, '+');
  return `https://fonts.googleapis.com/css2?family=${name}:wght@${weights.join(';')}&display=swap`;
}

/**
 * Adds a stylesheet <link> and resolves to true once it has loaded.
 * @param {string} href
 * @returns {Promise<boolean>}
 */
function addStylesheet(href) {
  return new Promise((resolve) => {
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = href;
    link.addEventListener('load', () => resolve(true), { once: true });
    link.addEventListener('error', () => {
      link.remove();
      resolve(false);
    }, { once: true });
    document.head.append(link);
  });
}
