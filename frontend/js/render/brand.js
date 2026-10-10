/**
 * The top of the guide page: the notice about sample data, the brand header
 * (logo, name, domain, description, facts) and the name in the toolbar.
 * Also the error version of the header, used when a guide can't be loaded
 * or its job failed.
 */

import { formatDate, safeUrl, displayUrl } from '../utils.js';
import { el, createIcon, list, lookup, text } from './dom.js';
import { validColors } from './colors.js';

/**
 * The brand's display name, with sensible fallbacks.
 * @param {Record<string, any>} guide
 * @returns {string}
 */
export function brandName(guide) {
  return text(guide.brand?.name) || text(guide.brand?.domain) || text(guide.query) || 'Untitled brand';
}

/**
 * Fills in the brand header.
 * @param {HTMLElement} page The <main> element.
 * @param {Record<string, any>} guide
 * @param {{ mock: boolean }} options
 */
export function renderBrandHeader(page, guide, { mock }) {
  const name = brandName(guide);
  const brand = guide.brand ?? {};

  // data-filled: the header shows the real guide now (pages.css fades it in).
  page.querySelector('.sf-guide-header')?.setAttribute('data-filled', '');
  page.querySelector('[data-brand-eyebrow]').textContent = 'Brand guide';
  page.querySelector('[data-brand-name]').textContent = name;
  page.querySelector('[data-brand-logo]').replaceChildren(headerLogo(guide.logo?.primary?.url));

  const siteHref = safeUrl(brand.url);
  const domain = text(brand.domain) || (siteHref ? displayUrl(siteHref) : '');
  const description = text(brand.description);

  const details = [
    domain && siteHref
      ? el('a', { className: 'sf-guide-header__domain', attrs: { href: siteHref, rel: 'noopener noreferrer' } }, [
          el('span', { text: domain }),
          createIcon('arrow-up-right', { size: 16 }),
        ])
      : null,
    description ? el('p', { className: 'sf-guide-header__description', text: description }) : null,
    headerFacts(guide, { mock }),
  ];
  // replaceChildren() would show a missing part as the word "null", so leave those out first.
  page.querySelector('[data-brand-details]').replaceChildren(...details.filter(Boolean));
}

/**
 * The logo next to the brand name. It is decorative here (alt=""), because
 * the name is right beside it; the Logo section describes it properly.
 * @param {unknown} url
 * @returns {HTMLElement}
 */
function headerLogo(url) {
  const placeholder = () => el('span', { className: 'sf-guide-header__placeholder' }, [createIcon('image', { size: 24 })]);
  const src = safeUrl(url);
  if (!src) return placeholder();

  const img = el('img', { className: 'sf-guide-header__img', attrs: { src, alt: '', decoding: 'async' } });
  // If the site blocks the image (or it is gone), show the placeholder instead.
  img.addEventListener('error', () => img.replaceWith(placeholder()), { once: true });
  return img;
}

/**
 * The row of small facts under the description: generated date, the
 * original query, language, a mock label and the warning count (which
 * also says "Partial guide" when whole sections are missing).
 * @param {Record<string, any>} guide
 * @param {{ mock: boolean }} options
 * @returns {HTMLElement}
 */
function headerFacts(guide, { mock }) {
  const items = [];

  const generated = formatDate(guide.generated_at);
  if (generated) items.push(fact('calendar', `Generated ${generated}`));

  const query = text(guide.query);
  if (query) items.push(fact('search', `Query: “${query}”`));

  const language = languageName(guide.brand?.language);
  if (language) items.push(fact('globe', language));

  if (mock) {
    items.push(el('li', {}, [el('span', { className: 'sf-badge sf-badge--accent', text: 'Mock data' })]));
  }

  const warnings = list(guide.warnings).length;
  const missing = missingSections(guide);
  const count = warnings === 1 ? '1 warning' : `${warnings} warnings`;
  const label = missing.length > 0 ? (warnings > 0 ? `Partial guide · ${count}` : 'Partial guide') : count;

  items.push(
    el('li', {}, [
      warnings > 0 || missing.length > 0
        ? el('a', { className: 'sf-badge sf-badge--warning sf-badge--link', attrs: { href: '#warnings' } }, [
            createIcon('triangle-alert', { size: 16 }),
            label,
            missing.length > 0 ? el('span', { className: 'visually-hidden', text: `. Missing: ${missing.join(', ')}.` }) : null,
          ])
        : el('span', { className: 'sf-badge sf-badge--success' }, [createIcon('circle-check', { size: 16 }), 'No warnings']),
    ]),
  );

  return el('ul', { className: 'sf-guide-header__facts' }, items);
}

