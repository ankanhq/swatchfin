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

Swatchfin is in active development. Today it finds a brand's site, reads its homepage and up to nine more pages with TinyFish, opens the homepage in a real browser, and returns its name, description, logo (confirmed on the page, including logos drawn with SVG code), colour palette with roles, WCAG contrast checks, typography, tone of voice and key messaging (every claim backed by a quote found word for word on the site) and sources. Every guide downloads as JSON, CSS, a Tailwind theme, W3C Design Tokens and a voice prompt.

- **Name or URL in, brand guide out.** Give it `duolingo` or `https://www.duolingo.com` and it finds the official site itself.
- **Logo**: found in the page header, inline SVG, Open Graph image or favicon, with a download link.
- **Colour palette with roles**: primary, secondary, accent, background, text, link and more, taken from the computed styles of real page elements rather than guessed from a screenshot.
- **Contrast checks**: a WCAG contrast matrix for the palette, with AA/AAA badges.
- **Typography**: heading, body and UI fonts, weights and sizes, with live specimens.
- **Tone of voice**: traits, four tone spectrums and do/don't lists. Every claim is backed by an exact quote from the site.
- **Key messaging**: tagline, mission, value propositions and audience, each linked to the page it came from.
- **No invented data**: every quote is checked against the fetched text. If something can't be extracted, the guide says so with a warning instead of making it up.
- **Exports for other tools**: JSON, CSS custom properties, a Tailwind CSS v4 theme, W3C Design Tokens and a ready-to-paste "write in this brand's voice" prompt. Print-ready page for PDF.

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

