/**
 * The top of the guide page: the notice about sample data, the brand header
 * (logo, name, domain, description, facts) and the name in the toolbar.
 * Also the error version of the header, used when a guide can't be loaded.
 */

import { formatDate, safeUrl, displayUrl } from '../utils.js';
import { el, createIcon, list, text } from './dom.js';

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

  page.querySelector('[data-brand-name]').textContent = name;
  page.querySelector('[data-brand-logo]').replaceChildren(headerLogo(guide.logo?.primary?.url));

  const siteHref = safeUrl(brand.url);
  const domain = text(brand.domain) || (siteHref ? displayUrl(siteHref) : '');
  const description = text(brand.description);

  page.querySelector('[data-brand-details]').replaceChildren(
    domain && siteHref
      ? el('a', { className: 'sf-guide-header__domain', attrs: { href: siteHref, rel: 'noopener noreferrer' } }, [
          el('span', { text: domain }),
          createIcon('arrow-up-right', { size: 16 }),
        ])
      : null,
    description ? el('p', { className: 'sf-guide-header__description', text: description }) : null,
    headerFacts(guide, { mock }),
  );
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
 * original query, language, a mock label and the warning count.
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
  items.push(
    el('li', {}, [
      warnings > 0
        ? el('a', { className: 'sf-badge sf-badge--warning sf-badge--link', attrs: { href: '#warnings' } }, [
            createIcon('triangle-alert', { size: 16 }),
            warnings === 1 ? '1 warning' : `${warnings} warnings`,
          ])
        : el('span', { className: 'sf-badge sf-badge--success' }, [createIcon('circle-check', { size: 16 }), 'No warnings']),
    ]),
  );

  return el('ul', { className: 'sf-guide-header__facts' }, items);
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
 * The notice above the header that says when the page shows sample data.
 * @param {HTMLElement} page
 * @param {{ mock: boolean, query: string }} options
 */
export function renderNotice(page, { mock, query }) {
  const slot = page.querySelector('[data-guide-notice]');
  if (!slot || !mock) return;

  const title = query ? 'Live generation isn’t connected yet' : 'Sample guide';
  const message = query
    ? `You searched for “${query}”. Until the Swatchfin backend is connected, this page shows a sample guide for Northwind Roasters, a fictional brand.`
    : 'This guide uses mock data for Northwind Roasters, a fictional brand, so the page can be built before live generation is connected. None of it was read from a real website.';

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
 * the placeholders, when data-state is "error".
 * @param {HTMLElement} page
 * @param {{ title: string, message: string }} error
 */
export function renderHeaderError(page, error) {
  page.querySelector('[data-brand-name]').textContent = error.title;
  page.querySelector('[data-guide-error-message]').textContent = error.message;
}
