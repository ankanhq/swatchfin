// Checks that Swatchfin's own colour tokens meet WCAG 2.2 AA.
// Run it with `npm run contrast`. It exits with an error if anything fails.
//
// In plain English:
//   1. Read frontend/css/tokens.css and collect every --sf-* colour.
//   2. Work out the final hex value of each semantic token, once for the
//      light theme and once for the dark theme.
//   3. Measure the contrast of every text/background pair we actually use.
//   4. Also confirm the two copies of the dark theme block are identical.

import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const css = await readFile(path.join(root, 'frontend', 'css', 'tokens.css'), 'utf8');

// Minimum ratios from WCAG 2.2: 4.5 for normal text,
// 3 for UI parts such as input borders and focus rings.
const TEXT = 4.5;
const UI = 3;

// [foreground, background, minimum ratio]. Names drop the "--sf-color-" prefix.
const PAIRS = [
  ['text', 'bg', TEXT],
  ['text', 'surface', TEXT],
  ['text', 'surface-subtle', TEXT],
  ['text-muted', 'bg', TEXT],
  ['text-muted', 'surface', TEXT],
  ['text-muted', 'surface-subtle', TEXT],
  ['text-inverse', 'text', TEXT],
  ['link', 'bg', TEXT],
  ['link', 'surface', TEXT],
  ['link', 'surface-subtle', TEXT],
  ['link-hover', 'bg', TEXT],
  ['accent-text', 'bg', TEXT],
  ['accent-text', 'surface', TEXT],
  ['accent-text', 'accent-subtle', TEXT],
  ['on-accent', 'accent', TEXT],
  ['on-accent', 'accent-hover', TEXT],
  ['text', 'selection', TEXT],
  ['success', 'bg', TEXT],
  ['success', 'success-subtle', TEXT],
  ['warning', 'bg', TEXT],
  ['warning', 'warning-subtle', TEXT],
  ['danger', 'bg', TEXT],
  ['danger', 'danger-subtle', TEXT],
  ['on-band', 'band', TEXT],
  ['on-band-muted', 'band', TEXT],
  ['border-input', 'bg', UI],
  ['border-input', 'surface', UI],
  ['focus', 'bg', UI],
  ['focus', 'surface', UI],
  ['focus', 'surface-subtle', UI],
  ['band-focus', 'band', UI],
  ['accent', 'band', UI],
];

/**
 * Returns the declarations inside the first `{ ... }` block that follows
 * the given selector, as { "--name": "value" }.
 * @param {RegExp} selector
 * @returns {Record<string, string>}
 */
function readBlock(selector) {
  const match = selector.exec(css);
  if (!match) throw new Error(`Selector not found in tokens.css: ${selector}`);
  const start = css.indexOf('{', match.index) + 1;
  const body = css.slice(start, css.indexOf('}', start));
  const declarations = {};
  for (const [, name, value] of body.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) {
    declarations[name] = value.trim();
  }
  return declarations;
}

/**
 * Follows var(--x) references until it reaches a hex colour.
 * @param {string} name Custom property name, e.g. "--sf-color-text".
 * @param {Record<string, string>} vars All declarations for one theme.
 * @returns {string} A 6-digit hex colour.
 */
function resolve(name, vars) {
  const value = vars[name];
  if (value === undefined) throw new Error(`Unknown token ${name}`);
  const ref = value.match(/^var\((--[\w-]+)\)$/);
  if (ref) return resolve(ref[1], vars);
  if (/^#[0-9a-f]{6}$/i.test(value)) return value.toLowerCase();
  throw new Error(`${name} is not a plain hex colour: ${value}`);
}

/** Relative luminance, as defined by WCAG. */
function luminance(hex) {
  const channels = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  const [r, g, b] = channels.map((c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** WCAG contrast ratio between two hex colours (1 to 21). */
function contrast(a, b) {
  const [light, dark] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (light + 0.05) / (dark + 0.05);
}

const base = readBlock(/^:root \{/m);
const dark = readBlock(/^:root\[data-theme="dark"\] \{/m);
const darkSystem = readBlock(/:root:not\(\[data-theme="light"\]\) \{/);

const themes = {
  light: base,
  dark: { ...base, ...dark },
};

let failures = 0;

for (const [theme, vars] of Object.entries(themes)) {
  console.log(`\n${theme} theme`);
  for (const [fg, bg, min] of PAIRS) {
    const fgHex = resolve(`--sf-color-${fg}`, vars);
    const bgHex = resolve(`--sf-color-${bg}`, vars);
    const ratio = contrast(fgHex, bgHex);
    const pass = ratio >= min;
    if (!pass) failures += 1;
    const label = `${fg} on ${bg}`.padEnd(32);
    console.log(`  ${pass ? 'pass' : 'FAIL'}  ${label} ${ratio.toFixed(2).padStart(5)}:1  (needs ${min})`);
  }
}

// The dark theme is written twice in tokens.css (toggle + system setting).
const same =
  Object.keys(dark).length === Object.keys(darkSystem).length &&
  Object.entries(dark).every(([name, value]) => darkSystem[name] === value);
console.log(`\ndark theme blocks identical: ${same ? 'yes' : 'NO'}`);
if (!same) failures += 1;

if (failures > 0) {
  console.error(`\n${failures} problem(s) found.`);
  process.exit(1);
}
console.log('\nAll checks passed.');
