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

Swatchfin is in active development. Today it finds a brand's site, reads its homepage and up to nine more pages with TinyFish, opens the homepage in a real browser, and returns its name, description, logo (confirmed on the page, including logos drawn with SVG code), colour palette with roles, typography and sources. Contrast checks, tone of voice and messaging arrive in Phase 7.

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
| **Search** | Turns a company name into its official domain, and finds the brand's own pages that its homepage doesn't link to (brand guidelines, press kits, and About or careers pages on sites built with JavaScript). |
| **Fetch** | Reads the live homepage twice at once: its `<head>`, header, navigation, footer and logo word for word (for the logo, icons, meta tags and links), and its main text as markdown. Then reads up to 9 more pages as markdown (About, Mission, Careers, Press, Blog, Product) for voice and messaging. |
| **Browser** | Opens the homepage in a real browser (one short session per guide, always ended) and reads the **computed** colours and fonts of real elements: buttons, headings, body text, links, navigation. Confirms the logo on the page, and reads what Fetch can't: the homepage and up to 3 pages of sites built with JavaScript. About a tenth of a cent of wallet credit per guide. |

```
name or URL → Search (resolve) → Fetch (homepage) → Search + links (choose pages) → Fetch (pages)
            → Browser (computed styles) → voice analysis → quote verification → BrandGuide JSON + page + exports
```

The details, what was learned from the docs and live tests, and results on three very different sites are in [docs/how-tinyfish-is-used.md](docs/how-tinyfish-is-used.md).

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

### Set up (once per computer)

