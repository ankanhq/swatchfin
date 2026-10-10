# How Swatchfin uses TinyFish

Swatchfin turns a company name or a URL into a brand guide by reading the live website. All of the reading is done by [TinyFish](https://tinyfish.ai) web APIs; Swatchfin decides what to read, parses it and checks it. Each API has a job the others can't do.

| TinyFish API | Job in Swatchfin | Calls per guide | Status |
|---|---|---|---|
| **Search** | Find the official site from a name; find the brand's own pages that its homepage doesn't link to | 1–3 | Live (Phase 5) |
| **Fetch** | Read the homepage (its structure and its text) and up to 9 more pages | up to 11 URLs | Live (Phase 5) |
| **Browser** | Measure the computed colours and fonts of real elements on the rendered homepage | 1 session | Phase 6 |

Every guide counts its calls (`tinyfish_usage`) and lists every page it read, with the API that read it (`sources`).

## Search

`GET https://api.search.tinyfish.ai`, code in [`backend/app/tinyfish/search.py`](../backend/app/tinyfish/search.py).

**1. Finding the official site** ([`extract/resolve.py`](../backend/app/extract/resolve.py)), only when a company name is typed:

- One search for the name, with `exclude_domains` set to sites that write *about* companies rather than *for* them (Wikipedia, social networks, app stores, company-data, review and news sites), and a `purpose` that says we want the official homepage. A site that *is* the name searched for (say, LinkedIn) is not excluded.
- Swatchfin scores what is left: first how well the address matches the name (`patagonia.com` for "Patagonia", `marksandspencer.com` for "Marks & Spencer"), then search rank, then a plain homepage over a deep page and the main site over a subdomain. It reads the site from its front door (`https://www.patagonia.com/`), whichever page of it the result was.
- When no address contains the name (for example 任天堂, Nintendo's name in Japanese, which finds `nintendo.com`), the best result is still used, and the guide warns that it may be the wrong company.

**2. Finding pages** ([`extract/discover.py`](../backend/app/extract/discover.py)), limited to the brand's own site with `include_domains`:

- Always: one search for brand guidelines, brand assets and press kits, which homepages rarely link to.
- Only when the homepage's links lead to fewer than three of About, mission, careers and press: one search for those. This is how Swatchfin finds pages on sites built with JavaScript, whose homepage gives Fetch no links at all.

Search results join the homepage's links and are scored the same way (see Fetch, step 3 below).

## Fetch

`POST https://api.fetch.tinyfish.ai`, code in [`backend/app/tinyfish/fetch.py`](../backend/app/tinyfish/fetch.py). Every request sets `ttl: 0` (a live copy, never a cached one) and a per-page time limit.

**What we learned from the docs and live tests.** `format: "html"` returns the page's *main content* as cleaned HTML: no `<head>`, no `<meta>` or icon links, no header, navigation or footer, no `<img>` or `<svg>`. That leaves out exactly what a brand guide needs from a homepage. But `include_selectors` returns the parts it names *word for word* (only scripts and styles are stripped). So Swatchfin asks for those parts by name.

**Step 2: the homepage, read twice at once** ([`extract/homepage.py`](../backend/app/extract/homepage.py)):

| Read | Request | Used for |
|---|---|---|
| Structure | `format: "html"`, `include_selectors: ["head", "header", "nav", "footer", "[class*=logo]", "[aria-label*=logo]", "[alt*=logo]", "[class*=brand]", "a[href='/']", …]` | Brand name (`og:site_name`, `application-name`), description, theme colour, icons, the Open Graph image, the logo, and the main links with their words |
| Content | `format: "markdown"`, `links: true`, `image_links: true` | The homepage's main text (for tone of voice in Phase 7) and every link on the page |

The logo is the image or inline SVG inside the link back to the homepage, or one labelled as a logo in the header or nav. Logos of other companies on the page (customers, partners) carry other names and are left out. Many sites draw the logo once in a hidden SVG sprite (`<symbol id="logo">`) and show it with `<use href="#logo">`; Swatchfin copies the symbol in, so the logo works on its own.

A logo drawn with SVG code has no file address. Swatchfin rebuilds it from an allow-list (only shapes, colours and text; links only inside the SVG; no scripts, styles, images, embedded HTML or outside addresses; see [`extract/svg.py`](../backend/app/extract/svg.py)) and serves the copy at `/api/v1/guides/{id}/logos/{n}.svg` with a Content-Security-Policy that blocks everything.

**Step 3: choosing pages.** Every link and search result is sorted into a kind by its address and words (brand assets, about, mission and values, product, careers, press, blog, pricing) and scored: more useful kinds first, then links from the main navigation, then short addresses over deep ones (the Careers page over one job advert). Logins, legal pages, files, other sites and copies of the site in other languages are left out. Up to 9 pages are kept, at most one or two of each kind.

**Step 4: the pages, in one batch** ([`extract/pages.py`](../backend/app/extract/pages.py)): `format: "markdown"`, up to 9 URLs. A page that is blocked, empty, gone or redirects to another website is skipped, and the guide's warnings say which and why.

## Browser (Phase 6)

One short TinyFish Browser session per guide will open the homepage in a real browser, read the computed colours and fonts of real elements with Playwright over CDP, confirm the logo, and always be closed. Until then, guides say that colours and fonts aren't measured yet, and nothing is made up to fill the gap.

## When something goes wrong

| What happens | Result |
|---|---|
| No site at the address (unreachable, 404) | The guide stops: "Swatchfin couldn't read example.com: the site couldn't be reached." |
| No official website found for a name | The guide stops and suggests typing the web address instead |
| No TinyFish key, a rejected key, or the free allowance used up (`402`) | The guide stops with a message for people; nothing is sent without a key |
| TinyFish busy (`429`) or a passing error (`5xx`, dropped connection) | Retried twice, after 1 s and 2 s (or what `Retry-After` asks, up to 5 s) |
| A page blocked by an anti-bot check, too slow, or empty | Skipped with a warning; the guide carries on |
| A homepage built only with JavaScript | The guide carries on with what Fetch could read and says what is missing (Phase 6's browser will read it) |
| A discovery search that stays busy | The homepage's own links are used, with a warning |

The API key is sent only from the server, in the `X-API-Key` header. It is kept as a secret string, so it never appears in logs or error messages. Swatchfin never fetches a brand's website itself: every read goes through TinyFish, which also refuses private network addresses.

## Live results (10 October 2026)

Three very different sites, run through the real app:

| | Patagonia (typed as a name) | stripe.com (typed as a URL) | Duolingo (typed as a name) |
|---|---|---|---|
| Kind of site | Retail, custom HTML elements, logo in an SVG sprite | Software, Next.js, inline SVG logo | App built with JavaScript |
| Site found | patagonia.com | (given) | duolingo.com |
| Logo | Inline SVG, rebuilt from its `<symbol>` | Inline SVG, Stripe navy `#031323` | None: the homepage has no HTML without JavaScript |
| Pages chosen | 8: company history, core values, activism, careers, stories, product guides… (3 found by search) | 6: About, Products, Press, Careers, Blog, Pricing | 3, all found by search |
| Pages read | 7 (Press redirected to patagoniaworks.com) | 6 | 2 (Careers is JavaScript-only too) |
| TinyFish calls | 2 searches, 10 Fetch URLs | 1 search, 8 Fetch URLs | 3 searches, 5 Fetch URLs |

## Limits and costs

- Search: free up to 12,000 calls a day, 30 a minute per key.
- Fetch: free up to 1,000 URLs a day (counted per page read), 150 URLs a minute per key. At up to 11 URLs per guide, that is roughly 90 guides a day.
- Fetch gives up on a page after 110 s at most; Swatchfin allows 40 s for the homepage and 30 s for other pages, so a guide stays inside its 150-second limit with room for the browser and voice steps.

Docs: [Search](https://docs.tinyfish.ai/search-api) · [Fetch](https://docs.tinyfish.ai/fetch-api) · [Browser](https://docs.tinyfish.ai/browser-api)
