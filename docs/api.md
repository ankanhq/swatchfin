# Swatchfin API and guide format

This page describes the JSON that Swatchfin sends, so other tools can use its brand guides. The code that defines these shapes is [`backend/app/schemas.py`](../backend/app/schemas.py), and a running Swatchfin also shows them at `/api/docs`.

## Endpoints

Making a guide takes 30 to 90 seconds, so it runs as a background job. You start a job, then ask for its progress until it is `complete` or `failed`.

| Method | Path | What it does |
|---|---|---|
| `POST` | `/api/v1/guides` | Starts a guide. Body: `{ "query": "duolingo" }` (a company name or a URL). Answers `202 { "id", "status" }` |
| `GET` | `/api/v1/guides/{id}` | The job's status and its seven steps, plus the full guide once it is complete |
| `DELETE` | `/api/v1/guides/{id}` | Cancels a job that is still `queued` or `running` (`204`). After that, `GET` answers `404`. A finished guide answers `409`, because anyone with its link could otherwise delete it |
| `GET` | `/api/v1/guides/{id}/export?format=…` | Downloads the guide as `json`, `css`, `tailwind`, `tokens` or `voice` (see the README's Exports section). A format the guide has nothing for answers `409` |
| `GET` | `/api/v1/guides/{id}/logos/{n}.svg` or `.png` | Swatchfin's own copy of a logo the site draws in its page (`n` is 1 to 5) |
| `GET` | `/api/v1/health` | `{ "status": "ok" }` |

Example:

```bash
curl -X POST https://swatchfin.onrender.com/api/v1/guides \
  -H "Content-Type: application/json" -d '{"query": "stripe.com"}'
# {"id": "bg_7f3a9c", "status": "queued"}

curl https://swatchfin.onrender.com/api/v1/guides/bg_7f3a9c
```

### Errors

Every error has the same shape, written so it can be shown to people as it is:

```json
{ "error": { "title": "Guide not found", "message": "There is no guide with this ID…" } }
```

An unknown address under `/api/` answers this JSON too, never an HTML page.

### Limits

- A query can be up to 200 characters: one company name or one URL. A URL must be a public website, so IP addresses and local network names are refused.
- On the live site, each visitor can start 15 new guides in any 24 hours and make 300 API requests a minute. Everyone together can start 90 new guides a day (UTC).
- A complete guide for the same search or site from the last 24 hours is sent back again instead of making a new one. The same search while its guide is still being made joins that job.
- At most 2 guides are made at once, and up to 20 more can wait as `queued`. After that, `POST` answers `503`. Each job gets at most 150 seconds.
- Request bodies can be up to 16 KB.

## Job status

This is what `GET /api/v1/guides/{id}` answers:

```json
{
  "id": "bg_7f3a9c",
  "status": "running",
  "query": "duolingo",
  "started_at": "2026-10-10T12:00:00Z",
  "steps": [
    { "name": "resolving", "status": "done", "detail": "Found duolingo.com",
      "started_at": "2026-10-10T12:00:00Z", "finished_at": "2026-10-10T12:00:02Z" },
    { "name": "reading_homepage", "status": "running", "detail": null,
      "started_at": "2026-10-10T12:00:02Z", "finished_at": null }
  ],
  "tinyfish_usage": { "search_calls": 1, "fetch_urls": 0, "browser_sessions": 0 },
  "error": null,
  "guide": null
}
```

- `status` is `queued`, `running`, `complete` or `failed`.
- `steps` always lists all seven steps in this order: `resolving`, `reading_homepage`, `discovering_pages`, `reading_pages`, `reading_styles`, `analysing_voice`, `verifying`. (The example above shows only the first two.) Each step is `pending`, `running`, `done`, `skipped` or `failed`. `resolving` is `skipped` when the query was already a URL.
- `detail` is one short line for people, like "Found duolingo.com". Show it as plain text.
- `tinyfish_usage` counts the TinyFish calls made so far.
- `error` is `{ "title", "message" }` when the job failed.
- `guide` is the full brand guide (below) when the job is complete.

## The brand guide

A complete guide looks like this. Anything Swatchfin couldn't find on the site is `null` or an empty list, and `warnings` says why. Swatchfin never makes up a value to fill a gap.

The example is shortened from the sample guide in [`frontend/mock/MOCK_northwind-roasters.json`](../frontend/mock/MOCK_northwind-roasters.json). Northwind Roasters is a made-up brand used to build the guide page, and `…` marks text left out here.

```json
{
  "schema_version": "1.1",
  "id": "bg_MOCK_northwind",
  "status": "complete",
  "query": "Northwind Roasters",
  "generated_at": "2026-10-09T10:24:00Z",
  "brand": { "name": "Northwind Roasters", "domain": "northwind-roasters.example",
             "url": "https://northwind-roasters.example/", "description": "…", "language": "en" },
  "logo": {
    "primary": { "url": "…", "format": "svg",
                 "method": "header-img", "source_url": "https://northwind-roasters.example/",
                 "confidence": 0.94 },
    "alternates": [],
    "favicon": "…"
  },
  "colors": [
    { "hex": "#B5532A", "rgb": [181, 83, 42], "role": "primary",
      "usage": ["primary button background", "header call-to-action"], "share": 0.07,
      "source": "computed-style", "confidence": 0.93 }
  ],
  "contrast": [ { "fg": "#2B1D16", "bg": "#FFFCF7", "ratio": 15.91, "wcag": "AAA" } ],
  "typography": [
    { "role": "heading", "family": "Fraunces", "fallback_stack": "Georgia, \"Times New Roman\", serif",
      "weights": [600], "sizes_px": [56, 36, 24], "is_webfont": true,
      "source": "computed-style", "confidence": 0.92 }
  ],
  "voice": {
    "summary": "…",
    "traits": [ { "name": "Warm", "description": "…",
                  "evidence": [ { "quote": "…", "source_url": "https://northwind-roasters.example/…",
                                  "verified": true } ] } ],
    "spectrum": { "formal_casual": 70, "serious_playful": 40, "technical_simple": 58, "reserved_bold": 30 },
    "do": ["…"], "dont": ["…"],
    "drafted_by": { "api": "anthropic", "model": "claude-sonnet-5-5" }
  },
  "messaging": {
    "tagline": { "text": "Small-batch coffee, roasted on Tuesdays.", "source_url": "https://northwind-roasters.example/", "verified": true },
    "mission": { "text": "…", "source_url": "https://northwind-roasters.example/…", "verified": true },
    "value_props": [ { "title": "…", "quote": "…", "source_url": "…", "verified": true } ],
    "audience": ["…"]
  },
  "sources": [ { "url": "https://northwind-roasters.example/", "title": "…", "api": "search",
                 "fetched_at": "2026-10-09T10:22:41Z" } ],
  "tinyfish_usage": { "search_calls": 1, "fetch_urls": 6, "browser_sessions": 1 },
  "warnings": []
}
```

What each part means:

- **`schema_version`**: `"1.1"`. It changes when the shape changes in a way that could break a reader. Version 1.1 added the logo method `css-background`. Every 1.0 guide is also a valid 1.1 guide.
- **`brand`**: the brand's name, domain, homepage URL, the site's own description and its language.
- **`logo`**: the best logo (`primary`), other versions (`alternates`) and the tab icon (`favicon`).
  - `format` is `svg`, `png`, `webp`, `jpg` or `ico`.
  - `method` says how the logo was found: `header-img` (an image in the page), `inline-svg` (SVG code in the page, copied by Swatchfin), `css-background` (a CSS background picture, photographed in the browser), `og-image` (the social preview image) or `favicon` (the tab icon, used when nothing better was found).
  - A logo Swatchfin copied has a `url` on Swatchfin itself (`/api/v1/guides/{id}/logos/1.svg`). The free server forgets these copies when it restarts, so the CSS and tokens exports put small ones right into the file.
- **`colors`**: each colour with a `role`: `primary`, `secondary`, `accent`, `background`, `surface`, `text`, `text-muted`, `link` or `border`.
  - `usage` says in words where the site uses it.
  - `share` is the part of the visible page in that colour, from 0 to 1.
  - `source` is where it came from (`computed-style` means a real browser measured it on a real element).
- **`contrast`**: text and background pairs from the palette, with their WCAG contrast ratio and grade (`AAA`, `AA`, `AA-large` or `fail`).
- **`typography`**: fonts by `role` (`heading`, `body`, `ui`, `mono`), with the weights and sizes the page uses. `is_webfont` is true when the site loads the font itself.
- **`voice`**: a short summary, traits, four tone scales from 0 to 100 (0 is the first word, 100 the second, so `formal_casual: 80` means quite casual), and do and don't lists. `drafted_by` names the language model that wrote it (`anthropic`, `gemini` or `groq`). It is `null` when no model answered.
- **`messaging`**: the tagline, mission, value propositions and audience. Each one comes with a quote and the page it is on.
- **`verified`**: every quote in `voice` and `messaging` was looked for word for word in the text TinyFish read. Only spacing, quote marks and a final full stop may differ. A quote that wasn't found is left out of the guide, and `warnings` says so.
- **`sources`**: every page Swatchfin read, and which TinyFish API read it (`search`, `fetch` or `browser`).
- **`tinyfish_usage`**: how many TinyFish calls the guide used.
- **`warnings`**: plain sentences about anything missing or uncertain.
- **`confidence`**: on logos, colours and fonts, from 0 (a guess) to 1 (certain).

Swatchfin checks every guide against these shapes before sending it, and refuses any field that isn't listed here.
