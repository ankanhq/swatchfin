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
| Frontend | Semantic HTML, CSS custom-property design system, Bootstrap 5.3 (heavily customised), vanilla JavaScript (ES modules), Lucide icons |
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
python3 -m http.server 8000 --directory frontend
```

Then open [http://localhost:8000](http://localhost:8000). This simple server lets the browser cache files, so use a hard refresh (Cmd+Shift+R / Ctrl+Shift+R) after editing CSS or JavaScript. The landing page works today. The guide page and the backend that generates guides are in progress, so submitting the form leads to a "not found" page for now.

### Development tools

Node.js is only used for small dev scripts. Nothing from `node_modules` is shipped to the browser.

```bash
npm install          # installs the pinned lucide-static package
npm run icons        # rebuilds frontend/assets/icons/icons.svg from the icon list in tools/build-icons.mjs
npm run logo         # rebuilds the animated header logos from the original logo files
npm run contrast     # checks every colour pair in frontend/css/tokens.css against WCAG 2.2 AA
```

The social preview image (`frontend/assets/og-image.png`) is built from `tools/og-image.html`. The command is at the top of that file.

## Credits

- Icons: [Lucide](https://lucide.dev) (ISC licence, see `frontend/assets/icons/LICENSE.txt`)
- Fonts: [Inter, Inter Tight](https://rsms.me/inter/) and [JetBrains Mono](https://www.jetbrains.com/lp/mono/) via Google Fonts (SIL Open Font License)

## License

[MIT](LICENSE) © 2026 Ankan Chowdhury

The Swatchfin name and logo are not covered by the MIT licence.
