<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="frontend/assets/brand/swatchfin-logo-dark.svg">
    <img src="frontend/assets/brand/swatchfin-logo.svg" alt="Swatchfin" width="212" height="64">
  </picture>
</p>

<p align="center"><strong>Brand guides from any URL, powered by TinyFish.</strong></p>

<p align="center">
  Type a company name or paste a website URL. Swatchfin reads the live site and returns a structured, verified brand guide: logo, colour palette, typography, tone of voice and key messaging.
</p>

<p align="center"><sub>Built for the TinyFish Student Bounty Drop 001, "Brand Guide Generator".</sub></p>

---

## Features

Swatchfin is in active development.

- **Name or URL in, brand guide out.** Give it `duolingo` or `https://www.duolingo.com` and it finds the official site itself.
- **Logo**: found in the page header, inline SVG, Open Graph image or favicon, with a download link.
- **Colour palette with roles**: primary, secondary, accent, background, text, link and more, taken from the computed styles of real page elements rather than guessed from a screenshot.
- **Contrast checks**: a WCAG contrast matrix for the palette, with AA/AAA badges.
- **Typography**: heading, body and UI fonts, weights and sizes, with live specimens.
- **Tone of voice**: traits, four tone spectrums and do/don't lists. Every claim is backed by an exact quote from the site.
- **Key messaging**: tagline, mission, value propositions and audience, each linked to the page it came from.
- **No invented data**: every quote is checked against the fetched text. If something can't be extracted, the guide says so with a warning instead of making it up.
- **Exports for other tools**: JSON, CSS custom properties, Tailwind config, W3C Design Tokens and a ready-to-paste "write in this brand's voice" prompt. Print-ready page for PDF.

## How TinyFish is used

Swatchfin uses three TinyFish APIs, and each one has a distinct job in the pipeline:

| TinyFish API | What it does in Swatchfin |
|---|---|
| **Search** | Turns a company name into its official domain, and finds brand or press-kit pages. |
| **Fetch** | Reads the live homepage HTML (logo, navigation, meta tags) and up to 10 sub-pages as markdown (About, Careers, Blog, Press, Product) for voice and messaging. |
| **Browser** | Opens the homepage in a real browser and reads the **computed** colours and fonts of real elements: buttons, headings, body text, links, navigation. |

```
name or URL → Search (resolve) → Fetch (homepage + sub-pages) → Browser (computed styles)
            → voice analysis → quote verification → BrandGuide JSON + page + exports
```

## Tech stack

| Layer | Tools |
|---|---|
| Frontend | Semantic HTML, CSS custom-property design system, Bootstrap 5.3 grid and reboot (heavily customised), vanilla JavaScript (ES modules), Lucide icons, self-hosted Inter, Inter Tight and JetBrains Mono |
| Backend | Python 3.11+, FastAPI, Uvicorn, Pydantic v2 |
| Web data | TinyFish Search, Fetch and Browser; Playwright over CDP; selectolax |
| Voice analysis | Anthropic Claude API, via a provider-agnostic wrapper |
| Quality | pytest, ruff |

The backend serves the frontend as static files, so the whole app deploys as one service.

## Getting started

