# CLAUDE.md — Swatchfin

> Project context and working rules for Claude Code. Read this whole file before every task.

---

## 1. What we are building

**Swatchfin** turns any company name or website URL into a structured, verified **brand guide**: logo, colour palette (with roles), typography, tone of voice and key messaging, pulled from the **live website** using **TinyFish** web APIs.

- **Tagline:** "Brand guides from any URL, powered by TinyFish."
- **Who it's for:** marketers, designers and AI-CMO-style products that need a brand's identity fast and in a format other tools can use.
- **Built for:** TinyFish Student Bounty Drop 001, "Brand Guide Generator" (category: Marketing Package; type: API / Agentic App).
- **Owner:** Ankan (GitHub: ankanhq · TinyFish: AnkanXplorer). Repo: https://github.com/ankanhq/swatchfin The owner knows HTML and CSS well and a little JavaScript, and reviews every change. **Explain JavaScript and Python changes in plain, simple English.**

This is a real portfolio-grade product, not a demo hack. Code quality, design quality and honesty of the data all matter.

---

## 2. Bounty rules the build MUST satisfy

**Submission requirements**
1. Works from just a URL **or** a company name.
2. Uses TinyFish **Fetch** to read the live site (**Search** as needed).
3. Outputs a structured brand guide (JSON + page) with colours, fonts, logo and voice.
4. Demo on at least three different brands.
5. Short explanation of how TinyFish is used (README + About page).

**Approval criteria (every one must pass)**
1. Fetch does the core extraction work.
2. Extracted details are accurate to the live site.
3. Works for any site, not a hardcoded few.
4. Output is structured and reusable by other tools.
5. Goes beyond summarising a homepage.

**Scoring:** 3+ TinyFish endpoints = top tier, but **each one must contribute meaningfully** (no padding). We use exactly three, each with a real job:
| TinyFish API | Job in Swatchfin |
|---|---|
| **Search** | Resolve a company name → official domain; find brand/press-kit pages |
| **Fetch** | Read homepage HTML (logo, nav links, meta) and up to 10 sub-pages as markdown (About, Careers, Blog, Press, Product) |
| **Browser** | Open the live page in a real browser and read **computed** colours and fonts of real elements (buttons, headings, body, links, nav) |

**Fair-play rules (hard rules — never break them)**
- No copied or recycled code from other brand-extractor projects. Write original code.
- **No fake data.** Never invent colours, fonts, quotes or messages. If something can't be extracted, return `null` plus a warning. Every voice/messaging quote must be verified against fetched text.
- **Never commit API keys or secrets.** Keys live only in `.env` (git-ignored). Provide `.env.example` with empty values.
- No canned data in the real app. Mock data exists **only** for frontend development, uses a **fictional** brand, and is clearly labelled `MOCK`.

---

## 3. Tech stack

**Frontend** (`/frontend`), plain static site, no build step:
- HTML5 (semantic), CSS3 with a custom design system built on CSS custom properties
- **Bootstrap 5.3.3**, served from our own site: only its reboot and grid CSS, joined into `frontend/vendor/bootstrap/bootstrap-slim.min.css` (with its MIT `LICENSE` beside it) by `npm run vendor` from the pinned npm package. Customise it heavily so it does not look like default Bootstrap. (Phase 3 moved it off the CDN for mobile performance; the owner approved.)
- **Icons: Lucide** (ISC licence, free for any use; the clean 24px stroke style used by many modern apps). Do **not** load a whole icon font or runtime JS. Download only the icons we use from the `lucide-static` npm package (pin one version) into `frontend/assets/icons/`, build one SVG sprite (`icons.svg`), and use `<svg class="sf-icon"><use href="assets/icons/icons.svg#search"/></svg>`. Icons inherit `currentColor`, use one stroke width (1.75) and sizes 16/20/24 only. No emoji as icons, no Font Awesome.
- **Vanilla JavaScript** (ES modules, no frameworks, no jQuery). Keep JS small, readable and commented.
- Fonts, served from our own site: **Inter** (UI/body), **Inter Tight** (headings), **JetBrains Mono** (hex codes, code, JSON). `npm run vendor` copies them from pinned `@fontsource-variable` packages into `frontend/assets/fonts/<family>/` with each family's `OFL.txt`, and writes `css/fonts.css`. Google Fonts is only used on the guide page, at runtime, to show a brand's detected font in its typography specimen.

