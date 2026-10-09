/**
 * Logo section: the main logo on a light and a dark tile, where it was
 * found, a download link, and any other versions (alternates, favicon).
 */

import { safeUrl } from '../utils.js';
import { el, createIcon, confidenceBadge, emptyState, fact, list, lookup, sourceLink, subsection, text } from './dom.js';
import { brandName } from './brand.js';

/** How the logo was found -> words for people. */
const METHOD_LABELS = {
  'header-img': 'Image in the page header',
  'inline-svg': 'Inline SVG in the page header',
  'og-image': 'Open Graph image',
  favicon: 'Favicon',
};

/**
 * @param {Record<string, any>} guide
 * @returns {HTMLElement}
 */
export function renderLogo(guide) {
  const name = brandName(guide);
  const primary = guide.logo?.primary;
  const src = safeUrl(primary?.url);

  if (!src) {
    return emptyState(
      'No logo found',
      'Swatchfin looked in the page header, inline SVGs, the Open Graph image and the favicon, and found nothing it could use.',
    );
  }

  const format = text(primary.format).toUpperCase();

  return el('div', { className: 'sf-logo-card' }, [
    el('div', { className: 'sf-logo-card__previews' }, [
      // The same image twice; only the first is described to screen readers.
      logoTile(src, `${name} logo`, 'light'),
      logoTile(src, '', 'dark'),
    ]),
    el('div', { className: 'sf-logo-card__info' }, [
      el('dl', { className: 'sf-facts' }, [
        ...fact('Found in', lookup(METHOD_LABELS, primary.method) ?? 'Unknown'),
        ...fact('Format', format || 'Unknown'),
        ...fact('Confidence', confidenceBadge(primary.confidence) ?? 'Not scored'),
        ...fact('Found on', sourceLink(primary.source_url) ?? 'Unknown'),
      ]),
      // "download" saves the file when it is on our own site; for logos on
      // other sites the browser opens it in a new view instead.
      el('a', { className: 'sf-btn sf-btn--secondary sf-btn--sm', attrs: { href: src, download: '', rel: 'noopener noreferrer' } }, [
        createIcon('download', { size: 16 }),
        format ? `Download ${format}` : 'Download logo',
      ]),
    ]),
    otherVersions(guide, src),
  ]);
}

/**
 * One preview tile with a fixed light or dark background.
 * @param {string} src
 * @param {string} alt
 * @param {'light' | 'dark'} tone
 * @returns {HTMLElement}
 */
function logoTile(src, alt, tone) {
  return el('figure', { className: `sf-logo-tile sf-logo-tile--${tone}` }, [
    logoImage(src, alt, 'sf-logo-tile__img'),
    el('figcaption', { className: 'sf-logo-tile__label', text: tone === 'light' ? 'On light' : 'On dark' }),
  ]);
}

/**
 * An <img> that turns into a short message if the file can't be loaded
 * (some sites block images shown on other sites).
 * @param {string} src
 * @param {string} alt
 * @param {string} className
 * @returns {HTMLElement}
 */
function logoImage(src, alt, className) {
  const img = el('img', { className, attrs: { src, alt, loading: 'lazy', decoding: 'async' } });
  img.addEventListener(
    'error',
    () => img.replaceWith(el('span', { className: 'sf-logo-tile__missing', text: 'Image could not be loaded' })),
    { once: true },
  );
  return img;
}

/**
 * Alternates and the favicon, without repeating the main logo or each other.
 * @param {Record<string, any>} guide
 * @param {string} primarySrc
 * @returns {HTMLElement | null}
 */
function otherVersions(guide, primarySrc) {
  const seen = new Set([primarySrc]);
  const items = [];

  for (const alternate of list(guide.logo?.alternates)) {
    const src = safeUrl(alternate?.url);
    if (!src || seen.has(src)) continue;
    seen.add(src);
    items.push(versionItem(src, lookup(METHOD_LABELS, alternate.method) ?? 'Alternate', text(alternate.format).toUpperCase(), alternate.confidence));
  }

  const favicon = safeUrl(guide.logo?.favicon);
  if (favicon && !seen.has(favicon)) items.push(versionItem(favicon, 'Favicon', '', null));

  if (items.length === 0) return null;
  return subsection('Other versions', [el('ul', { className: 'sf-logo-versions' }, items)]);
}

/**
 * @param {string} src
 * @param {string} label
 * @param {string} format
 * @param {unknown} confidence
 * @returns {HTMLElement}
 */
function versionItem(src, label, format, confidence) {
  return el('li', { className: 'sf-logo-version' }, [
    el('span', { className: 'sf-logo-version__thumb' }, [logoImage(src, '', 'sf-logo-version__img')]),
    el('span', { className: 'sf-logo-version__text' }, [
      el('span', { className: 'sf-logo-version__label', text: label }),
      el('a', { className: 'sf-logo-version__link', text: format ? `Open ${format}` : 'Open file', attrs: { href: src, rel: 'noopener noreferrer' } }),
    ]),
    confidenceBadge(confidence),
  ]);
}
