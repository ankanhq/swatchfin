/**
 * Logo section: the main logo on a light and a dark tile, a note when it
 * is hard to see on one of them, where it was found, a download link, and
 * any other versions (alternates, favicon).
 */

import { safeUrl } from '../utils.js';
import { el, createIcon, confidenceBadge, emptyState, fact, list, lookup, siteHost, sourceLink, subsection, text } from './dom.js';
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
  const notes = el('ul', { className: 'sf-logo-card__notes' });
  addContrastNotes(notes, src);

  return el('div', { className: 'sf-logo-card' }, [
    el('div', { className: 'sf-logo-card__preview' }, [
      el('div', { className: 'sf-logo-card__tiles' }, [
        // The same image twice; only the first is described to screen readers.
        logoTile(src, `${name} logo`, 'light'),
        logoTile(src, '', 'dark'),
      ]),
      notes,
    ]),
    el('div', { className: 'sf-logo-card__info' }, [
      el('dl', { className: 'sf-facts' }, [
        ...fact('Found in', lookup(METHOD_LABELS, primary.method) ?? 'Unknown'),
        ...fact('Format', format || 'Unknown'),
        ...fact('Confidence', confidenceBadge(primary.confidence) ?? 'Not scored'),
        ...fact('Found on', sourceLink(primary.source_url, { site: siteHost(guide) }) ?? 'Unknown'),
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

/* --------------------------------------------------------------------------
   Contrast check for the preview tiles
   -------------------------------------------------------------------------- */

// Luminance of the two tile colours in pages.css: white and ink (#0b0f19).
const LIGHT_TILE = luminance(0xff, 0xff, 0xff);
const DARK_TILE = luminance(0x0b, 0x0f, 0x19);
// WCAG 2.2 asks for 3:1 for graphics such as logos (success criterion 1.4.11).
const MIN_RATIO = 3;

/**
 * Adds "Low contrast on dark backgrounds…" notes under the tiles when most
 * of the logo is hard to see on one of them.
 * @param {HTMLElement} notes The (empty) list under the tiles.
 * @param {string} src
 */
async function addContrastNotes(notes, src) {
  const result = await lowContrastSides(src);
  if (!result) return;
  if (result.dark) notes.append(contrastNote('Low contrast on dark backgrounds. Use a light version of the logo there.'));
  if (result.light) notes.append(contrastNote('Low contrast on light backgrounds. Use a dark version of the logo there.'));
}

/**
 * @param {string} message
 * @returns {HTMLElement}
 */
function contrastNote(message) {
  return el('li', { className: 'sf-logo-card__note' }, [createIcon('triangle-alert', { size: 16 }), el('span', { text: message })]);
}

/**
 * Looks at the logo's pixels and says on which tile it is hard to see.
 *
 * In plain English: draw the logo small onto a hidden canvas and read back
 * its colours. Ignore see-through pixels. For every solid pixel, work out
 * its contrast against the white tile and against the dark tile. If more
 * than half of the solid pixels are below 3:1 on a tile, the logo is hard
 * to see there.
 *
 * Returns null (no notes) when the check can't be done fairly:
 * - The logo is on another website. Browsers don't let a page read pixels
 *   from other sites' images, and trying logs errors. Once the backend
 *   serves logos from Swatchfin's own address, every logo gets the check.
 * - The logo has its own solid background (a JPG, or a PNG with no
 *   transparency). It brings its own contrast, so the tile doesn't matter.
 *
 * @param {string} src
 * @returns {Promise<{ dark: boolean, light: boolean } | null>}
 */
async function lowContrastSides(src) {
  if (new URL(src).origin !== window.location.origin) return null;

  const img = new Image();
  img.src = src;
  try {
    await img.decode();
  } catch {
    return null;
  }
  if (!img.naturalWidth || !img.naturalHeight) return null;

  const width = 160;
  const height = Math.max(1, Math.round((width * img.naturalHeight) / img.naturalWidth));
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext('2d', { willReadFrequently: true });
  if (!context) return null;
  context.drawImage(img, 0, 0, width, height);

  let pixels;
  try {
    pixels = context.getImageData(0, 0, width, height).data;
  } catch {
    return null; // the browser refused to share the pixels
  }

  let solid = 0;
  let clear = 0;
  let lowOnDark = 0;
  let lowOnLight = 0;
  // Each pixel is four numbers: red, green, blue, alpha (0 = see-through).
  for (let i = 0; i < pixels.length; i += 4) {
    const alpha = pixels[i + 3];
    if (alpha < 16) clear += 1;
    if (alpha < 200) continue; // skip see-through and soft edge pixels
    solid += 1;
    const lum = luminance(pixels[i], pixels[i + 1], pixels[i + 2]);
    if (ratio(lum, DARK_TILE) < MIN_RATIO) lowOnDark += 1;
    if (ratio(lum, LIGHT_TILE) < MIN_RATIO) lowOnLight += 1;
  }

  // Less than 10% see-through: the logo has its own background.
  if (solid === 0 || clear / (width * height) < 0.1) return null;
  return { dark: lowOnDark / solid > 0.5, light: lowOnLight / solid > 0.5 };
}

/**
 * WCAG relative luminance of an sRGB colour (0 = black, 1 = white).
 * @param {number} r
 * @param {number} g
 * @param {number} b
 * @returns {number}
 */
function luminance(r, g, b) {
  const channel = (value) => {
    const c = value / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

/**
 * WCAG contrast ratio between two luminances, from 1 to 21.
 * @param {number} a
 * @param {number} b
 * @returns {number}
 */
function ratio(a, b) {
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

/* --------------------------------------------------------------------------
   Other versions
   -------------------------------------------------------------------------- */

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
 * A small card: thumbnail, then the label above a row with the link and
 * the confidence badge (the row wraps instead of squeezing either).
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
      el('span', { className: 'sf-logo-version__meta' }, [
        el('a', { className: 'sf-logo-version__link', text: format ? `Open ${format}` : 'Open file', attrs: { href: src, rel: 'noopener noreferrer' } }),
        confidenceBadge(confidence),
      ]),
    ]),
  ]);
}
