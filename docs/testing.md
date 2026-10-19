# How Swatchfin was tested

The README has the short version. This page has the full numbers: the tone of voice benchmark, and what testing on live sites found and fixed.

## Tone of voice benchmark

`tools/benchmark_voice.py` reads each site once with TinyFish and sends the same request to every model (90 seconds each, twice, a minute apart). Then it runs step 7's word-for-word check on each answer. Run it with:

```bash
python tools/benchmark_voice.py stripe.com patagonia.com duolingo.com --rounds 2
```

Results from 12 October 2026, both rounds together:

| Site | Model | Answered | Time | Quotes found word for word | Traits kept | Tagline | Mission | Value props kept | Cost per call |
|---|---|---|---|---|---|---|---|---|---|
| stripe.com (7 pages) | Claude | 2 of 2 | 8.5–9.3 s | 24 of 24 | 8 of 8 | “Financial infrastructure to grow your revenue.” | “Our mission is to increase economic growth.” | 8 of 8 | $0.032 |
| | Groq | 2 of 2 | 4.0–4.4 s | 17 of 24 | 7 of 8 | the page title, “Stripe \| Financial Infrastructure to Grow Your Revenue” | a description of the company, not its mission | 4 of 8 | free ($0.002 paid) |
| | Gemini | 1 of 2 (busy) | 10.1 s | 14 of 14 | 4 of 4 | “Financial infrastructure to grow your revenue.” | “Our mission is to increase economic growth.” | 4 of 4 | free ($0.009 paid) |
| patagonia.com (8 pages) | Claude | 2 of 2 | 8.3–8.5 s | 23 of 23 | 8 of 8 | “MADE FOR THE MOMENT. BUILT FOR A LIFETIME.” | none found | 8 of 8 | $0.024 |
| | Groq | 2 of 2 | 3.2–3.3 s | 23 of 26 | 8 of 8 | the page title, “Patagonia Outdoor Clothing & Gear” | none found | 8 of 8 | free ($0.001 paid) |
| | Gemini | 1 of 2 (busy) | 8.8 s | 14 of 14 | 4 of 4 | “MADE FOR THE MOMENT. BUILT FOR A LIFETIME.” | “Protect our home planet.” | 4 of 4 | free ($0.007 paid) |
| duolingo.com (5 pages) | Claude | 2 of 2 | 7.9–8.5 s | 21 of 21 | 8 of 8 | “Learn a language for free” | “Develop the best education in the world and make it universally available.” | 6 of 6 | $0.023 |
| | Groq | 2 of 2 | 3.5–4.0 s | 18 of 28 | 7 of 8 | “free. fun. effective.” | the same as Claude's | 4 of 8 | free ($0.001 paid) |
| | Gemini | 2 of 2 | 12.9–17.5 s | 21 of 21 | 6 of 6 | “The most fun way to learn languages, chess, and more!” | the same as Claude's | 8 of 8 | free ($0.006 paid) |

What the numbers say:

- **Claude** answered every time, every one of its 68 quotes was found, and both rounds gave the same tagline and mission. It took about 8.5 s and cost $0.023 to $0.032 a guide.
- **Gemini** was just as accurate when it answered (49 of 49 quotes, and the right taglines and missions), and it costs nothing on the free tier. But `gemini-3.8-flash` answered "high demand" (HTTP 503) to 2 of its 6 calls. It says so within 2 to 4 seconds, so trying it costs the chain little time.
- **Groq** always answered and was the fastest (3 to 4 s), but 20 of its 78 quotes weren't on the pages word for word. It joined two passages with "…", changed a word ("Accept payments anywhere" where the page says "Take payments anywhere"), or wrote non-breaking hyphens the site doesn't use. Step 7 dropped all of them, so its guides stay accurate but thinner (4 of 8 value propositions for Stripe and Duolingo). It also picked page titles as taglines, and a description of Stripe as its mission.

So the default order is Claude, then Gemini, then Groq (`LLM_ORDER=anthropic,gemini,groq`). Claude stays first because it was the only model that always answered and always quoted exactly. Gemini comes next because it matched Claude's accuracy, and when it is busy it fails fast. Groq is the best last resort: it is the most likely to answer, and the check keeps what it gets wrong out of the guide. The benchmark itself always asks every model, whatever the order.