**Requirements:** Python 3.11+, a TinyFish API key (free at [agent.tinyfish.ai](https://agent.tinyfish.ai)) and an [Anthropic API key](https://console.anthropic.com). Copy `.env.example` to `.env` and add your keys. Never commit `.env`.

```bash
git clone https://github.com/ankanhq/swatchfin.git
cd swatchfin
cp .env.example .env   # then add your keys to .env (it is git-ignored)
```

### Run the frontend

The frontend is a static site with no build step. Serve the `frontend` folder over HTTP (the icon sprite does not load from `file://`):

```bash
python3 tools/serve.py
```

Then open [http://localhost:8000](http://localhost:8000) (pass another port as an argument, e.g. `python3 tools/serve.py 8001`). This is the standard Python file server with two additions: the header `Cache-Control: no-cache`, so the browser re-checks every file on every load, and Swatchfin's own `404.html` for any missing address (try [localhost:8000/anything](http://localhost:8000/anything)), sent with a real 404 status as the production server will. Avoid plain `python3 -m http.server`: it sends no caching rules, the browser keeps old copies of edited files, and an old cached module mixed with a new one stops the guide page from loading. If a page ever looks out of date, do a hard refresh (Cmd+Shift+R / Ctrl+Shift+R).

**The guide page runs on mock data for now.** The backend that generates real guides is in progress, so the guide page uses a stand-in (`frontend/js/mock-job.js`) built around *Northwind Roasters*, a fictional brand. Submitting the form on the landing page plays a 10-second simulated run of the seven steps, labelled as a simulation, and then shows the sample guide. No website is read. These addresses show every state of the page:

| Address | What it shows |
|---|---|
| [`guide.html?q=Duolingo`](http://localhost:8000/guide.html?q=Duolingo) | A simulated run from a company name, then the sample guide |
| [`guide.html?q=stripe.com`](http://localhost:8000/guide.html?q=stripe.com) | The same from a URL (the search step is skipped) |
| [`guide.html?id=mock`](http://localhost:8000/guide.html?id=mock) | The finished sample guide (`frontend/mock/MOCK_northwind-roasters.json`) |
| [`guide.html?id=mock-partial`](http://localhost:8000/guide.html?id=mock-partial) | A partial guide: the browser step "timed out", so colours and fonts are missing |
| [`guide.html?id=mock-failed`](http://localhost:8000/guide.html?id=mock-failed) | A run that fails at "Reading the homepage" |
| [`guide.html`](http://localhost:8000/guide.html) | The empty state ("No guide to show") |
| [`guide.html?id=nope`](http://localhost:8000/guide.html?id=nope) | The "Guide not found" error |

The mock is only for building the frontend: it follows the exact BrandGuide and job status shapes in `CLAUDE.md`, and every part of it is labelled as mock.

### Development tools

Node.js is only used for small dev scripts. Nothing from `node_modules` is shipped to the browser.

```bash
npm install          # installs the pinned dev packages (Lucide, fonts, Bootstrap, Lighthouse)
npm run icons        # rebuilds frontend/assets/icons/icons.svg from the icon list in tools/build-icons.mjs
npm run vendor       # copies the fonts and Bootstrap's reboot + grid into frontend/, with their licences (needs Python fontTools for the Fraunces sample)
npm run logo         # rebuilds the animated header logos from the original logo files
npm run contrast     # checks every colour pair in frontend/css/tokens.css against WCAG 2.2 AA
npm run fonts        # rebuilds frontend/assets/data/google-fonts.json (Google Fonts family names and weights)
npm run lighthouse   # audits every page and guide state on mobile and desktop (dev server must be running)
```

The site serves everything from its own origin: no CDN or font service is needed to show a page. The only exception is below.

The guide page shows each detected font in that font when it can. It only asks Google Fonts for a family and weight that exist there, which it checks against `google-fonts.json`. A brand's self-hosted font is never requested; the specimen uses the fallback fonts and says so.

The social preview image (`frontend/assets/og-image.png`) is built from `tools/og-image.html`. The command is at the top of that file.

## Credits

- Icons: [Lucide](https://lucide.dev) (ISC licence, see `frontend/assets/icons/LICENSE.txt`)
- Fonts: [Inter](https://rsms.me/inter/), [Inter Tight](https://github.com/rsms/inter-tight), [JetBrains Mono](https://www.jetbrains.com/lp/mono/) and three letters of [Fraunces](https://github.com/undercasetype/Fraunces) (for the example card), served from this site via [Fontsource](https://fontsource.org). SIL Open Font License 1.1: see `OFL.txt` in each folder under `frontend/assets/fonts/`.
- Layout: [Bootstrap](https://getbootstrap.com) 5.3.3 reboot and grid (MIT licence, see `frontend/vendor/bootstrap/LICENSE`)

## License

[MIT](LICENSE) © 2026 Ankan Chowdhury

The Swatchfin name and logo are not covered by the MIT licence.
