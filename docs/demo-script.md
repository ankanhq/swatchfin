# Demo video script

A screen recording of about three minutes for the TinyFish Student Bounty Drop 001 submission. It shows Swatchfin on four brands, from a URL and from a name, and where each TinyFish API does its work.

The bounty asks to see five things. Each is shown here:

| The bounty asks for | Where in the video |
|---|---|
| Works from a URL **or** a company name | Notion and Stripe from a URL (scenes 2 and 4), Duolingo from its name (scene 6) |
| Fetch does the core extraction | The progress steps (scene 2) and the Sources list (scene 5) |
| Accurate to the live site | Notion's logo, Stripe's colours and Patagonia's quotes, each next to its source |
| Structured, reusable output | The Export menu and the JSON (scene 7) |
| At least three different brands | Notion, Stripe, Patagonia and Duolingo |

## Before you record

1. **Wake the server.** Open <https://swatchfin.onrender.com> and wait until the start page shows. After 15 minutes without visitors the free server sleeps, and the first visit takes about a minute.
2. **Make three guides in advance**: open the start page, click the example chips **stripe.com** and **https://www.patagonia.com**, then type **Duolingo** and click Generate. Wait for each guide to finish. When you open them again during the recording, they open at once: a guide made in the last 24 hours is reused.
3. **Don't push to GitHub until you have finished.** A push makes Render deploy, and a deploy forgets every guide.
4. **Mind the limits.** Each visitor can start 15 new guides in any 24 hours. This demo starts 4 (Notion, Stripe, Patagonia, Duolingo); reopening one of them doesn't count.
5. **Set up the screen:** a browser window of about 1440 × 900, zoom at 100%, the light theme, one tab, bookmarks bar hidden, notifications off.

Notion is the one guide made live, so the video shows the progress steps. If it opens at once, it was made in the last 24 hours and reused: make the live one with another site instead, such as linear.app.

## Scenes

The times are a guide. Speed up the wait in scene 2 when editing (the steps take about a minute).

### 1. What it is (0:00–0:15)

**Show:** the start page.

**Say:** "This is Swatchfin. Give it a company name or a website, and it reads the live site with TinyFish and gives back a brand guide: logo, colours, fonts, tone of voice and key messages, each traced back to its source."

### 2. Making a guide, live (0:15–0:50)

**Do:** type `notion.so` and click **Generate**. Let the progress list run.

**Say, as the steps tick:** "A URL, so there's nothing to search for. TinyFish Fetch reads Notion's homepage twice at once: its header, navigation and logo word for word, and its text. Then Swatchfin picks the pages worth reading, About, Careers, Pricing, with the homepage's links and TinyFish Search, and Fetch reads them all in one batch. TinyFish Browser opens the homepage in a real browser and measures the colours and fonts the browser actually draws. Then a language model drafts the tone of voice from that text, and every quote it uses is checked word for word."

### 3. The Notion guide (0:50–1:15)

**Show:** the top of the guide, then the Logo section.

**Say:** "Notion's logo is drawn with code in the page, and it takes its colours from Notion's own stylesheet. So Swatchfin copies it in the colours the browser really drew it in, then draws the copy once more to check it shows a logo, and not a blank square. Here it is on light and dark backgrounds, with the other versions it found and how sure it is of each."

**Do:** scroll to **Typography**. "The fonts are the ones the page really loaded, shown in a live specimen."

### 4. Stripe: colours (1:15–1:45)

**Do:** go back to the start page and click the **stripe.com** chip. It opens at once.

**Show:** the **Colour palette**. Click a hex code: the "Copied" message appears.

**Say:** "Every colour has a role, primary, background, text, and says where the site uses it: button background, link text. They come from the computed styles of real elements, not from a screenshot." Scroll to **Contrast**: "And every text and background pair is graded for WCAG contrast."

### 5. Patagonia: tone of voice (1:45–2:15)

**Do:** open the **https://www.patagonia.com** chip.

**Show:** **Tone of voice**. Open a trait to show its quotes.

**Say:** "The tone of voice is drafted by Claude from the text TinyFish read, and every claim needs a quote. Each quote was found word for word on the site, and links to the page it's on. Anything that couldn't be found was dropped, and the guide says so." Scroll to **Sources**: "Every page read is listed, with the TinyFish API that read it: Fetch, Search or Browser."

### 6. Duolingo, from its name (2:15–2:35)

**Do:** go back to the start page, type `Duolingo`, click **Generate**. It opens at once.

**Say:** "From just a name, TinyFish Search finds the official site. Duolingo's homepage is built with JavaScript, so Fetch gets almost nothing; the browser draws it, and the guide still has its logo, colours and text." Point at the Duolingo wordmark in the guide's header.

### 7. Output for other tools (2:35–2:55)

**Do:** open the **Export** menu.

**Say:** "Every guide downloads as JSON with a fixed schema, CSS custom properties, a Tailwind theme, W3C Design Tokens, and a prompt that tells an AI to write in the brand's voice. Or print it as a PDF." Click **JSON** and show the downloaded file for a moment.

### 8. How TinyFish is used (2:55–3:10)

**Do:** open **About** from the top menu and scroll to the TinyFish section.

**Say:** "Three TinyFish APIs, each with its own job: Search finds the site and pages its homepage doesn't link to, Fetch does the core reading, and Browser measures what only a real browser can see. The code is open source on GitHub. Swatchfin: brand guides from any URL, powered by TinyFish."

## After recording

- Upload the video and send Claude Code its link: it goes into the README.
- The submission needs the live link (<https://swatchfin.onrender.com>), the GitHub repo (<https://github.com/ankanhq/swatchfin>), the video, a LinkedIn post tagging TinyFish, and a post in #showcase on the TinyFish Discord.