**Backend** (`/backend`):
- Python 3.11+, **FastAPI**, **Uvicorn**, **Pydantic v2**
- TinyFish Python SDK (`pip install tinyfish`) and/or `httpx` for REST
- **Playwright** (Python) connecting to TinyFish Browser via `connect_over_cdp`
- **selectolax** (or BeautifulSoup) for HTML parsing
- LLM for voice/messaging analysis: provider-agnostic wrapper, default **Anthropic Claude API**; key from `.env`
- **pytest** for tests, **ruff** for lint/format
- FastAPI also serves `/frontend` as static files, so the whole app deploys as **one service** (e.g. Render).

---

## 4. TinyFish API reference (verified from docs.tinyfish.ai)

Always re-check https://docs.tinyfish.ai before writing integration code.

- **Auth:** header `X-API-Key: $TINYFISH_API_KEY` (one key from agent.tinyfish.ai)
- **Search:** `GET https://api.search.tinyfish.ai?query=...` → structured ranked results. Free, ~30 req/min.
- **Fetch:** `POST https://api.fetch.tinyfish.ai`
  - body: `urls` (max 10), `format` = `html` | `markdown` (default) | `json`, `ttl` (`0` = force live fetch), `include_selectors` / `exclude_selectors` (max 20), `purpose` (≤2000 chars)
  - response: `results[]` with `url, final_url, title, description, language, format, text`; `errors[]` with per-URL failures (timeouts, anti-bot blocks)
  - Free up to 1,000 URLs/day. **Does not return images/binary**; get logo URLs by parsing HTML.
- **Browser:** `POST https://api.browser.tinyfish.ai` → `session_id`, `cdp_url`, `base_url`. Session creation takes 10–30 s (use ≥60 s timeout). Connect with Playwright `chromium.connect_over_cdp(cdp_url)`. End with `DELETE https://api.browser.tinyfish.ai/{session_id}`. **Browser costs wallet credit**: use one short session per brand and always close it (try/finally).
- Docs: https://docs.tinyfish.ai/fetch-api · https://docs.tinyfish.ai/search-api · https://docs.tinyfish.ai/browser-api

---

## 5. Extraction pipeline

```
input (name or URL)
 1. RESOLVE   – URL given? normalise it. Name given? TinyFish Search → pick official domain (skip Wikipedia, social, news).
 2. HOMEPAGE  – Fetch (format=html, ttl=0) → parse: logo candidates, favicon/apple-touch-icon, og:image,
                theme-color, meta description, nav/footer links.
 3. DISCOVER  – choose up to 9 high-value sub-pages from links (about, company, mission, careers, blog,
                press, newsroom, brand, product, pricing). Optionally Search "<brand> brand guidelines / press kit".
 4. CONTENT   – Fetch those pages (format=markdown) in one batch.
 5. VISUALS   – Browser session → homepage → getComputedStyle on body, h1–h3, p, a, nav, primary buttons/CTAs,
                header, footer. Weight colours by element importance and visible area. Read document.fonts for
                loaded web fonts. Confirm the logo element and its rendered size. Close session.
 6. VOICE     – LLM reads the fetched markdown → tone traits, 4 tone spectrums, do/don't, tagline, mission,
                value props, audience. Each item MUST include an exact quote + source URL.
 7. VERIFY    – Normalise whitespace and check every quote exists in the fetched text. Drop unverified items
                and add a warning. Compute WCAG contrast for palette pairs. Assign confidence scores.
 8. ASSEMBLE  – Build the BrandGuide JSON (schema below), store it, serve it to the UI and the export endpoints.
```

Error handling: per-step failures must not crash the whole job. Fetch blocked → fall back to Browser page content. Missing data → `null` + warning. Show clear, human-readable errors in the UI.

---

## 6. BrandGuide JSON schema (frontend ↔ backend contract)

The frontend is built first against this exact shape. Keep it stable; bump `schema_version` on breaking changes.

