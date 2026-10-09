/**
 * Contrast section: a table with text colours down the side and background
 * colours across the top. Each cell shows a sample, the contrast ratio and
 * its WCAG rating. Pairs the guide didn't measure show a dash.
 *
 * The ratios come from the backend. This file only displays them; it does
 * not recalculate anything.
 */

import { isHexColor } from '../utils.js';
import { el, emptyState, list, lookup } from './dom.js';
import { roleLabel, validColors } from './colors.js';

/** WCAG rating -> badge text and tone. */
const RATINGS = {
  AAA: { label: 'AAA', tone: 'success' },
  AA: { label: 'AA', tone: 'success' },
  'AA-large': { label: 'AA large', tone: 'warning' },
  fail: { label: 'Fail', tone: 'danger' },
};

/**
 * @param {Record<string, any>} guide
 * @returns {HTMLElement}
 */
export function renderContrast(guide) {
  const pairs = list(guide.contrast)
    .filter((pair) => isHexColor(pair?.fg) && isHexColor(pair?.bg) && typeof pair.ratio === 'number' && pair.ratio >= 1)
    .map((pair) => ({ ...pair, fg: pair.fg.toUpperCase(), bg: pair.bg.toUpperCase(), wcag: ratingOf(pair) }));

  if (pairs.length === 0) {
    return emptyState('No contrast checks', 'Contrast is measured between text and background colours, and this guide has no such pairs.');
  }

  // Name each colour by its role in the palette, e.g. "Muted text".
  const names = new Map(validColors(guide).map((color) => [color.hex, roleLabel(color.role)]));
  const nameOf = (hex) => names.get(hex) ?? hex;

  const textColors = [...new Set(pairs.map((pair) => pair.fg))];
  const backgrounds = [...new Set(pairs.map((pair) => pair.bg))];
  const byPair = new Map(pairs.map((pair) => [`${pair.fg}|${pair.bg}`, pair]));

  const head = el('thead', {}, [
    el('tr', {}, [
      el('th', { className: 'sf-contrast__corner', attrs: { scope: 'col' }, text: 'Text on background' }),
      ...backgrounds.map((bg) => el('th', { attrs: { scope: 'col' } }, [colorLabel(bg, nameOf(bg))])),
    ]),
  ]);

  const body = el('tbody', {}, textColors.map((fg) =>
    el('tr', {}, [
      el('th', { attrs: { scope: 'row' } }, [colorLabel(fg, nameOf(fg))]),
      ...backgrounds.map((bg) => {
        const pair = byPair.get(`${fg}|${bg}`);
        return pair ? cell(pair, nameOf(bg)) : emptyCell();
      }),
    ]),
  ));

  return el('div', { className: 'sf-contrast' }, [
    summary(pairs),
    el('div', { className: 'sf-contrast__frame' }, [
      el('table', { className: 'sf-contrast__table' }, [
        el('caption', { className: 'visually-hidden', text: 'Contrast ratio of each text colour (rows) on each background colour (columns).' }),
        head,
        body,
      ]),
    ]),
    legend(),
  ]);
}

/**
 * The rating from the data if it is one we know, otherwise worked out from
 * the ratio with the WCAG 2.2 thresholds.
 * @param {Record<string, any>} pair
 * @returns {keyof typeof RATINGS}
 */
function ratingOf(pair) {
  if (lookup(RATINGS, pair.wcag)) return pair.wcag;
  if (pair.ratio >= 7) return 'AAA';
  if (pair.ratio >= 4.5) return 'AA';
  if (pair.ratio >= 3) return 'AA-large';
  return 'fail';
}

/**
 * "9 of 12 pairs pass AA for normal text. 2 only for large text. 1 fails."
 * @param {Array<{ wcag: string }>} pairs
 * @returns {HTMLElement}
 */
function summary(pairs) {
  const count = (...ratings) => pairs.filter((pair) => ratings.includes(pair.wcag)).length;
  const pass = count('AAA', 'AA');
  const large = count('AA-large');
  const fail = count('fail');

  const parts = [`${pass} of ${pairs.length} pairs pass AA for normal text.`];
  if (large) parts.push(`${large} ${large === 1 ? 'passes' : 'pass'} for large text only.`);
  if (fail) parts.push(`${fail} ${fail === 1 ? 'fails' : 'fail'}.`);
  return el('p', { className: 'sf-contrast__summary', text: parts.join(' ') });
}

/**
 * A colour chip with its role and hex code, for the table headers.
 * @param {string} hex
 * @param {string} name
 * @returns {HTMLElement}
 */
function colorLabel(hex, name) {
  const chip = el('span', { className: 'sf-contrast__chip', attrs: { 'aria-hidden': 'true' } });
  chip.style.setProperty('--sf-swatch', hex);
  return el('span', { className: 'sf-contrast__color' }, [
    chip,
    el('span', { className: 'sf-contrast__name' }, [
      el('span', { text: name }),
      name !== hex ? el('span', { className: 'sf-contrast__hex', text: hex }) : null,
    ]),
  ]);
}

/**
 * @param {{ fg: string, bg: string, ratio: number, wcag: keyof typeof RATINGS }} pair
 * @param {string} bgName Shown in the cell on phones, where the column headers are hidden.
 * @returns {HTMLElement}
 */
function cell(pair, bgName) {
  const rating = RATINGS[pair.wcag];
  const sample = el('span', { className: 'sf-contrast__sample', text: 'Aa', attrs: { 'aria-hidden': 'true' } });
  sample.style.setProperty('--sf-fg', pair.fg);
  sample.style.setProperty('--sf-bg', pair.bg);

  return el('td', { className: `sf-contrast__cell sf-contrast__cell--${rating.tone}` }, [
    sample,
    el('span', { className: 'sf-contrast__result' }, [
      el('span', { className: 'sf-contrast__on', text: `on ${bgName}` }),
      el('span', { className: 'sf-contrast__ratio', text: `${pair.ratio.toFixed(2)}:1` }),
      el('span', { className: `sf-badge sf-badge--${rating.tone}`, text: rating.label }),
    ]),
  ]);
}

/** @returns {HTMLElement} */
function emptyCell() {
  return el('td', { className: 'sf-contrast__cell sf-contrast__cell--none' }, [
    el('span', { text: '–', attrs: { 'aria-hidden': 'true' } }),
    el('span', { className: 'visually-hidden', text: 'Not measured' }),
  ]);
}

/** What each rating means. @returns {HTMLElement} */
function legend() {
  const item = (rating, meaning) => el('li', {}, [
    el('span', { className: `sf-badge sf-badge--${RATINGS[rating].tone}`, text: RATINGS[rating].label }),
    el('span', { text: meaning }),
  ]);
  return el('ul', { className: 'sf-contrast__legend', attrs: { 'aria-label': 'What the ratings mean' } }, [
    item('AAA', '7:1 or more'),
    item('AA', '4.5:1 or more, for normal text'),
    item('AA-large', '3:1 or more, for text from 24px (or 19px bold)'),
    item('fail', 'below 3:1'),
  ]);
}