/**
 * The parts of the guide that are missing completely, e.g. ["colours",
 * "fonts"] when the browser step failed. An empty list means a full guide.
 * @param {Record<string, any>} guide
 * @returns {string[]}
 */
export function missingSections(guide) {
  const messaging = guide.messaging ?? {};
  const checks = {
    logo: Boolean(safeUrl(guide.logo?.primary?.url)),
    colours: validColors(guide).length > 0,
    fonts: list(guide.typography).length > 0,
    'tone of voice': list(guide.voice?.traits).length > 0,
    'key messaging':
      Boolean(text(messaging.tagline?.text) || text(messaging.mission?.text)) || list(messaging.value_props).length > 0,
  };
  return Object.keys(checks).filter((name) => !checks[name]);
}

/**
 * @param {string} icon
 * @param {string} label
 * @returns {HTMLElement}
 */
function fact(icon, label) {
  return el('li', { className: 'sf-guide-header__fact' }, [createIcon(icon, { size: 16 }), el('span', { text: label })]);
}

/**
 * "en" -> "English". Returns "" for a missing or unknown code.
 * @param {unknown} code
 * @returns {string}
 */
function languageName(code) {
  if (typeof code !== 'string' || code.trim() === '') return '';
  try {
    return new Intl.DisplayNames(['en'], { type: 'language' }).of(code.trim()) ?? '';
  } catch {
    return ''; // not a valid language code
  }
}

/**
 * The brand name and domain in the sticky toolbar.
 * @param {HTMLElement} page
 * @param {Record<string, any>} guide
 */
export function renderToolbar(page, guide) {
  page.querySelector('[data-guidebar-name]').textContent = brandName(guide);
  page.querySelector('[data-guidebar-domain]').textContent = text(guide.brand?.domain);
}

/**
 * MOCK: the notice that labels the sample guide for Northwind Roasters, a
 * fictional brand. Until live generation is connected (Phases 5–7), every
 * run ends with it. `query` is what was searched for, when that was
 * another brand; it is empty for the sample itself (?id=mock).
 * @type {Record<string, { title: string, message: (query: string) => string }>}
 */
const NOTICES = {
  sample: {
    title: 'Sample guide',
    message: (query) =>
      query
        ? `You searched for “${query}”. Live generation isn’t connected yet, so this page shows the sample guide for Northwind Roasters, a fictional brand. None of it was read from a real website.`
        : 'This guide uses mock data for Northwind Roasters, a fictional brand, so the page can be built before live generation is connected. None of it was read from a real website.',
  },
};

/**
 * The notice above the header that says when the page shows sample data.
 * With no kind (a real guide), the notice is removed.
 * @param {HTMLElement} page
 * @param {string | null} kind A key of NOTICES, or null.
 * @param {{ query?: string }} [options]
 */
export function renderNotice(page, kind, { query = '' } = {}) {
  const slot = page.querySelector('[data-guide-notice]');
  if (!slot) return;

  const notice = lookup(NOTICES, kind);
  if (!notice) {
    slot.replaceChildren();
    return;
  }

  const title = notice.title;
  const message = notice.message(query);

  slot.replaceChildren(
    el('div', { className: 'sf-notice' }, [
      createIcon('info', { className: 'sf-notice__icon' }),
      el('div', {}, [
        el('p', { className: 'sf-notice__title', text: title }),
        el('p', { className: 'sf-notice__text', text: message }),
      ]),
    ]),
  );
}

/**
 * Turns the header into an error message. The buttons (Start a new guide,
 * Try again) are plain HTML in guide.html; the CSS shows them, and hides
 * the placeholders, when data-state is "error" or "failed".
 * @param {HTMLElement} page
 * @param {{ title: string, message: string, retryLabel?: string }} error
 * @param {{ eyebrow?: string, retryHref?: string }} [options]
 *   eyebrow: the small line above the title. retryHref: where Try again
 *   goes. Without it, Try again opens this same address again.
 */
export function renderHeaderError(page, error, { eyebrow = 'Brand guide', retryHref } = {}) {
  page.querySelector('[data-brand-eyebrow]').textContent = eyebrow;
  page.querySelector('[data-brand-name]').textContent = error.title;
  page.querySelector('[data-guide-error-message]').textContent = error.message;

  const retry = page.querySelector('[data-guide-retry]');
  if (retry && retryHref) retry.setAttribute('href', retryHref);
  const label = page.querySelector('[data-guide-retry-label]');
  if (label && error.retryLabel) label.textContent = error.retryLabel;
}
