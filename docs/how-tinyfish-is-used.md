# How Swatchfin uses TinyFish

Swatchfin turns a company name or a URL into a brand guide by reading the live website. All of the reading is done by [TinyFish](https://tinyfish.ai) web APIs; Swatchfin decides what to read, parses it and checks it. Each API has a job the others can't do.

| TinyFish API | Job in Swatchfin | Calls per guide | Status |
|---|---|---|---|
| **Search** | Find the official site from a name; find the brand's own pages that its homepage doesn't link to | 1–3 | Live (Phase 5) |
| **Fetch** | Read the homepage (its structure and its text) and up to 9 more pages | up to 11 URLs | Live (Phase 5) |
| **Browser** | Measure the colours and fonts the browser really draws, confirm the logo, and read what Fetch can't (pages built with JavaScript) | 1 session, about 20–35 s | Live (Phase 6) |

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
| Content | `format: "markdown"`, `links: true`, `image_links: true` | The homepage's main text (what Claude reads for the tone of voice, and what its quotes are checked against) and every link on the page |

The logo is the image or inline SVG inside the link back to the homepage, or one labelled as a logo in the header or nav. Logos of other companies on the page (customers, partners) carry other names and are left out. Many sites draw the logo once in a hidden SVG sprite (`<symbol id="logo">`) and show it with `<use href="#logo">`; Swatchfin copies the symbol in, so the logo works on its own.

A logo drawn with SVG code has no file address. Swatchfin rebuilds it from an allow-list (only shapes, colours and text; links only inside the SVG; no scripts, styles, images, embedded HTML or outside addresses; see [`extract/svg.py`](../backend/app/extract/svg.py)) and serves the copy at `/api/v1/guides/{id}/logos/{n}.svg` with a Content-Security-Policy that blocks everything.

**Step 3: choosing pages.** Every link and search result is sorted into a kind by its address and words (brand assets, about, mission and values, product, careers, press, blog, pricing) and scored: more useful kinds first, then links from the main navigation, then short addresses over deep ones (the Careers page over one job advert). Logins, legal pages, files, other sites and copies of the site in other languages are left out. Up to 9 pages are kept, at most one or two of each kind.

**Step 4: the pages, in one batch** ([`extract/pages.py`](../backend/app/extract/pages.py)): `format: "markdown"`, up to 9 URLs. A page that is blocked, empty, gone or redirects to another website is skipped, and the guide's warnings say which and why.

## Browser

`POST https://api.browser.tinyfish.ai` starts a real Chrome in the cloud and answers with a `cdp_url`; Swatchfin connects to it with Playwright (`connect_over_cdp`) and ends it with `DELETE https://api.browser.tinyfish.ai/{session_id}`. Code in [`backend/app/tinyfish/browser.py`](../backend/app/tinyfish/browser.py) and [`extract/visuals.py`](../backend/app/extract/visuals.py).

**One short session per guide, always ended.** Browser is the one API that costs wallet credit (by the minute), so:

- The session is asked for as soon as the website is known, with the homepage as its start page. TinyFish gets it ready while Fetch reads (steps 2–4), so the guide doesn't wait for it.
- It is ended straight after step 5, in a `finally` block: whether the guide finished, failed, was cancelled or ran out of time. A session still starting when a guide stops is ended in the background the moment it exists.
- As a safety net, every session is created with `timeout_seconds: 180`, so TinyFish ends it itself after 3 idle minutes if ending it ever fails.
- If the browser can't be used (busy, no credit, the page won't load), the guide still finishes with what Fetch read, and its warnings say that colours and fonts are missing. Nothing is guessed to fill the gap.

**Step 5: measuring the homepage.** One script, [`measure_page.js`](../backend/app/extract/measure_page.js), runs in the page at 1440 × 900 px once it has loaded and its web fonts are ready. Cookie banners and pop-ups covering the page are hidden in this private browser first; nothing is clicked or accepted. The script records:

