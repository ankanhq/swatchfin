/**
 * Colour palette section: a strip showing how much of the page each colour
 * covers, then one swatch per colour with its role, HEX and RGB (both copy
 * on click), where it is used, and how sure Swatchfin is.
 *
 * Colours are painted through a CSS custom property (--sf-swatch), and only
 * after isHexColor() has confirmed the value is a plain "#RRGGBB" code.
 */

import { isHexColor } from '../utils.js';
import { el, createIcon, confidenceBadge, copyButton, emptyState, list, lookup, sentenceCase, text } from './dom.js';

/** Colour role in the data -> label for people. */
const ROLE_LABELS = {
  primary: 'Primary',
  secondary: 'Secondary',
  accent: 'Accent',
  background: 'Background',
  surface: 'Surface',
  text: 'Text',
  'text-muted': 'Muted text',
  link: 'Link',
  border: 'Border',
};

/**
 * @param {unknown} role
 * @returns {string}
 */
export function roleLabel(role) {
  const key = text(role);
  return lookup(ROLE_LABELS, key) ?? (sentenceCase(key) || 'Colour');
}

/**
 * The guide's colours that have a valid hex code, with the hex in capitals.
 * @param {Record<string, any>} guide
 * @returns {Array<Record<string, any> & { hex: string }>}
 */
export function validColors(guide) {
  return list(guide.colors)
    .filter((color) => isHexColor(color?.hex))
    .map((color) => ({ ...color, hex: color.hex.toUpperCase() }));
}

/**
 * @param {Record<string, any>} guide
 * @returns {HTMLElement}
 */
export function renderColors(guide) {
  const colors = validColors(guide);
  if (colors.length === 0) {
    return emptyState('No colours found', 'The browser step could not read the computed styles of the homepage, so there is no palette.');
  }

  return el('div', { className: 'sf-palette' }, [
    shareStrip(colors),
    // data-sequence: the swatches "fill in" one after another (see pages.css).
    el('ul', { className: 'sf-swatches', attrs: { 'data-sequence': '' } }, colors.map(swatch)),
  ]);
}

/**
 * A bar split by each colour's share of the visible homepage, largest first.
 * @param {Array<Record<string, any> & { hex: string }>} colors
 * @returns {HTMLElement | null}
 */
function shareStrip(colors) {
  const shares = colors
    .filter((color) => typeof color.share === 'number' && color.share > 0)
    .sort((a, b) => b.share - a.share);
  if (shares.length === 0) return null;

  const total = shares.reduce((sum, color) => sum + color.share, 0);
  const describe = (color) => `${roleLabel(color.role)} ${Math.round((color.share / total) * 100)}%`;

  const segments = shares.map((color) => {
    const segment = el('span', {
      className: 'sf-share-strip__segment',
      attrs: { title: `${describe(color)} · ${color.hex}` },
    });
    segment.style.setProperty('--sf-swatch', color.hex);
    segment.style.setProperty('--sf-share', String(color.share / total));
    return segment;
  });

  return el('figure', { className: 'sf-share-strip' }, [
    el('div', {
      className: 'sf-share-strip__bar',
      attrs: { role: 'img', 'aria-label': `Share of the visible homepage: ${shares.map(describe).join(', ')}.`, 'data-sequence': '' },
    }, segments),
    el('figcaption', { className: 'sf-share-strip__caption', text: 'Share of the visible homepage area' }),
  ]);
}

/**
 * One swatch card.
 * @param {Record<string, any> & { hex: string }} color
 * @param {number} index Position, used to stagger the fill-in animation.
 * @returns {HTMLElement}
 */
function swatch(color, index) {
  const role = roleLabel(color.role);
  const rgb = `rgb(${rgbOf(color).join(', ')})`;
  const usage = list(color.usage).map(text).filter(Boolean);
  const share = typeof color.share === 'number' && color.share > 0 ? Math.round(color.share * 100) : null;

  const item = el('li', { className: 'sf-swatch' }, [
    el('button', {
      className: 'sf-swatch__color',
      attrs: { type: 'button', 'data-copy': color.hex, 'aria-label': `Copy ${role} colour ${color.hex}` },
    }, [
      el('span', { className: 'sf-swatch__hint', attrs: { 'aria-hidden': 'true' } }, [
        createIcon('copy', { size: 16, className: 'sf-copy__icon' }),
        'Copy',
      ]),
    ]),
    el('div', { className: 'sf-swatch__body' }, [
      el('div', { className: 'sf-swatch__head' }, [
        el('h3', { className: 'sf-swatch__role', text: role }),
        confidenceBadge(color.confidence),
      ]),
      el('div', { className: 'sf-swatch__values' }, [copyButton(color.hex, 'HEX'), copyButton(rgb, 'RGB')]),
      usage.length > 0 ? el('p', { className: 'sf-swatch__usage', text: sentenceCase(usage.join(', ')) }) : null,
      share !== null ? el('p', { className: 'sf-swatch__share', text: `${share < 1 ? '<1' : share}% of the visible area` }) : null,
    ]),
  ]);

  item.style.setProperty('--sf-swatch', color.hex);
  item.style.setProperty('--sf-i', String(index));
  return item;
}

/**
 * The colour's RGB numbers: from the data when they are valid, otherwise
 * worked out from the hex code (so the two can never disagree on screen).
 * @param {Record<string, any> & { hex: string }} color
 * @returns {number[]}
 */
function rgbOf(color) {
  const fromHex = [1, 3, 5].map((start) => parseInt(color.hex.slice(start, start + 2), 16));
  const given = list(color.rgb);
  const valid = given.length === 3 && given.every((n, i) => n === fromHex[i]);
  return valid ? given : fromHex;
}