```json
{
  "schema_version": "1.0",
  "id": "bg_7f3a9c",
  "status": "complete",
  "query": "duolingo",
  "generated_at": "2026-10-10T12:00:00Z",
  "brand": { "name": "", "domain": "", "url": "", "description": "", "language": "en" },
  "logo": {
    "primary": { "url": "", "format": "svg|png|webp|jpg|ico", "method": "header-img|inline-svg|og-image|favicon", "source_url": "", "confidence": 0.0 },
    "alternates": [],
    "favicon": ""
  },
  "colors": [
    { "hex": "#000000", "rgb": [0, 0, 0], "role": "primary|secondary|accent|background|surface|text|text-muted|link|border",
      "usage": ["primary button background"], "share": 0.0, "source": "computed-style", "confidence": 0.0 }
  ],
  "contrast": [ { "fg": "#000000", "bg": "#FFFFFF", "ratio": 21.0, "wcag": "AAA|AA|AA-large|fail" } ],
  "typography": [
    { "role": "heading|body|ui|mono", "family": "", "fallback_stack": "", "weights": [400, 700],
      "sizes_px": [16], "is_webfont": true, "source": "computed-style", "confidence": 0.0 }
  ],
  "voice": {
    "summary": "",
    "traits": [ { "name": "", "description": "", "evidence": [ { "quote": "", "source_url": "", "verified": true } ] } ],
    "spectrum": { "formal_casual": 50, "serious_playful": 50, "technical_simple": 50, "reserved_bold": 50 },
    "do": [], "dont": []
  },
  "messaging": {
    "tagline":     { "text": "", "source_url": "", "verified": true },
    "mission":     { "text": "", "source_url": "", "verified": true },
    "value_props": [ { "title": "", "quote": "", "source_url": "", "verified": true } ],
    "audience": []
  },
  "sources": [ { "url": "", "title": "", "api": "search|fetch|browser", "fetched_at": "" } ],
  "tinyfish_usage": { "search_calls": 0, "fetch_urls": 0, "browser_sessions": 0 },
  "warnings": []
}
```

---

## 7. Backend API (our endpoints)

Generation takes 30–90 s, so it is an async job with polling.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v1/guides` | Body `{ "query": "duolingo" }` → `202 { id, status }` |
| `GET` | `/api/v1/guides/{id}` | Job status + live progress steps; full BrandGuide when `complete` |
| `GET` | `/api/v1/guides/{id}/export?format=json\|css\|tailwind\|tokens\|voice` | Downloadable exports |
| `GET` | `/api/v1/health` | Health check |

- `tokens` = W3C Design Tokens (DTCG) JSON. `voice` = a ready-to-paste "write in this brand's voice" prompt (markdown). PDF = the guide page's print stylesheet (browser "Save as PDF").
- Progress steps (shown live in the UI): `resolving → reading_homepage → discovering_pages → reading_pages → reading_styles → analysing_voice → verifying → complete | failed`.
- **Job status** returned by `GET /api/v1/guides/{id}`. The progress view on `guide.html` is built against this shape:
  ```json
  {
    "id": "bg_7f3a9c", "status": "queued|running|complete|failed", "query": "duolingo",
    "started_at": "2026-10-10T12:00:00Z",
    "steps": [ { "name": "resolving", "status": "pending|running|done|skipped|failed",
                 "detail": "Found duolingo.com", "started_at": "", "finished_at": "" } ],
    "tinyfish_usage": { "search_calls": 1, "fetch_urls": 0, "browser_sessions": 0 },
    "error": null,
    "guide": null
  }
  ```
  `steps` always lists the seven steps in order (`resolving` is `skipped` when a URL was given). `detail` is one short line for people, shown as plain text. `tinyfish_usage` counts the calls made so far. `error` is `{ "title", "message" }` when `failed`; `guide` is the full BrandGuide when `complete`.
- Validate input (length, URL format), rate-limit per IP, CORS restricted to our own origin, timeouts on every outbound call.
- Storage: in-memory + JSON files in `backend/data/guides/` is fine (git-ignored).
- Static files: serve `/frontend` with `Cache-Control: no-cache`, gzip for text files, and `404.html` with a real 404 status for unknown paths. `tools/serve.py` does all three in development; without them, cached modules break the guide page and mobile Lighthouse scores drop.

---

## 8. Frontend: pages and UX

1. **`index.html` (Landing):** hero with one big input ("Company name or URL") + Generate button, example chips (that just fill the input), "How it works" (3 TinyFish steps), feature grid, sample output preview, footer with "Powered by TinyFish".
2. **`guide.html?id=…` (Result):**
   - Progress view while running (step list with icons, spinner on the current step, elapsed time, cancel/back).
   - Guide view when complete: brand header (logo, name, domain, generated date) · **Logo** card with download link · **Colour palette** (large swatches, role, HEX/RGB, usage, click-to-copy with toast) · **Contrast matrix** with WCAG badges · **Typography** specimens rendered in the detected font when available · **Tone of voice** (traits with expandable proof quotes + source links, 4 spectrum sliders, do/don't lists) · **Key messaging** (tagline, mission, value props) · **Sources** (every URL, which TinyFish API read it) · **Warnings** · confidence badges · sticky **Export** bar (JSON, CSS, Tailwind, Tokens, Voice prompt, Print/PDF).
3. **`about.html`:** how Swatchfin works and how TinyFish is used (this is a bounty requirement), a pipeline diagram, limitations and privacy note.
4. **`404.html`**.

States to design for every view: loading, empty, partial result (with warnings), error, and success. **No lorem ipsum**: write real product copy.

---

## 9. Design system: make it look like a real product

Target quality: the polish of products like Linear, Vercel or Stripe docs. Calm, editorial, precise. It must **not** look vibe-coded.

- **Tokens** in `frontend/css/tokens.css` (`:root` custom properties): colours, spacing (4/8 px scale), radii, shadows, font sizes (modular scale), z-index, transitions.
- **Palette (from the logo):** ink `#0B0F19`, paper `#FAFAF7`, neutral greys, primary accent coral `#FF5A1F`, secondary accent amber `#FFB020` (use sparingly, mostly in the logo and highlights), plus success/warning/danger. Check AA contrast: coral on white is for large text, buttons with dark text or icons only. Use a darker coral (e.g. `#D9440F`) for small text and links. Full **dark mode** via `[data-theme="dark"]` + `prefers-color-scheme`, toggle saved in localStorage.
- Avoid AI-template clichés: no purple gradients, no glowing blobs, no emoji as icons, no random drop-shadows, no centred-everything layouts. Use whitespace, clear hierarchy, aligned grids and restrained motion.
- Icons: Lucide only, one stroke weight, aligned to text baseline, never decorative clutter.

