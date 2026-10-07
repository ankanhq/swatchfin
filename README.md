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

> **Status: early development (Phase 0 of 11).** The features below are what Swatchfin is being built to do. See the [roadmap](#roadmap) for progress.
>
> Built for the TinyFish Student Bounty Drop 001, "Brand Guide Generator".

---

## Features

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

A full write-up will live in [`docs/how-tinyfish-is-used.md`](docs/) and on the app's About page.

## Tech stack

| Layer | Tools |
|---|---|
| Frontend | Semantic HTML, CSS custom-property design system, Bootstrap 5.3 (heavily customised), vanilla JavaScript (ES modules), Lucide icons |
| Backend | Python 3.11+, FastAPI, Uvicorn, Pydantic v2 |
| Web data | TinyFish Search, Fetch and Browser; Playwright over CDP; selectolax |
| Voice analysis | Anthropic Claude API, via a provider-agnostic wrapper |
| Quality | pytest, ruff |

The backend serves the frontend as static files, so the whole app deploys as one service.

## Getting started

**Requirements:** Python 3.11+, a [TinyFish](https://agent.tinyfish.ai) API key and an [Anthropic](https://console.anthropic.com) API key.

```bash
git clone https://github.com/ankanhq/swatchfin.git
cd swatchfin
cp .env.example .env   # then add your keys to .env (it is git-ignored)
```

Install and run instructions will be added in Phase 4, when the backend lands.

## Project structure

```
swatchfin/
├── frontend/   static site: pages, CSS design system, JS modules, brand assets
├── backend/    FastAPI app: TinyFish clients, extraction pipeline, exporters, tests
└── docs/       how TinyFish is used, screenshots
```

## Roadmap

- [x] **Phase 0:** Repo setup
- [ ] **Phase 1:** Design system, header/footer, theme toggle, landing page
- [ ] **Phase 2:** Brand guide result page (rendered from a fictional mock brand)
- [ ] **Phase 3:** Progress view, error and empty states, About page, 404, print stylesheet, accessibility pass
- [ ] **Phase 4:** FastAPI backend, schemas, job system; frontend connected to the real API
- [ ] **Phase 5:** TinyFish Search + Fetch: resolve, homepage parsing, logo, page discovery
- [ ] **Phase 6:** TinyFish Browser: computed colours and fonts
- [ ] **Phase 7:** Tone of voice and messaging, with quote verification and contrast checks
- [ ] **Phase 8:** Exports: JSON, CSS, Tailwind, Design Tokens, voice prompt
- [ ] **Phase 9:** Testing on 10+ real websites
- [ ] **Phase 10:** Deploy, screenshots, demo on 3+ brands
- [ ] **Phase 11:** Bounty submission

## License

[MIT](LICENSE) © 2026 Ankan Chowdhury
