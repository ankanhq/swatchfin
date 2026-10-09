// Runs Lighthouse on every Swatchfin page, and on every state of the guide
// page, for mobile and desktop, then prints a table of the four scores.
// Run it with `npm run lighthouse` while the dev server is running
// (python3 tools/serve.py). The full reports are saved in
// reports/lighthouse/ (git-ignored): open the .html files in a browser.
//
//   npm run lighthouse                       every page, mobile and desktop
//   npm run lighthouse -- guide about        only the pages with these names
//   BASE_URL=http://localhost:8001 npm run lighthouse
//
// How it works, in plain English:
//   1. For each page and each device, start the pinned Lighthouse CLI. It
//      opens its own headless Chrome, loads the page and audits it.
//   2. Read the JSON report it saved and keep the four category scores.
//   3. Print one table, and mark any score under the target (95).

import { spawn } from 'node:child_process';
import { mkdir, readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const TARGET = 95;
const BASE_URL = process.env.BASE_URL ?? 'http://localhost:8000';

// [name, address]. The guide states use the mock data until Phase 4.
const PAGES = [
  ['start', '/'],
  ['about', '/about.html'],
  ['guide', '/guide.html?id=mock'],
  ['guide-partial', '/guide.html?id=mock-partial'],
  ['guide-running', '/guide.html?q=Duolingo'],
  ['guide-failed', '/guide.html?id=mock-failed'],
  ['guide-empty', '/guide.html'],
  ['guide-not-found', '/guide.html?id=nope'],
  // Lighthouse won't audit an answer with a 404 status, so it opens the
  // file itself. Its SEO score doesn't count: the page is noindex on purpose.
  ['404', '/404.html'],
];

/** Scores that don't apply to a page (shown as "n/a"). */
const NOT_SCORED = { 404: ['seo'] };

const DEVICES = ['mobile', 'desktop'];
const CATEGORIES = ['performance', 'accessibility', 'best-practices', 'seo'];
const LABELS = { performance: 'Perf', accessibility: 'A11y', 'best-practices': 'Best', seo: 'SEO' };

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const outDir = path.join(root, 'reports', 'lighthouse');
const lighthouse = path.join(root, 'node_modules', '.bin', 'lighthouse');

/**
 * Runs the Lighthouse CLI once and waits for it to finish.
 * @param {string[]} args
 * @returns {Promise<void>}
 */
function runLighthouse(args) {
  return new Promise((resolve, reject) => {
    const child = spawn(lighthouse, args, { stdio: ['ignore', 'ignore', 'inherit'] });
    child.on('error', reject);
    child.on('exit', (code) => (code === 0 ? resolve() : reject(new Error(`Lighthouse exited with code ${code}`))));
  });
}

/**
 * Audits one page on one device and returns its scores (0–100).
 * @param {string} name
 * @param {string} address
 * @param {string} device
 * @returns {Promise<Record<string, number | null>>}
 */
async function audit(name, address, device) {
  const base = path.join(outDir, `${name}-${device}`);
  const args = [
    BASE_URL + address,
    `--only-categories=${CATEGORIES.join(',')}`,
    '--output=json',
    '--output=html',
    `--output-path=${base}`,
    '--chrome-flags=--headless=new',
    '--quiet',
  ];
  if (device === 'desktop') args.push('--preset=desktop');

  await runLighthouse(args);
  const report = JSON.parse(await readFile(`${base}.report.json`, 'utf8'));

  const scores = {};
  for (const category of CATEGORIES) {
    const score = report.categories[category]?.score;
    scores[category] = typeof score === 'number' ? Math.round(score * 100) : null;
  }
  return scores;
}

async function main() {
  const only = process.argv.slice(2);
  const pages = only.length > 0 ? PAGES.filter(([name]) => only.includes(name)) : PAGES;
  if (pages.length === 0) {
    console.error(`No page with that name. Pages: ${PAGES.map(([name]) => name).join(', ')}`);
    process.exit(1);
  }

  await mkdir(outDir, { recursive: true });
  console.log(`Lighthouse ${BASE_URL}, ${pages.length} pages × ${DEVICES.length} devices. This takes a few minutes.\n`);

  const header = ['Page'.padEnd(18), 'Device'.padEnd(8), ...CATEGORIES.map((c) => LABELS[c].padStart(5))].join(' ');
  console.log(header);
  console.log('-'.repeat(header.length));

  let below = 0;
  for (const [name, address] of pages) {
    for (const device of DEVICES) {
      const scores = await audit(name, address, device);
      const cells = CATEGORIES.map((category) => {
        const score = scores[category];
        if (NOT_SCORED[name]?.includes(category)) return '  n/a';
        if (score === null) return '    –';
        if (score < TARGET) below += 1;
        return `${score < TARGET ? '*' : ' '}${String(score).padStart(4)}`;
      });
      console.log([name.padEnd(18), device.padEnd(8), ...cells].join(' '));
    }
  }

  console.log(`\n* = under ${TARGET}. Reports: reports/lighthouse/<page>-<device>.report.html`);
  console.log(below === 0 ? 'Every score meets the target.' : `${below} score(s) under the target.`);
}

main().catch((error) => {
  console.error(error.message);
  console.error('Is the dev server running? Start it with: python3 tools/serve.py');
  process.exit(1);
});