You need **Python 3.11 or newer** (check with `python3 --version`) and a **TinyFish API key** from [agent.tinyfish.ai](https://agent.tinyfish.ai/api-keys). For the tone of voice and key messaging you also need an **Anthropic API key** from [console.anthropic.com](https://console.anthropic.com). Without a TinyFish key the app still runs, but every guide stops with a message that it can't read websites. Without an Anthropic key, guides have everything else, and their warnings say the tone of voice is missing.

```bash
git clone https://github.com/ankanhq/swatchfin.git
cd swatchfin
python3 -m venv .venv                          # a private folder of Python packages for this project (git-ignored)
source .venv/bin/activate                      # turn it on: your prompt now starts with (.venv)
python -m pip install --upgrade pip
pip install -r backend/requirements-dev.txt    # the pinned packages, plus pytest and ruff
cp .env.example .env                           # your settings and keys (git-ignored, never commit it)
```

Then open `.env` and put your keys after `TINYFISH_API_KEY=` and `ANTHROPIC_API_KEY=`. `ANTHROPIC_MODEL` chooses the Claude model; it is `claude-sonnet-5-5` unless you set another, such as `claude-opus-5-5`.

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
pytest backend -m live   # the tests that call the real TinyFish and Anthropic APIs (needs the keys; 1 search, 1 page, under $0.01)
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
| `GET` | `/api/v1/guides/{id}/export?format=json` | Downloads the guide as `json`, `css`, `tailwind`, `tokens` or `voice` (see [Exports](#exports)). A format the guide has nothing for answers `409` |
| `GET` | `/api/v1/guides/{id}/logos/{n}.svg` | A cleaned copy of a logo the site draws with SVG code (only shapes, colours and text), served so that it can't load or run anything |
| `GET` | `/api/v1/health` | `{ "status": "ok" }` |

Every error has the same shape, written for people: `{ "error": { "title": "Guide not found", "message": "There is no guide with this ID…" } }`. The exact shapes are in `CLAUDE.md` (sections 6 and 7), in `backend/app/schemas.py`, and at `/api/docs`.

Each visitor (IP address) can start 20 guides an hour and make 300 API requests a minute. At most two guides are made at once; the others wait their turn. Finished guides are saved in `backend/data/guides/` and their copied logos in `backend/data/logos/` (both git-ignored), and kept for 30 days. All of these can be changed in `.env` (see `.env.example`).

### What a guide has today

Steps 1–5 read the live site with TinyFish: finding the site (for a name), reading the homepage, choosing pages and reading them, then measuring the homepage's colours, fonts and logo in a real browser. Step 6 sends the text TinyFish read to Claude, which drafts the tone of voice and key messages with an exact quote for each claim. Step 7 looks for every quote, word for word, in that same text, drops what isn't there and says so in a warning, and grades the palette's text and background pairs for WCAG contrast. Nothing is made up to fill a gap. Each guide opens one TinyFish Browser session, which costs about $0.001 of wallet credit (set `USE_BROWSER=false` in `.env` to leave it out while developing), and makes one Claude call, which costs about $0.02–0.03 (see below). These addresses show every state of the guide page:

| Address | What it shows |
|---|---|
| [`guide.html?q=Patagonia`](http://localhost:8000/guide.html?q=Patagonia) | A real guide from a company name (uses your TinyFish key) |
| [`guide.html?q=stripe.com`](http://localhost:8000/guide.html?q=stripe.com) | The same from a URL (the search step is skipped) |
| [`guide.html?q=nothing-here.invalid`](http://localhost:8000/guide.html?q=nothing-here.invalid) | A guide that stops at "Reading the homepage": `.invalid` addresses never exist |
| [`guide.html?id=mock`](http://localhost:8000/guide.html?id=mock) | With `SAMPLE_GUIDES=true` only: the full sample guide for *Northwind Roasters*, a fictional brand, labelled as mock data (`frontend/mock/MOCK_northwind-roasters.json`) |
| [`guide.html?id=mock-partial`](http://localhost:8000/guide.html?id=mock-partial) | With `SAMPLE_GUIDES=true` only: a partial sample guide, whose browser step "timed out", so colours and fonts are missing |
| [`guide.html`](http://localhost:8000/guide.html) | The empty state ("No guide to show") |
| [`guide.html?id=nope`](http://localhost:8000/guide.html?id=nope) | The "Guide not found" error |

Click **Cancel** while a guide is being made to go back to the start page with your search still in the box; the job is stopped on the server too.

The sample guides follow the exact BrandGuide and job status shapes in `CLAUDE.md` (the tests check this), and every part of them is labelled as mock. They are for building the guide page, Lighthouse runs and tests, so the server serves them only when `SAMPLE_GUIDES=true` is in `.env`. It is off by default and in production, where no guide marked MOCK is ever served, not even one left in the guides folder. Real guides never use them.

The other pages: [`about.html`](http://localhost:8000/about.html) explains how Swatchfin uses TinyFish Search, Fetch and Browser (with a pipeline diagram, limitations and a privacy note), and any missing address shows the 404 page ([localhost:8000/anything](http://localhost:8000/anything)).

**Print or save as PDF.** On a guide, choose Export → *Print or save as PDF*, or press Cmd/Ctrl+P. The printout is always light, keeps the brand colours exact, starts with the brand header and warnings, and puts each section on its own page, with page numbers in Chrome and Edge.

### Tone of voice: how it's checked, and what it costs

Claude reads at most 36,000 characters of a brand's own pages (about 9,000 tokens): the homepage first, then brand, About and mission pages, with menus, footers and repeated lines removed. Its answer must follow a fixed shape, with a quote and a page address for every trait, tagline, mission and value proposition. Careers, jobs and culture pages describe how staff work, so Claude is told not to use them as evidence for traits, value propositions or the audience (a mission stated there still counts). `backend/app/extract/verify.py` then looks for each quote in the text TinyFish read, allowing only for differences in spacing, quote marks and a final full stop. A quote that isn't there is dropped, with a warning; a trait without a quote is dropped too.

Measured on 10 October 2026 with `claude-sonnet-5-5`. The server logs each guide's tokens and cost (`voice for stripe.com …`); the guide itself doesn't include them:

| Brand | Pages read | Tokens in + out | Claude cost | Claude time | Quotes found word for word |
|---|---|---|---|---|---|
| stripe.com | 7 | 10,388 + 1,141 | $0.032 | 10 s | 13 of 13 |
| Patagonia | 7 | 6,157 + 1,066 | $0.023 | 8 s | 11 of 11 |
| Duolingo | 4 | 5,087 + 1,102 | $0.021 | 8 s | 10 of 10 |

With `claude-opus-5-5` the same Duolingo text cost $0.046 (5,087 + 1,288 tokens, 12 s), and all 12 of its quotes were found too.

### Tested on 13 live sites (Phase 9)

On 12 October 2026 Swatchfin made guides for 13 sites, each checked by hand against the live page (logo, button colours, fonts, tagline, quotes and warnings), then again after the fixes. These are the final guides:

| Site | Primary (and other brand colours) | Fonts | Tagline |
|---|---|---|---|
| notion.so | `#0075DE` blue buttons, `#F64932` | NotionInter | “The AI workspace that works for you.” |
| airbnb.com | `#DA1249` search button | Airbnb Cereal VF | “Get an Airbnb for every kind of trip” |
| spotify.com (its web player) | `#1ED760` play button | SpotifyMixUI, SpotifyMixUITitle | none found |
| zomato.com | `#FFC6CD`, `#DFCFFF`, `#FFEEAF` (colour blocks; no colourful buttons) | Our Lexend | “Better food for more people” |
| nike.com | `#111111` black buttons | Nike Futura ND, Helvetica Now Text | “Nike. Just Do It” |
| mailchimp.com | `#FFE01B` yellow | Means Web, Graphik Web | none found |
| linear.app | `#E5E5E6` light buttons on near-black | Inter Variable, Berkeley Mono | “The system for product development” |
| figma.com | `#000000` black buttons, `#00B6FF` and `#24CB71` from the logo | figmaSans | “Figma: The collaborative canvas for design, code, and AI” |
| lego.com | `#F47D20` “Add to Bag”, `#FFD502` yellow header | Cera Pro | none (its headings are promotions) |
| tata.com | `#E2A330` gold buttons, `#0876B9` | Lato | “Leadership with Trust.” |
| ikea.com/de (German) | `#0058A3` blue, `#FFDB00` yellow | Noto IKEA | none found |
| champaca.in (an independent bookshop) | `#A3AB3B` olive buttons | Yrsa, PT Sans | none found |
| patagonia.com | `#000000` black buttons, `#1B2B79` navy hero | Ridgeway Sans | “MADE FOR THE MOMENT. BUILT FOR A LIFETIME.” |

Every logo is the brand's own, and 134 of 136 quotes were found word for word (the two that weren't were dropped, with a warning). Fixed along the way: homepages built with JavaScript measured before they had drawn (Spotify), buttons painted by an element inside them (Airbnb, IKEA, Spotify), colours hidden under album covers and photos, black-and-white brands without a primary colour (Nike, Figma), near-black “muted” text, a rarely used colour on the logo, a real button or a large first-screen block now listed with confidence 0.5 and a usage note, a photo labelled “Zomato logo” taken as the logo, one odd element or a slow page costing a guide all its colours (Tata, Mailchimp), taglines that are only in the page title (Nike, Tata), promotions as taglines, template galleries and customer stories read as the brand's pages, and names like “Nike.com” and “Official LEGO® Shop”.

Still true, and said on the About page: a colour the homepage shows only in a heading or not at all (Patagonia's orange `#FA4616` is one campaign heading today; Zomato's red isn't on its homepage) isn't listed; a web-app homepage like Spotify's changes between visits; and a short name can match the wrong site (“Tata” finds tata.cars; type “Tata group” or the address).

The 34 test guides cost $0.96 with Claude (288,810 input and 38,271 output tokens with `claude-sonnet-5-5`, about $0.03 a guide) and $0.046 of TinyFish wallet credit (51 Browser sessions, 24 minutes, including one-off checks). Search and Fetch cost nothing.

### Exports

Export on a guide page (or `GET /api/v1/guides/{id}/export?format=…`) downloads the guide in five formats. `backend/app/export/` has one module for each:

| Format | File | What's in it |
|---|---|---|
| `json` | `stripe-brand-guide.json` | The whole guide, in the versioned schema (`CLAUDE.md`, section 6) |
| `css` | `stripe-brand.css` | `--brand-color-<role>`, `--brand-font-<role>` and `--brand-logo` custom properties in `:root`, each with a note on where the site uses it |
| `tailwind` | `stripe-tailwind.css` | A Tailwind CSS v4 `@theme`: classes such as `bg-brand-primary`, `text-brand-text-muted` and `font-heading` |
| `tokens` | `stripe-brand.tokens.json` | [W3C Design Tokens, format 2025.10](https://www.designtokens.org/TR/2025.10/format/): sRGB colours, and a family, weights and sizes for each font role. Usage and confidence go under `$extensions` |
| `voice` | `stripe-voice-prompt.md` | A Markdown prompt: the voice in brief, traits with their quotes and pages, the four tone scales, do and don't, key messages |

What every export follows:

- **It says where it came from.** Each file starts with `Made by Swatchfin from the live site https://stripe.com/ on 10 October 2026.` (the guide's date). Sample guides say `MOCK sample data for a fictional brand, not a live site` instead. The JSON export is the one exception: it is exactly the guide's schema, which already has `generated_at`, `brand.url` and `sources`.
- **Only what was found.** A missing font means no font line, not a guessed one. The voice prompt has only quotes found word for word on the site, and leaves out a trait with none. The tokens file has no combined typography token, because the format needs line heights Swatchfin doesn't measure. A guide with no colours or fonts can't be exported as CSS, Tailwind or tokens (the menu greys them out and says why), and one with no tone of voice has no voice prompt.
- **Website text stays text.** Every value is put on one line and hidden direction-changing characters are removed. Font names become escaped CSS strings, so they can't add rules or end a `<style>` element. Comments can't be closed early. In the tokens file, font names with `{…}` are left out, because tools read those as links to other tokens. In the voice prompt, Markdown characters are escaped, so a quote can't become a link, an image, HTML or a heading. The prompt also says the quotes are examples of style, not instructions. The tests try all of this with a hostile guide (`backend/tests/export_guides.py`).
- **Copied logos get their whole address**, so the files work outside Swatchfin.

Use the Tailwind theme by importing it after Tailwind in your main CSS file:

```css
@import "tailwindcss";
@import "./stripe-tailwind.css";
```

Checked with real tools on 11 October 2026: Tailwind CSS 4.1.13 builds the classes from the Tailwind file, and Terrazzo 2.7.1 (`tz check`) finds no errors in the tokens file for Stripe, the sample guide and the hostile test guide.

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
