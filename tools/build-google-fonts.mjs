// Builds frontend/assets/data/google-fonts.json: the names of every Google
// Fonts family and the weights each one has. Run it with `npm run fonts`.
//
// Why: the guide page shows each detected font in that font when it can.
// It may only ask Google Fonts for families (and weights) that exist there,
// because a request for anything else fails with an error that shows up in
// the browser console. This list lets the page check first.
//
// How it works, in plain English:
//   1. Download Google's public font catalogue (the same data fonts.google.com uses).
//   2. For each family, keep its name and its upright weights (100 to 900).
//   3. Store the weights as one number: bit 0 = 100, bit 1 = 200 ... bit 8 = 900.
//      For example 511 means all nine weights, 72 means 400 and 700 only.
//   4. Save it as small JSON, sorted by name so changes are easy to review.

import { writeFile, mkdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const SOURCE = 'https://fonts.google.com/metadata/fonts';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const outFile = path.join(root, 'frontend', 'assets', 'data', 'google-fonts.json');

const response = await fetch(SOURCE, { signal: AbortSignal.timeout(30_000) });
if (!response.ok) throw new Error(`Google Fonts catalogue answered ${response.status}`);

// The response starts with a short anti-hijacking prefix before the JSON.
const raw = await response.text();
const catalogue = JSON.parse(raw.slice(raw.indexOf('{')));

/** @type {Record<string, number>} */
const families = {};
for (const family of catalogue.familyMetadataList) {
  let mask = 0;
  for (const key of Object.keys(family.fonts)) {
    // Keys look like "400" (upright) or "400i" (italic). Keep upright only.
    if (/^[1-9]00$/.test(key)) mask |= 1 << (Number(key) / 100 - 1);
  }
  if (mask) families[family.family] = mask;
}

const sorted = Object.fromEntries(Object.entries(families).sort(([a], [b]) => a.localeCompare(b)));
await mkdir(path.dirname(outFile), { recursive: true });
await writeFile(outFile, `${JSON.stringify(sorted)}\n`);
console.log(`google-fonts.json: ${Object.keys(sorted).length} families`);
