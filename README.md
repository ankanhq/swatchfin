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

Swatchfin is in active development. Features marked `in progress` are not available yet.

- **Name or URL in, brand guide out.** Give it `duolingo` or `https://www.duolingo.com` and it finds the official site itself. `in progress`
- **Logo**: found in the page header, inline SVG, Open Graph image or favicon, with a download link. `in progress`
- **Colour palette with roles**: primary, secondary, accent, background, text, link and more, taken from the computed styles of real page elements rather than guessed from a screenshot. `in progress`
- **Contrast checks**: a WCAG contrast matrix for the palette, with AA/AAA badges. `in progress`
- **Typography**: heading, body and UI fonts, weights and sizes, with live specimens. `in progress`
- **Tone of voice**: traits, four tone spectrums and do/don't lists. Every claim is backed by an exact quote from the site. `in progress`
- **Key messaging**: tagline, mission, value propositions and audience, each linked to the page it came from. `in progress`
- **No invented data**: every quote is checked against the fetched text. If something can't be extracted, the guide says so with a warning instead of making it up. `in progress`
- **Exports for other tools**: JSON, CSS custom properties, Tailwind config, W3C Design Tokens and a ready-to-paste "write in this brand's voice" prompt. Print-ready page for PDF. `in progress`

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

Install and run instructions are coming soon.

## License

[MIT](LICENSE) © 2026 Ankan Chowdhury

The Swatchfin name and logo are not covered by the MIT licence.