### Brand assets (already designed, original, owned by the project)
Files live in `frontend/assets/brand/`. **Use them as they are. Do not redraw, recolour or distort the logo.**
| File | Use |
|---|---|
| `swatchfin-logo.svg` / `swatchfin-logo-dark.svg` | Header and footer lockup (mark + wordmark) on light / dark theme |
| `swatchfin-mark.svg` / `swatchfin-mark-dark.svg` | Mark alone (small spaces, loading state) |
| `swatchfin-app-icon.svg`, `favicon.svg`, `favicon-32.png`, `apple-touch-icon.png`, `app-icon-512.png` | Favicons, web manifest, social preview |

The mark is a fish fin (curved leading edge, concave trailing edge, flat base) split into three swatch cards (ink, coral, amber) that fan out from a rivet hole, like a paint swatch deck. It shows the name, *swatch + fin*. The gaps and rivet are real transparent cut-outs, so the mark works on any background. Minimum size 16 px. Keep clear space around it of at least 1/4 of the mark's height. Use the files with `<img>` tags (they contain masks with IDs, so don't paste several copies inline on one page). The wordmark is Inter Tight SemiBold, already converted to outlines. Make the OG image (1200×630) from the lockup on ink background.
- Responsive from 360 px to 1440 px+. Mobile is first-class.
- **Accessibility:** WCAG 2.2 AA contrast, visible focus rings, keyboard navigable, `aria-live` for progress and toasts, alt text, `prefers-reduced-motion` respected, proper labels.
- Print stylesheet (`print.css`) so "Save as PDF" produces a clean, branded one-page-per-section guide.
- Target Lighthouse ≥ 95 for Performance, Accessibility, Best Practices and SEO. Add meta description, Open Graph tags and a favicon.

---

## 10. Folder structure