You need **Python 3.11 or newer** (check with `python3 --version`) and a **TinyFish API key** from [agent.tinyfish.ai](https://agent.tinyfish.ai/api-keys). The Anthropic key in `.env.example` is used from Phase 7. Without a TinyFish key the app still runs, but every guide stops with a message that it can't read websites.

```bash
git clone https://github.com/ankanhq/swatchfin.git
cd swatchfin
python3 -m venv .venv                          # a private folder of Python packages for this project (git-ignored)
source .venv/bin/activate                      # turn it on: your prompt now starts with (.venv)
python -m pip install --upgrade pip
pip install -r backend/requirements-dev.txt    # the pinned packages, plus pytest and ruff
cp .env.example .env                           # your settings and keys (git-ignored, never commit it)
```

Then open `.env` and put your key after `TINYFISH_API_KEY=`.

On Windows, turn the virtual environment on with `.venv\Scripts\activate` instead.

### Run Swatchfin

In every new terminal, turn the virtual environment on first, then start the server from the repo root:

```bash
source .venv/bin/activate
python tools/serve.py
```

Open [http://localhost:8000](http://localhost:8000). The interactive API docs are at [localhost:8000/api/docs](http://localhost:8000/api/docs). Press Ctrl+C to stop. To use another port, pass it as an argument: `python tools/serve.py 8001`.

This runs the FastAPI app in `backend/app` (the same app that runs in production). It serves the API under `/api/v1` and the website from `frontend/`. When you save a Python file in `backend/app`, it restarts by itself. For HTML, CSS and JavaScript changes, just reload the page.

Every file is sent with `Cache-Control: no-cache`, so the browser re-checks it on every load and never mixes an old cached module with a new one. Text files are gzip-compressed. Any missing address gets Swatchfin's own 404 page with a real 404 status (try [localhost:8000/anything](http://localhost:8000/anything)), while a missing `/api/...` address answers with JSON. If a page ever looks out of date, do a hard refresh (Cmd+Shift+R / Ctrl+Shift+R).

### Run the tests

```bash
pytest backend           # all backend tests, against a fake TinyFish (no network, no key needed)
pytest backend -m live   # the tests that call the real TinyFish APIs (needs the key; spends 1 search and 1 page)
ruff check backend       # code checks
ruff format backend      # formats the Python code
```

### The API

A guide takes 30–90 seconds, so it is made as a background job. Start one, then ask for its progress until it is `complete` or `failed`:

| Method | Path | What it does |
|---|---|---|
| `POST` | `/api/v1/guides` | Body `{ "query": "duolingo" }`. Answers `202 { "id", "status" }` straight away |
| `GET` | `/api/v1/guides/{id}` | The job's status and its seven steps; the full brand guide once it is complete |
| `DELETE` | `/api/v1/guides/{id}` | Cancels a job that is still queued or running (`204`). A finished guide answers `409` |
| `GET` | `/api/v1/guides/{id}/export?format=json` | Downloads the guide. `css`, `tailwind`, `tokens` and `voice` arrive in Phase 8 |
| `GET` | `/api/v1/guides/{id}/logos/{n}.svg` | A cleaned copy of a logo the site draws with SVG code (only shapes, colours and text), served so that it can't load or run anything |
| `GET` | `/api/v1/health` | `{ "status": "ok" }` |

Every error has the same shape, written for people: `{ "error": { "title": "Guide not found", "message": "There is no guide with this ID…" } }`. The exact shapes are in `CLAUDE.md` (sections 6 and 7), in `backend/app/schemas.py`, and at `/api/docs`.

Each visitor (IP address) can start 20 guides an hour and make 300 API requests a minute. At most two guides are made at once; the others wait their turn. Finished guides are saved in `backend/data/guides/` and their copied logos in `backend/data/logos/` (both git-ignored), and kept for 30 days. All of these can be changed in `.env` (see `.env.example`).

### What a guide has today

Steps 1–5 read the live site with TinyFish: finding the site (for a name), reading the homepage, choosing pages and reading them, then measuring the homepage's colours, fonts and logo in a real browser. Steps 6–7 (tone of voice, checking quotes and contrast) arrive in Phase 7; until then they show as skipped, and each guide's warnings say what it doesn't have yet. Nothing is made up to fill a gap. Each guide opens one TinyFish Browser session, which costs about $0.001 of wallet credit; set `USE_BROWSER=false` in `.env` to leave it out while developing. These addresses show every state of the guide page:

| Address | What it shows |
|---|---|
| [`guide.html?q=Patagonia`](http://localhost:8000/guide.html?q=Patagonia) | A real guide from a company name (uses your TinyFish key) |
| [`guide.html?q=stripe.com`](http://localhost:8000/guide.html?q=stripe.com) | The same from a URL (the search step is skipped) |
| [`guide.html?q=nothing-here.invalid`](http://localhost:8000/guide.html?q=nothing-here.invalid) | A guide that stops at "Reading the homepage": `.invalid` addresses never exist |
| [`guide.html?id=mock`](http://localhost:8000/guide.html?id=mock) | The full sample guide for *Northwind Roasters*, a fictional brand, labelled as mock data (`frontend/mock/MOCK_northwind-roasters.json`) |
| [`guide.html?id=mock-partial`](http://localhost:8000/guide.html?id=mock-partial) | A partial sample guide: the browser step "timed out", so colours and fonts are missing |
| [`guide.html`](http://localhost:8000/guide.html) | The empty state ("No guide to show") |
| [`guide.html?id=nope`](http://localhost:8000/guide.html?id=nope) | The "Guide not found" error |

Click **Cancel** while a guide is being made to go back to the start page with your search still in the box; the job is stopped on the server too.

The sample guides follow the exact BrandGuide and job status shapes in `CLAUDE.md` (the tests check this), and every part of them is labelled as mock. Real guides never use them.

The other pages: [`about.html`](http://localhost:8000/about.html) explains how Swatchfin uses TinyFish Search, Fetch and Browser (with a pipeline diagram, limitations and a privacy note), and any missing address shows the 404 page ([localhost:8000/anything](http://localhost:8000/anything)).

**Print or save as PDF.** On a guide, choose Export → *Print or save as PDF*, or press Cmd/Ctrl+P. The printout is always light, keeps the brand colours exact, starts with the brand header and warnings, and puts each section on its own page, with page numbers in Chrome and Edge.

### Quality checks

Last run (`npm run lighthouse`, Lighthouse 13.5.0, against the FastAPI app from `tools/serve.py`, after Phase 4):

| | Performance | Accessibility | Best Practices | SEO |
|---|---|---|---|---|
| Desktop, every page and guide state | 99–100 | 100 | 100† | 100 |
| Mobile: start, about, 404 | 96–100 | 100 | 100 | 100* |
| Mobile: guide states | 91–94‡ | 100 | 100† | 100 |

\* The 404 page is `noindex` on purpose, so its SEO score doesn't count.

† 96 on the "Guide not found" state: Chrome logs the server's real 404 answer in the console, and Lighthouse counts that.

‡ Mobile scores use Lighthouse's simulated slow phone and move between runs: the finished guide scored 85 once and 91 and 92 on two reruns. Most of the remaining time is the guide data arriving and being drawn, plus the Google Fonts request for the typography specimen.

Checked by hand as well: keyboard only (visible focus everywhere, nothing hidden under the sticky toolbar), no sideways scrolling at 320px, 24px touch targets, screen reader announcements for each progress step, reduced motion, and both themes.

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