Token counts depend on each model's tokenizer. The same Stripe text was 10,670 input tokens for Claude, 6,156 for Groq and 5,921 for Gemini. On 10 October, `claude-opus-5-5` read Duolingo's text for $0.046 (12 s), and all 12 of its quotes were found.

## Tested on 13 live sites

On 12 October 2026 Swatchfin made guides for 13 sites: notion.so, airbnb.com, spotify.com, zomato.com, nike.com, mailchimp.com, linear.app, figma.com, lego.com, tata.com, ikea.com/de, champaca.in and patagonia.com. Each guide was checked by hand against the live page (logo, button colours, fonts, tagline, quotes and warnings), then checked again after the fixes. The final colours, fonts and taglines are in the README's table.

Every logo was the brand's own, and 134 of 136 quotes were found word for word. The other two were dropped, with a warning.

Problems found and fixed along the way:

- Homepages built with JavaScript were measured before they had finished drawing (Spotify).
- Buttons painted by an element inside them were missed (Airbnb, IKEA, Spotify).
- Colours hidden under album covers and photos were counted.
- Black-and-white brands had no primary colour (Nike, Figma).
- Near-black text was listed as "muted" text.
- A rarely used colour on the logo, a real button or a big first-screen block was left out. It is now listed with confidence 0.5 and a usage note.
- A photo labelled "Zomato logo" was taken as the logo.
- One odd element or a slow page could cost a guide all its colours (Tata, Mailchimp).
- Taglines that are only in the page title were missed (Nike, Tata).
- Promotions were taken as taglines.
- Template galleries and customer stories were read as the brand's own pages.
- Names like "Nike.com" and "Official LEGO® Shop" weren't cleaned up.

### After the deploy: Notion

On the live site, Notion's logo came out as a blank white square, and its first "other version" was a checkmark.

- Notion paints the dark parts of its logo with a CSS variable from its own stylesheet, and the copy lost it.
- The checkmark sat in a language-menu link to `/en-US`, which looked like a link home.

The fixes:

- Logos drawn with SVG code are now copied in the colours the browser really draws them in.
- Every copy is drawn in a blank browser tab, and left out if it comes out blank or as one plain shape.
- Simple icons and language-menu links are never taken as logos.
- The site's icon is the logo of last resort.

This was checked again on notion.so, stripe.com and patagonia.com (full guides), and on nike.com, figma.com, airbnb.com, linear.app, spotify.com, mailchimp.com and lego.com (the logo steps). Every logo is the brand's own, in its real colours. For example, Stripe's wordmark is now `#061B31`, the colour it is drawn in, where the copy used to fall back to `#031323`.

### Then amazon.in

Amazon's logo is one part of a CSS "sprite" picture, so there was no image or SVG to find. The logo chosen was a homepage card labelled only "Logo". Its primary colour was the red of its deal badges, used on under 1% of the page.

The fixes:

- Logos drawn with a CSS background are now photographed in the browser, as a see-through PNG that Swatchfin serves.
- Image files go through the same blank-or-plain check as SVG copies.
- Promotions and other companies' logos are never the logo.
- A sale or deal badge's colour is never the primary or the link colour. Without coloured buttons, the logo's own colour leads.

This was checked again on amazon.in (its photographed logo, and primary `#FC9B18`, the orange of its logo), notion.so (`#0075DE`), stripe.com (`#533AFD`), patagonia.com (black) and flipkart.com (`#2A55E5` from its buttons). Flipkart's header logo is two images the page doesn't label or link at all, so its guide shows Flipkart's app icon and says so.

### Still true

These are also listed on the About page:

- A colour the homepage shows only in a heading, or not at all, isn't listed. Patagonia's orange `#FA4616` is in one campaign heading today, and Zomato's red isn't on its homepage.
- A web-app homepage like Spotify's changes between visits.
- A short name can match the wrong site: "Tata" finds tata.cars, so type "Tata group" or the address.

### What testing cost

The 34 test guides cost $0.96 with Claude (288,810 input and 38,271 output tokens with `claude-sonnet-5-5`, about $0.03 a guide) and $0.046 of TinyFish wallet credit (51 Browser sessions, 24 minutes, including one-off checks). Search and Fetch cost nothing.
