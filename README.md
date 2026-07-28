# Geroinzo — Gallery (Telegram Mini App)

A personal gallery, built as a gift. It runs as a Telegram Mini App: a grunge image/video
wall, likes, and **Telegram Stars** support (donations, plus optional pay-to-unlock content).
Everything — media, social links, logo, and an intro video — is managed from a simple
**admin page**, so you never have to edit code.

---

## Quick start

```bash
git clone <this-repo-url>
cd geroinzo-gallery

cp .env.example .env          # then open .env and fill it in (see below)

pip install -r requirements.txt
python app.py
```

Now open:

- **Gallery:** http://localhost:5000
- **Admin:** http://localhost:5000/admin  (log in with your `ADMIN_PASSWORD`)

The database (`gallery.db`) is created automatically on first run — nothing to install.

> On Windows, use `copy .env.example .env` instead of `cp`.

---

## Demo content vs. handing it over empty

A fresh `git clone` opens **empty** — the database and uploaded media are gitignored, so
nobody inherits anyone else's content. That's what the person you gift it to gets.

For your own **preview / public reveal**, you can fill it with on-brand sample content:

```bash
python seed_demo.py      # adds 6 sample works (incl. a locked one) + About content
python app.py            # open http://localhost:5000 to show it off
```

To clear it back to empty (e.g. before handing over, or to swap in real work):

```bash
python reset.py          # wipes all media, links, and settings — safe to run live
```

So the flow for a gift is: **you** seed + show how it looks → **they** clone and get a clean,
empty gallery to fill with their own work in `/admin`. Each of you uses your own bot token
(see below); nothing of yours is shared.

---

## Filling in `.env`

```
BOT_TOKEN=        # from @BotFather — needed for Stars donations/unlocks
ADMIN_PASSWORD=   # the password you type at /admin (pick anything)
SECRET_KEY=       # any long random string (signs the admin login cookie)
PORT=5000         # optional
```

The gallery and admin panel work locally **without** a `BOT_TOKEN`. The token is only needed
for the "Send Stars" / "Unlock" buttons to actually take payments.

---

## Adding your content (admin panel)

Go to `/admin` and log in. You can:

- **Add media** — upload an image or video, set title/description/date/year, choose a wall size
  (tall / medium / short), and optionally **lock** it behind a minimum number of Stars.
- **Reorder** the wall by dragging items.
- **Social links** — add icons that show in the gallery's *About* tab. Icon names come from
  [tabler.io/icons](https://tabler.io/icons) (e.g. `brand-instagram`, `brand-x`, `brand-youtube`, `mail`).
- **Logo** — set logo text, or upload a logo image.
- **About text** — a short blurb for the About tab.
- **Intro / loading screen** — upload a self-made video (muted, any length). Tick "Use loading
  screen" and it plays once on open, then reveals the gallery. Untick to disable it.

## Custom fonts (optional)

Drop your `.woff2` / `.otf` / `.ttf` files into `static/fonts/`, then open
`templates/index.html` and un-comment the `@font-face` blocks at the top of the `<style>`,
filling in the file names. The design already references them via CSS variables.

---

## Show it online for free (Cloudflare Tunnel)

To put it on the internet with a real HTTPS link (so Telegram can open it and Stars work),
without paying for hosting:

1. Install the tunnel tool once: `winget install --id Cloudflare.cloudflared`
2. **Double-click `share.bat`** (Windows). It starts the app and opens a tunnel, then prints a
   public URL like `https://red-fox-1234.trycloudflare.com`.
3. Paste that URL into @BotFather (see the next section).

It stays online as long as `share.bat` is running. This is separate from ngrok and doesn't use it.
The free URL changes each time you restart — just re-paste the new one in BotFather. (For a URL
that never changes, make a free Cloudflare account + a named tunnel on your own domain.)

> Prefer two manual terminals instead of the .bat?
> Terminal 1: `python app.py`  ·  Terminal 2: `cloudflared tunnel --url http://localhost:5000`

## Running it as a real Telegram Mini App

Telegram needs a public **HTTPS** URL.

1. Create a bot with **@BotFather**, copy its token into `.env` as `BOT_TOKEN`.
2. Expose your local server over HTTPS, e.g. with a tunnel:
   ```bash
   # examples — use whichever you have
   cloudflared tunnel --url http://localhost:5000
   #   or
   ngrok http 5000
   ```
3. In **@BotFather** → *Bot Settings → Configure Mini App* (or `/newapp`), set the Mini App URL
   to your HTTPS tunnel address.
4. Open the Mini App from your bot. Likes, donations, and unlocks now work end-to-end.

### How Stars payments work here

When someone taps **Send Stars** or **Unlock**, the server creates a Telegram Stars invoice
(`createInvoiceLink`, currency `XTR`). To actually **receive** the payment, the app runs a small
background task that talks to Telegram (`getUpdates`) and:

- approves the `pre_checkout_query` (required, or the payment fails), and
- records the `successful_payment` — saving the donation and, for locked items, granting the unlock.

This means **no webhook setup is required** — just keep `python app.py` running.

> Note: this app uses long-polling (`getUpdates`) for payments. Run **one** instance of the bot at
> a time, and don't also set a Telegram webhook on the same bot, or they'll conflict.

---

## Project layout

```
geroinzo-gallery/
├── app.py            # Flask server, JSON API, admin, Stars payment poller
├── database.py       # SQLite schema + queries (auto-created)
├── seed_demo.py      # optional: fill with demo content for a preview
├── reset.py          # wipe back to an empty gallery
├── templates/
│   ├── index.html    # the gallery (design-locked) — wired to the API
│   └── admin.html    # the admin panel
├── static/
│   ├── fonts/        # drop custom fonts here
│   └── media/        # uploaded images/videos + intro video (auto-filled)
├── requirements.txt
├── .env.example
└── README.md
```