```
swatchfin/
├── CLAUDE.md
├── README.md
├── LICENSE                      (MIT)
├── .gitignore
├── .env.example
├── frontend/
│   ├── index.html  guide.html  about.html  404.html
│   ├── css/      fonts.css (generated)  tokens.css  base.css  components.css  pages.css  print.css
│   ├── js/       api.js  app.js  guide.js  render/*.js  utils.js  theme.js
│   ├── assets/   brand/ (logo files, provided)  icons/icons.svg (Lucide sprite)  fonts/ (self-hosted, OFL)  og-image.png
│   ├── vendor/   bootstrap/ (reboot + grid, MIT; copied by npm run vendor)
│   └── mock/     MOCK_northwind-roasters.json   (fictional brand, dev only)
├── backend/
│   ├── app/
│   │   ├── main.py  config.py  schemas.py  jobs.py
│   │   ├── tinyfish/   search.py  fetch.py  browser.py
│   │   ├── extract/    resolve.py  homepage.py  discover.py  visuals.py  voice.py  verify.py  contrast.py
│   │   ├── export/     css.py  tailwind.py  tokens.py  voice_prompt.py
│   │   └── llm.py
│   ├── tests/
│   └── requirements.txt
└── docs/
    ├── how-tinyfish-is-used.md
    └── screenshots/
```

---

## 11. Coding standards

- **Security:** all website-derived text is untrusted. In JS insert it with `textContent` / `createElement`, **never** `innerHTML` with dynamic data. Only allow `http(s)` URLs in links/images. Escape everything in exports.
- HTML: semantic elements, one `<h1>` per page, no inline styles, no inline event handlers.
- CSS: custom properties for every colour/size, BEM-style class names (`.sf-swatch__hex`), Bootstrap overrides isolated in `components.css`. No `!important` unless overriding Bootstrap and commented.
- JS: ES modules, `const`/`let`, small pure functions, JSDoc comments, `async/await` with `try/catch`, no global variables, no console errors.
- Python: type hints everywhere, Pydantic models for all I/O, `async` HTTP with timeouts and retries, structured logging, no secrets in logs.
- Tests: unit tests for parsing, contrast maths, quote verification and exports; one integration test per TinyFish client (skipped if no key).
- Pin all dependency versions.

---

## 12. How Claude Code should work in this repo

1. **Plan first.** For each phase, show a short plan and wait for approval before writing code.
2. Work in **small, reviewable steps**. After each step, summarise what changed and how to check it (which file to open, what to click).
3. The owner reviews HTML/CSS directly. **Explain JS and Python in simple English**, with short comments in the code.
4. After each completed milestone, make a git commit using Conventional Commits (`feat:`, `fix:`, `style:`, `docs:`, `refactor:`, `test:`, `chore:`). Never commit `.env`, `data/` or secrets. Before committing, run `git status` and check that nothing secret is staged.
5. Never claim something works without running it. For frontend work, open the page (e.g. `python -m http.server` in `/frontend`) and check the console. For backend work, run the tests.
6. Ask instead of guessing when a requirement is unclear.
7. Keep `README.md` updated as features land.

---

## 13. Build phases

- [x] **Phase 0:** Repo setup: structure, `.gitignore`, `.env.example`, README skeleton, LICENSE, first commit, push to GitHub
- [x] **Phase 1:** Design system (`tokens.css`, `base.css`), header/footer, theme toggle, landing page
- [x] **Phase 2:** Guide result page rendered from `mock/MOCK_northwind-roasters.json`
- [x] **Phase 3:** Progress view, error/empty states, about page, 404, print stylesheet, accessibility + Lighthouse pass
- [ ] **Phase 4:** FastAPI skeleton, schemas, job system, serves frontend; frontend switches from mock to real API
- [ ] **Phase 5:** TinyFish Search + Fetch: resolve, homepage parsing, logo, page discovery, content
- [ ] **Phase 6:** TinyFish Browser: computed colours, fonts, logo confirmation
- [ ] **Phase 7:** Voice and messaging with LLM + quote verification + confidence + contrast
- [ ] **Phase 8:** Exports (JSON, CSS, Tailwind, DTCG tokens, voice prompt)
- [ ] **Phase 9:** Test on 10+ varied real sites, fix failures, remove mock usage from production paths
- [ ] **Phase 10:** Deploy, final README (with "How TinyFish is used"), screenshots, demo video on 3+ brands
- [ ] **Phase 11:** Submit: build link, LinkedIn post tagging TinyFish, #showcase on Discord

- [ ] **Phase 12 (only after the bounty is submitted and judged):** Rename this file. Move `CLAUDE.md` to `docs/PROJECT_BRIEF.md` with `git mv`, update any links to it, then commit as "docs: rename project brief" and push. Do this last, because after the rename Claude Code no longer reads these rules automatically.