| What | How | Used for |
|---|---|---|
| Every element with text, a background or a border (up to 2,500) | `getComputedStyle`: the colour the browser really draws, with see-through colours blended onto what is behind them, and colours in any CSS format (`oklch()`, `color()`…) turned into `#RRGGBB` | Colour roles, fonts |
| Buttons, including links drawn as buttons | A filled or outlined box of button size; a fill painted on `::before` or `::after` counts (Duolingo's green "Get started" is one) | The primary colour |
| The first screen, point by point (every 24 px) | `elementFromPoint` and the background drawn there; photos, videos and gradients count as images | Each colour's share of the visible area |
| The web fonts | `document.fonts` (those loaded) | Which font each piece of text is really set in |
| The `<head>`, header, nav, footer and logo parts | The same parts Fetch reads, as the browser drew them, with a number on every image and SVG and its size, visibility and colour on screen | Confirming the logo; filling Fetch's gaps |
| The visible text and links | `innerText`, `a[href]` | Filling Fetch's gaps |

Then, in Python, each colour gets one role. The background is what the page itself is painted with. The text colour is the neutral that stands out most among those used for at least 5% of the text on the page background (text on photos or coloured sections doesn't count). The primary is the colourful colour the buttons use most; without one, a strong neutral button fill (black buttons); without that, the most used colourful colour. Then come the link colour, secondary and accent (clearly different colourful colours with real evidence), muted text, surface and border. Colours nobody could tell apart (delta E below 3) count as one. Every colour lists what it is used for ("button background, link text") and how sure Swatchfin is.

**Checking the logo.** The logo Fetch found is looked up among the images and SVGs the browser numbered (same file address, or an SVG with the same shapes). One shown near the top of the page at a real size is confirmed (confidence up, size on screen in the step's detail line); a hidden copy, such as a phone-menu version, drops behind the visible one. A logo drawn in `currentColor` takes its colour from the page, so Swatchfin's copy is given the colour measured there instead of being black.

**Filling Fetch's gaps.** On a site built with JavaScript, Fetch gets almost nothing. The browser's copy of the page is read by the same code as Fetch's ([`extract/homepage.py`](../backend/app/extract/homepage.py)), so its logo, icons, description and text fill what is missing. Pages Fetch couldn't read because they were empty without JavaScript, blocked or too slow (up to 3) are opened in the same session and their visible text read. They are listed under sources with the API **Browser**. Fetch still does the core reading; the browser only fills gaps.

**What we learned from the docs and live tests.**

- Sessions started in 3.5–5 seconds, faster than the docs' 10–30 s (Swatchfin still allows 60 s).
- Browser is billed by the second at $0.002 a minute: the wallet balance (`GET https://agent.tinyfish.ai/v1/wallet`, which also lists the rates) fell by exactly the session times that `GET https://api.browser.tinyfish.ai/usage` reported.
- Sites hide a lot in the rendered page: Stripe's hero headline stacks two copies of its text in different colours to animate between them (counted once), Patagonia's logo is on the page twice (one hidden in the phone menu), and Patagonia's rendered `og:site_name` is "Patagonia United States" (region labels are now left off names).

## After TinyFish: tone of voice, checked against what Fetch read

Steps 6 and 7 don't call TinyFish, but they rest on its work. The text TinyFish read (the homepage's markdown, the other pages' markdown, and the visible text of any page only Browser could read) is the one source of truth for the tone of voice:

- **Step 6** ([`extract/voice.py`](../backend/app/extract/voice.py), [`llm.py`](../backend/app/llm.py)) sends that text to Claude, cleaned and cut to at most 36,000 characters. Claude never browses: it can only quote what TinyFish read.
- **Step 7** ([`extract/verify.py`](../backend/app/extract/verify.py)) looks for every quote in the same text, word for word, and drops what isn't there. A quote found on a different page than the one Claude named is credited to the page it is really on, so every source link in a guide points to a page TinyFish read.

## When something goes wrong

| What happens | Result |
|---|---|
| No site at the address (unreachable, 404) | The guide stops: "Swatchfin couldn't read example.com: the site couldn't be reached." |
| No official website found for a name | The guide stops and suggests typing the web address instead |
| No TinyFish key, a rejected key, or the free allowance used up (`402`) | The guide stops with a message for people; nothing is sent without a key |
| TinyFish busy (`429`) or a passing error (`5xx`, dropped connection) | Retried twice, after 1 s and 2 s (or what `Retry-After` asks, up to 5 s) |
| A page blocked by an anti-bot check, too slow, or empty | Skipped with a warning; the guide carries on |
| A homepage built only with JavaScript | The browser reads it instead: logo, icons, description and text, and up to 3 pages Fetch couldn't read |
| The browser is busy, out of credit, or can't open the page | Step 5 is skipped with a warning; the guide keeps everything Fetch read |
| The guide is cancelled or runs out of time | The browser session is ended anyway (and ends itself after 3 idle minutes if that ever fails) |
| A discovery search that stays busy | The homepage's own links are used, with a warning |
| No Anthropic key, Claude busy, slow or refusing, or a quote not on the page | The tone of voice (or that part of it) is left out with a warning; everything TinyFish read stays |

The API key is sent only from the server, in the `X-API-Key` header. It is kept as a secret string, so it never appears in logs or error messages. Swatchfin never fetches a brand's website itself: every read goes through TinyFish, which also refuses private network addresses.

## Live results (10 October 2026, Phase 6)

Three very different sites, run through the real app:

| | stripe.com (typed as a URL) | patagonia.com (typed as a URL) | Duolingo (typed as a name) |
|---|---|---|---|
| Kind of site | Software, Next.js, inline SVG logo | Retail, custom HTML elements, logo in an SVG sprite | App built with JavaScript |
| Logo | Inline SVG, confirmed at 60 × 25 px | Inline SVG, confirmed at 120 × 22 px (a hidden copy in the phone menu set aside) | Found by the browser (Fetch saw none): image, confirmed at 179 × 42 px |
| Colours | Primary `#533AFD` (buttons, links), secondary navy `#0D1738`, text `#061B31`, muted `#50617A`, surface `#E5EDF5` and 3 more | Primary `#1B2B79` (a section; no coloured buttons, so medium confidence), text `#000000`, surface `#F5F5F5`; 40% of the first screen is photos | Primary `#58CC02` ("Get started"), link `#1CB0F6`, secondary `#100F3E`, text `#4B4B4B`, muted `#777777` and 3 more |
| Fonts | `sohne-var` throughout, weights 300 and 400 | Ridgeway Sans, weights 300–700 | `feather` for headings, `duolingo-sans` for text |
| Pages chosen | 6: About, Products, **Newsroom** (not Stripe Press, a book publisher), Careers, Blog, Pricing | 8: company history, core values, activism, careers, stories, product guides… | 3, all found by search |
| Pages read | 6 by Fetch | 7 by Fetch (Press redirected to patagoniaworks.com) | 2 by Fetch, plus about.duolingo.com by Browser |
| TinyFish calls | 1 search, 8 Fetch URLs, 1 browser session (17 s) | 1 search, 10 Fetch URLs, 1 browser session (25–29 s) | 3 searches, 5 Fetch URLs, 1 browser session (33 s) |
| Whole guide | 18 s | 25–31 s | 35 s |

## Live results (10 October 2026, Phase 7)

The same three sites, with tone of voice from `claude-sonnet-5-5`:

| | stripe.com | Patagonia | Duolingo |
|---|---|---|---|
| Text Claude read | 7 pages, 10,388 tokens | 7 pages, 6,157 tokens | 4 pages (the homepage and About page read by Browser), 5,087 tokens |
| Quotes found word for word | 13 of 13 | 11 of 11 | 10 of 10 |
| Tagline | "Financial infrastructure to grow your revenue." | "MADE FOR THE MOMENT. BUILT FOR A LIFETIME." | "The most fun way to learn languages, chess, and more!" |
| Mission | "Our mission is to increase economic growth." (Careers page) | None on the pages read, so none in the guide | "Develop the best education in the world and make it universally available." |
| Colour pairs graded | 15 | 3 | 11 |
| Whole guide | 26–32 s | 44 s | 46 s |

## Limits and costs

- Search: free up to 12,000 calls a day, 30 a minute per key.
- Fetch: free up to 1,000 URLs a day (counted per page read), 150 URLs a minute per key. At up to 11 URLs per guide, that is roughly 90 guides a day.
- Fetch gives up on a page after 110 s at most; Swatchfin allows 40 s for the homepage and 30 s for other pages, so a guide stays inside its 150-second limit with room for the browser and voice steps.
- Browser: $0.002 a minute from the wallet, billed by the second; at most 5 sessions at once per account (Swatchfin makes at most 2 guides at once). The three guides above used 17–33 seconds of browser time each: **$0.0006–$0.0011 a guide**, about a tenth of a cent, or roughly 1,000 guides per dollar. `USE_BROWSER=false` in `.env` leaves the browser out (for example while developing).

- Claude (not TinyFish): one call per guide, about $0.02–0.03 with `claude-sonnet-5-5` and about twice that with `claude-opus-5-5`. Step 6 gets at most 60 seconds of a guide's 150.

Docs: [Search](https://docs.tinyfish.ai/search-api) · [Fetch](https://docs.tinyfish.ai/fetch-api) · [Browser](https://docs.tinyfish.ai/browser-api)
