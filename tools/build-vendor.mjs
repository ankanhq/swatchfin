// Copies the third-party files Swatchfin serves from its own server into
// /frontend, from pinned npm packages, each with its licence next to it.
// Run it with `npm run vendor` after changing one of these package versions.
//
// What it writes:
//   frontend/vendor/bootstrap/          bootstrap-slim.min.css: Bootstrap's
//                                       reboot and grid files joined into one
//                                       (the only parts the site uses) + LICENSE (MIT)
//   frontend/assets/fonts/<family>/     the .woff2 files + OFL.txt
//   frontend/css/fonts.css              the @font-face rules for those files
// Then it runs tools/subset-fraunces.py, which makes the three-letter
// Fraunces file for the start page's example card (needs Python fontTools).
//
// How the fonts work, in plain English: each family is split into one file
// per script (Latin, Latin Extended, Cyrillic, Greek, Vietnamese). The
// @font-face rules copied from the package say which characters each file
// covers ("unicode-range"), so a browser only downloads the files for the
// characters a page actually shows. Each file is a variable font: one file
// holds every weight.

import { copyFile, mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const modules = path.join(root, 'node_modules');
const frontend = path.join(root, 'frontend');

// Package folder -> the font-family name the CSS uses (see tokens.css).
const FONTS = [
  { pkg: 'inter', family: 'Inter' },
  { pkg: 'inter-tight', family: 'Inter Tight' },
  { pkg: 'jetbrains-mono', family: 'JetBrains Mono' },
];

const BOOTSTRAP_FILES = ['bootstrap-reboot.min.css', 'bootstrap-grid.min.css'];

/** Reads "version" from an installed package. */
async function versionOf(pkg) {
  const data = JSON.parse(await readFile(path.join(modules, pkg, 'package.json'), 'utf8'));
  return data.version;
}

/**
 * Joins Bootstrap's reboot and grid files into one, so a page makes one
 * request instead of two. Each part keeps its own Bootstrap licence banner.
 * The source map links are dropped, because the maps aren't copied.
 */
async function copyBootstrap() {
  const out = path.join(frontend, 'vendor', 'bootstrap');
  await rm(out, { recursive: true, force: true });
  await mkdir(out, { recursive: true });

  const version = await versionOf('bootstrap');
  const parts = [];
  for (const file of BOOTSTRAP_FILES) {
    const css = await readFile(path.join(modules, 'bootstrap', 'dist', 'css', file), 'utf8');
    parts.push(css.replace(/\/\*# sourceMappingURL=[^*]*\*\/\s*$/, '').trim());
  }
  const header = `/* Bootstrap ${version}: ${BOOTSTRAP_FILES.join(' + ')}, joined by tools/build-vendor.mjs (npm run vendor). */`;
  await writeFile(path.join(out, 'bootstrap-slim.min.css'), `${header}\n${parts.join('\n')}\n`);
  await copyFile(path.join(modules, 'bootstrap', 'LICENSE'), path.join(out, 'LICENSE'));
  console.log(`bootstrap ${version}: ${BOOTSTRAP_FILES.join(' + ')} -> bootstrap-slim.min.css`);
}

/**
 * Copies one family's upright, weight-axis files and returns its @font-face rules.
 * @param {{ pkg: string, family: string }} font
 * @returns {Promise<string>}
 */
async function copyFont({ pkg, family }) {
  const source = path.join(modules, '@fontsource-variable', pkg);
  const out = path.join(frontend, 'assets', 'fonts', pkg);
  await rm(out, { recursive: true, force: true });
  await mkdir(out, { recursive: true });
  await copyFile(path.join(source, 'LICENSE'), path.join(out, 'OFL.txt'));

  // wght.css holds one @font-face per script, upright style, weight axis only.
  const css = await readFile(path.join(source, 'wght.css'), 'utf8');
  const blocks = css.match(/@font-face\s*\{[^}]*\}/g) ?? [];
  if (blocks.length === 0) throw new Error(`No @font-face rules in ${pkg}/wght.css`);

  const rules = [];
  for (const block of blocks) {
    const file = block.match(/url\(\.\/files\/([^)]+\.woff2)\)/)?.[1];
    const weight = block.match(/font-weight:\s*([^;]+);/)?.[1];
    const range = block.match(/unicode-range:\s*([^;]+);/)?.[1];
    if (!file || !weight || !range) throw new Error(`Unexpected @font-face rule in ${pkg}/wght.css`);

    await copyFile(path.join(source, 'files', file), path.join(out, file));
    rules.push(
      [
        '@font-face {',
        `  font-family: "${family}";`,
        '  font-style: normal;',
        `  font-weight: ${weight};`,
        '  font-display: swap;',
        `  src: url("../assets/fonts/${pkg}/${file}") format("woff2");`,
        `  unicode-range: ${range};`,
        '}',
      ].join('\n'),
    );
  }

  console.log(`${family} ${await versionOf(`@fontsource-variable/${pkg}`)}: ${blocks.length} files`);
  return `/* ---- ${family} (OFL, see assets/fonts/${pkg}/OFL.txt) ---- */\n${rules.join('\n\n')}`;
}

async function main() {
  await copyBootstrap();

  const sections = [];
  for (const font of FONTS) sections.push(await copyFont(font));

  // The example card on the start page shows "Aa" and "N" in Fraunces.
  // Its file only has those three letters, so its family name is not
  // "Fraunces": the guide page must never mistake it for the whole font.
  sections.push(`/* ---- Fraunces, three letters only (OFL, see assets/fonts/fraunces/OFL.txt) ----
   Only for the made-up Northwind Roasters example card on the start page.
   Made by tools/subset-fraunces.py. */
@font-face {
  font-family: "Fraunces Sample";
  font-style: normal;
  font-weight: 600;
  font-display: swap;
  src: url("../assets/fonts/fraunces/fraunces-sample-aan.woff2") format("woff2");
  unicode-range: U+0041, U+004E, U+0061;
}`);

  const header = `/* ==========================================================================
   Swatchfin fonts, served from this site.
   Generated by tools/build-vendor.mjs (npm run vendor). Do not edit by hand.
   Sources: the pinned @fontsource-variable packages in package.json.
   ========================================================================== */
`;
  await writeFile(path.join(frontend, 'css', 'fonts.css'), `${header}\n${sections.join('\n\n')}\n`);
  console.log('wrote frontend/css/fonts.css');

  const fraunces = path.join(frontend, 'assets', 'fonts', 'fraunces');
  await rm(fraunces, { recursive: true, force: true });
  await mkdir(fraunces, { recursive: true });
  await copyFile(path.join(modules, '@fontsource-variable', 'fraunces', 'LICENSE'), path.join(fraunces, 'OFL.txt'));
  execFileSync('python3', [
    path.join(root, 'tools', 'subset-fraunces.py'),
    path.join(modules, '@fontsource-variable', 'fraunces', 'files', 'fraunces-latin-full-normal.woff2'),
    path.join(fraunces, 'fraunces-sample-aan.woff2'),
  ], { stdio: 'inherit' });
}

main().catch((error) => {
  console.error(error.message);
  process.exit(1);
});
