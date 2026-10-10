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

### Set up (once per computer)

You need **Python 3.11 or newer**. Check with `python3 --version`. API keys aren't needed yet: live generation arrives in Phase 5, and until then every run ends with the sample guide (see below).

```bash
git clone https://github.com/ankanhq/swatchfin.git
cd swatchfin
python3 -m venv .venv                          # a private folder of Python packages for this project (git-ignored)
source .venv/bin/activate                      # turn it on: your prompt now starts with (.venv)
python -m pip install --upgrade pip
pip install -r backend/requirements-dev.txt    # the pinned packages, plus pytest and ruff
cp .env.example .env                           # your settings and keys (git-ignored, never commit it)
```

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
pytest backend         # all backend tests
ruff check backend     # code checks
ruff format backend    # formats the Python code
```

### The API

A guide takes 30–90 seconds, so it is made as a background job. Start one, then ask for its progress until it is `complete` or `failed`:

| Method | Path | What it does |
|---|---|---|
| `POST` | `/api/v1/guides` | Body `{ "query": "duolingo" }`. Answers `202 { "id", "status" }` straight away |
| `GET` | `/api/v1/guides/{id}` | The job's status and its seven steps; the full brand guide once it is complete |
| `DELETE` | `/api/v1/guides/{id}` | Cancels a job that is still queued or running (`204`). A finished guide answers `409` |
| `GET` | `/api/v1/guides/{id}/export?format=json` | Downloads the guide. `css`, `tailwind`, `tokens` and `voice` arrive in Phase 8 |
| `GET` | `/api/v1/health` | `{ "status": "ok" }` |

Every error has the same shape, written for people: `{ "error": { "title": "Guide not found", "message": "There is no guide with this ID…" } }`. The exact shapes are in `CLAUDE.md` (sections 6 and 7), in `backend/app/schemas.py`, and at `/api/docs`.

Each visitor (IP address) can start 20 guides an hour and make 300 API requests a minute. At most two guides are made at once; the others wait their turn. Finished guides are saved in `backend/data/guides/` (git-ignored) and kept for 30 days. All of these can be changed in `.env` (see `.env.example`).

### Live generation isn't connected yet

The backend, the job system and the API are real, but the seven steps are placeholders until Phases 5–7 connect TinyFish. Each step waits a second and says it is a placeholder, no website is read, no TinyFish calls are made, and every run ends with the sample guide for *Northwind Roasters*, a fictional brand. The page labels it as mock data. These addresses show every state of the guide page:

| Address | What it shows |
|---|---|
| [`guide.html?q=Duolingo`](http://localhost:8000/guide.html?q=Duolingo) | A run from a company name, then the sample guide |
| [`guide.html?q=stripe.com`](http://localhost:8000/guide.html?q=stripe.com) | The same from a URL (the search step is skipped) |
| [`guide.html?q=fail.invalid`](http://localhost:8000/guide.html?q=fail.invalid) | A run that fails at "Reading the homepage". Addresses ending in `.invalid` (reserved, so they never exist) fail on purpose until Phase 5 |
| [`guide.html?id=mock`](http://localhost:8000/guide.html?id=mock) | The finished sample guide (`frontend/mock/MOCK_northwind-roasters.json`) |
| [`guide.html?id=mock-partial`](http://localhost:8000/guide.html?id=mock-partial) | A partial guide: the browser step "timed out", so colours and fonts are missing |
| [`guide.html`](http://localhost:8000/guide.html) | The empty state ("No guide to show") |
| [`guide.html?id=nope`](http://localhost:8000/guide.html?id=nope) | The "Guide not found" error |

Click **Cancel** while a guide is being made to go back to the start page with your search still in the box; the job is stopped on the server too.

The mock data follows the exact BrandGuide and job status shapes in `CLAUDE.md` (the tests check this), and every part of it is labelled as mock.

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
