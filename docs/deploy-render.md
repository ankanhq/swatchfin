# Deploy Swatchfin on Render (free plan)

Swatchfin runs as **one web service**: the same Python app serves the API and the website. This guide puts it on [Render](https://render.com)'s free plan, using the `render.yaml` file in the repository root (a "Blueprint": a file that tells Render how to build and run the app, so you don't have to type the settings yourself).

At the end you have a public address like `https://swatchfin.onrender.com`, with your API keys stored only in Render's settings.

## Before you start

You need:

- A GitHub account with access to the `swatchfin` repository.
- Your four API keys, ready to paste: **TinyFish** ([agent.tinyfish.ai](https://agent.tinyfish.ai/api-keys)), **Anthropic** ([console.anthropic.com](https://console.anthropic.com)), **Google Gemini** ([aistudio.google.com](https://aistudio.google.com/apikey)) and **Groq** ([console.groq.com](https://console.groq.com/keys)).

Keys go **only** into Render's website. Never into `render.yaml`, a commit, an issue or a chat.

**Set a spend limit at Anthropic first.** In the Anthropic Console, open *Settings → Limits* and set a monthly spend limit (Swatchfin's is $5). It is a hard cap that no bug in Swatchfin can get around. At about $0.03 a guide, $5 covers roughly 160 guides written by Claude in a month. When the limit is reached, Claude refuses, and Swatchfin moves on to Gemini, then Groq, whose free tiers cost nothing. Guides keep working.

## 1. Create a Render account

1. Go to [dashboard.render.com](https://dashboard.render.com) and sign up with **GitHub**. Signing up this way connects the two, so Render can read the repository.
2. When GitHub asks which repositories Render may see, choose **Only select repositories** and pick `swatchfin`. Render needs nothing else.

The free plan doesn't need a credit card.

## 2. Create the service from the Blueprint

1. In the Render dashboard, click **New** (top right), then **Blueprint**.
2. Choose the `swatchfin` repository and click **Connect**.
3. Render reads `render.yaml` and shows what it will create: one **web service** called `swatchfin`, on the **Free** plan. Give the Blueprint a name if it asks (for example `swatchfin`).

## 3. Paste the four keys

On the same page, Render lists the settings marked `sync: false` in `render.yaml` and asks for their values:

| Setting | Paste |
|---|---|
| `TINYFISH_API_KEY` | your TinyFish key |
| `ANTHROPIC_API_KEY` | your Anthropic key |
| `GEMINI_API_KEY` | your Gemini key |
| `GROQ_API_KEY` | your Groq key |

Paste each one, then click the button at the bottom to create everything (Render calls it **Deploy Blueprint** or **Apply**). Spaces, tabs, line breaks and quote marks that come along with a paste are taken out when Swatchfin reads a key, so they can't break it.

Render asks for these values **only this once**. If you skip one, add it later under the service's **Environment** tab (see "Change a key" below).

The other settings (Python version, the daily limits, `PROXY_HOPS`) come from `render.yaml` and need nothing from you.

## 4. Wait for the first deploy

Render now installs the Python packages and starts the app. It takes about 3 to 5 minutes. Open the `swatchfin` service and its **Logs** tab to watch. When it is ready, the log shows lines like:

```
INFO swatchfin: tone of voice: claude-sonnet-5-5, then gemini-3.8-flash, then openai/gpt-oss-120b
INFO swatchfin: guides made today: 4 of 50
INFO:     Application startup complete.
```

- **"tone of voice: …"** lists the language models that have a key. One missing means its key wasn't pasted.
- **"guides made today: N of 50"** means the TinyFish key works: Swatchfin asked TinyFish how many guides were already made today.
- A warning that `TINYFISH_API_KEY is not set` means that key is missing. Add it under **Environment**.

The service page shows **Live** in green when the deploy has worked.

## 5. Open the site

The address is at the top of the service page: `https://swatchfin.onrender.com` (if that name was taken, Render adds a few letters, for example `swatchfin-x1y2.onrender.com`).

- Open it and try one of the example chips on the start page.
- `https://<your address>/api/v1/health` should answer `{"status":"ok"}`.

Send the address to Claude Code: it goes into the README, the About page's social preview tags and the demo script.

## 6. Check the visitor address

Behind Render, every request reaches Swatchfin through Render's proxies. They write the visitor's real address in a header called `X-Forwarded-For`, but they also keep any address a visitor makes up and sends in the same header. Swatchfin therefore reads the entry the proxies add for the visitor, counting from the end of the list. `PROXY_HOPS` says how many entries from the end to go.

**Checked on 12 October 2026:** an ordinary request (one that sent no header of its own) arrived with 3 entries, so Render's proxies add 3 and the visitor is the first of them. `render.yaml` sets `PROXY_HOPS` to `3`. (With the first setting, `1`, Swatchfin read the last proxy's address instead, so every visitor shared one limit of 5 guides a day.)

To check it again after a deploy, open the site once, then have Claude Code send one request with a made-up first entry. In **Logs**, find the lines that start with `X-Forwarded-For had`:

```
INFO swatchfin.ratelimit: X-Forwarded-For had 3 entries; the visitor is entry 1 (PROXY_HOPS=3)
INFO swatchfin.ratelimit: X-Forwarded-For had 4 entries; the visitor is entry 2 (PROXY_HOPS=3)
```

The first is your ordinary visit: the visitor is entry 1. The second is the request with the made-up entry: the visitor is entry 2, so the made-up entry 1 was ignored. The lines show how many entries there were, never the addresses. If the numbers differ, copy the lines back: `PROXY_HOPS` changes in `render.yaml`, and the next deploy picks it up. A `WARNING` line means a request had fewer entries than `PROXY_HOPS`, so the setting is too high.

Each number of entries is written once each time the server starts, so check right after a deploy.

## Living with the free plan

| What happens | When | What Swatchfin forgets |
|---|---|---|
| **The server sleeps** | after 15 minutes with no visitors. The next visitor waits about a minute while it wakes | saved guides, copied SVG logos, the 24-hour reuse list, each visitor's count |
| **A deploy** | every push to `main` (and when you click **Manual Deploy**) | the same |
| **Render restarts it** | Render may do this at any time on the free plan | the same |

What it **doesn't** forget: the daily limit for everyone. When the server starts, it asks TinyFish how many guides were made today (each one opens one TinyFish Browser session) and counts on from there. Guides you make on your own computer count too, because they use the same key and the same credit.

A forgotten guide's link shows "Guide not found" with a **Make this guide again** button. So the README and the About page link to the home page, never to a single guide.

Other things to know:

- **Free hours.** Render gives each account 750 free instance hours a month. One service that never slept would use about 744, and a sleeping service uses none, so Swatchfin fits.
- **A guide in progress isn't cut off by sleep.** Its page asks for progress every 1.5 seconds, which counts as a visit. A push to `main` in the middle of one does stop it.
- **Before recording a demo**, open the site and wait for it to wake, so the video doesn't start with a one-minute wait.

## Change a key or a setting

1. Open the `swatchfin` service, then the **Environment** tab.
2. Edit the value and save. Render asks whether to deploy now. Choose to save and deploy, so the app restarts with the new value.

The limits and `PROXY_HOPS` are set in `render.yaml`. Change them there and push: Render applies the file again and deploys. An edit to them under **Environment** can be replaced the next time the file is applied, so keep the file as the one place they are set. The four keys are the exception: they are only ever set under **Environment**.

## Stop or pause it

Under the service's **Settings**, **Suspend Service** stops it (the address then shows an error) and **Resume Service** starts it again. Deleting the service removes it and its address for good.

## If something goes wrong

- **The build fails.** Open the failed deploy's log. Every package is pinned and has a ready-made Linux build for Python 3.13 (checked in Phase 10), so a failure usually means a typo in a changed `render.yaml`.
- **Every guide stops with "Swatchfin can't read websites right now".** The TinyFish key is missing or wrong. Fix it under **Environment**.
- **Guides have no tone of voice**, and their warning gives each model's reason: no language model key worked. Check the three keys, and the Anthropic spend limit.
- **"Swatchfin has reached today's limit".** 50 new guides were made today (UTC). Sites with a guide from the last 24 hours still open; new ones work again after midnight UTC.
