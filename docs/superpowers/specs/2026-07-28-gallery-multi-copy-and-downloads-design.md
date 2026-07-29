# Gallery: multi-copy support, theming, and downloadable content

**Date:** 2026-07-28
**Status:** implemented. Sections 1–3 shipped 2026-07-28; Section 4 (downloads
and snippets) shipped 2026-07-29.

## Goal

Two things at once:

1. Make the app **copyable**. The owner hands a folder to another person, who runs it
   against their own bot with their own language, colours, fonts, and content. No code
   editing, no updates flowing between copies afterwards.
2. Add **downloadable assets and live code snippets** to the owner's copy.

Everything that differs between copies is set in the admin panel. There is one codebase.

## Background

The app is a Flask + SQLite Telegram Mini App (`app.py`, `database.py`, two templates).
Media lives in `static/media/`, settings in a `settings` key/value table. A background
thread long-polls Telegram `getUpdates` to complete Stars payments.

Copies do not sync. The recipient gets a frozen snapshot. Because more copies may follow,
per-copy differences are configuration rather than edited code — hand-editing each copy
does not scale and cannot be undone once copies diverge.

---

## Section 1: Per-copy configuration lives in admin

Creating a copy becomes:

1. Copy the folder.
2. Edit `.env` — `BOT_TOKEN`, `ADMIN_PASSWORD`, `SECRET_KEY`.
3. Run it, open `/admin`, set everything else.

A new **Appearance** tab writes to the existing `settings` table:

| Setting | Control | Effect |
|---|---|---|
| `language` | dropdown EN / RU | selects `lang/en.json` or `lang/ru.json`, for app **and** admin |
| `accent_color` | colour picker | overrides `--green` |
| `bg_page`, `bg_base`, `bg_raised` | colour pickers | surface colours |
| `font_display` | file upload | replaces `--font-display` |
| `font_mono` | file upload | replaces `--font-mono` |
| `cell_radius` | slider 0–12px | `--cell-radius` |
| `stars_mode` | off / all / checked only | see Section 2 |
| `downloads_enabled` | on / off | gates Section 4 entirely |

**Mechanism.** These are already CSS custom properties in `:root`. The server injects saved
values as an inline `<style>` override at page render. No CSS files are edited and there is
no build step — change a colour in admin, reload, done.

**Language.** Two static JSON files hold ~200 strings (≈60 app, ≈140 admin). The admin
dropdown only chooses which file loads. English is the default. Admin-switchable was chosen
over fixed-per-copy so that making a copy never requires touching code.

### Self-hosted fonts and icons (required)

The app currently loads from two external hosts:

- `fonts.googleapis.com` — Space Grotesk, Share Tech Mono (`index.html:12–14`)
- `cdn.jsdelivr.net/.../@tabler/icons-webfont@latest` (`index.html:1152`, `admin.html:7`)

Both are unreliable or blocked from Russia. Since every control in the app and admin is a
Tabler icon, the Russian copy would open with no icons. The `@latest` tag is also unpinned
and can change without warning.

Both must be vendored into `static/`. Owner fonts (`C:\GEROINZO\fonts\`) convert from `.ttf`
to `.woff2`, shipping 2–3 weights rather than all 8. The `@font-face` blocks at
`index.html:25–51` are currently commented-out `YOUR_DISPLAY_FONT` placeholders and become
real, pointing at whatever admin uploaded.

> **Licence note.** The recipient's font files are named "TT Travels Next Trial". Trial
> licences normally forbid production use. This is the recipient's exposure, not the
> owner's, but should be resolved before their copy is public.

---

## Section 2: Stars button control

Global `stars_mode` setting, three values:

| Mode | Wall images | Posts |
|---|---|---|
| `off` | no donation button | no donation button |
| `all` (current behaviour) | shown | shown on every post |
| `checked` | shown only where ticked | shown only where ticked |

Per-item opt-in adds `show_stars INTEGER NOT NULL DEFAULT 0` to **both** `posts` and
`media`, surfaced as a checkbox in each editor. It applies only in `checked` mode.

### Donation and Unlock are separate

They are currently the same element — `index.html:1594` relabels the button `Unlock · N★`
when an item is locked. Left as-is, setting `stars_mode: off` would make every locked wall
image **permanently unviewable**, with no way for anyone to pay to unlock it.

Therefore:

- **Donation** ("Send Stars", voluntary) obeys `stars_mode` and can be hidden.
- **Unlock** (required to view locked content) is **always shown when an item is locked**,
  regardless of `stars_mode`.

`off` means "stop asking for money", never "break my locked content".

### Migration

`database.py:117–122` establishes the pattern: read `PRAGMA table_info`, then
`ALTER TABLE … ADD COLUMN … NOT NULL DEFAULT …`. All new columns in this spec follow it and
are safe to apply to the live database.

---

## Section 3: De-branding and layout fixes

### De-branding

"Geroinzo" appears in 35 places across 8 files, in three distinct roles:

| Role | Where | Becomes |
|---|---|---|
| Visible brand | logo text, About, invoice titles | reads the existing `logo_text` setting |
| CSS font family names | `'GeroinzoDisplay'`, `'GeroinzoMono'`, `'GeroinzoStamp'` | `'AppDisplay'`, `'AppMono'`, `'AppStamp'` |
| Docs and scripts | `README.md`, `share.bat`, `restart.ps1`, `seed_demo.py` | generic wording |

The directory stays `geroinzo-gallery`. Renaming breaks the tunnel scripts and gains
nothing — the recipient only ever sees what renders in the app.

### Fixes

1. **Post image cap removed.** `app.py:302` truncates a post's images to 15 with `[:15]`,
   silently discarding the rest. The endpoint also splits `images` and `videos` into two
   arrays that the client immediately re-merges (`index.html:2057`); collapse to one list.
2. **Rounded corners.** `--cell-radius` moves from hardcoded `0` to the admin slider.
3. **Load-time size jump.** Every cell starts at `grid-row-end: span 20` (~160px) and snaps
   to its real height once the image loads (`index.html:335`). Store each image's width and
   height at upload and emit `aspect-ratio`, so cells are correctly sized before the image
   arrives.
4. **Placeholder height.** `relayoutCell` measures a placeholder's grid-forced height and
   recomputes the same span from it — self-referential. Give placeholders a fixed span.
5. **Dead code removed.** `.morph-gallery`, `.morph-item`, `.post-reader-gallery`,
   `.cell-ghost`, and the `#expGhost` "WHO NEEDS" watermark.

### Already done (commit `76c6bed`)

The `.scan` scanline overlay is removed. It painted a repeating 4px gradient (1px of 18%
black) over every thumbnail. On 2× screens the stripes landed on whole device pixels for a
uniform ~4.5% darkening; on 3× screens (iPhone Pro/Max) the 3px/4px stops fell between
device pixels, so Safari resampled the gradient — the lines smeared and moiréd against the
photo. That is why images looked dark on some iPhone models and not others. It had already
been disabled in the fullscreen viewer for the same reason; this extended that to the
thumbnails.

---

## Section 4: Downloads and snippets (owner's copy)

Gated behind `downloads_enabled`. Off in the recipient's copy — a setting, not a code fork,
so it stays available for any future copy.

### Access modes

Adds `access_mode TEXT NOT NULL DEFAULT 'free_donate'` and
`price_stars INTEGER NOT NULL DEFAULT 0` to `posts`.

| Mode | Visitor sees | Card |
|---|---|---|
| `free` | `↓ Download`, works immediately | normal |
| `free_donate` (default) | `↓ Download` works immediately; a quiet "support this" text link beside it | normal |
| `paid` | `↓ 25★ to download`; unlocks permanently for that user after payment | **distinct colour** |

The donation link is deliberately understated — a text link, not a button competing with
the download. Downloading never waits on it.

**Paid card styling.** A `.post-card.is-paid` class with its own token (`--paid-accent`,
defaulting to amber) rather than reusing `--accent`. The accent colour is admin-configurable
and could be set to anything, including a colour that makes paid cards indistinguishable
from normal ones; a separate token keeps "this one costs money" readable at any accent
setting. The card shows a price badge in the same colour.

### Two invoice paths, different trust levels

The donor chooses their own amount, from 1 up. That makes the two payment flows
fundamentally different and they must not share an endpoint:

- **Donation** — amount comes from the visitor. Server validates it is an integer ≥ 1 and
  within Telegram's per-invoice maximum for `XTR` (confirm the current figure against the
  Bot API docs at implementation time; reject rather than clamp). Then bills it.
- **Paid download** — amount comes **only from `posts.price_stars`**, never from the
  request body. A client-supplied price lets anyone edit a 500★ asset down to 1★.

Kept as two endpoints so the distinction cannot be lost in later edits.

### Snippet posts

Not a new content type — an existing post with optional `snippet_html`, `snippet_css`,
`snippet_js` columns. If any is non-empty, the reader renders a live preview above the body:

```html
<iframe sandbox="allow-scripts" srcdoc="…"></iframe>
```

`allow-scripts` **without** `allow-same-origin`: the snippet runs normally but cannot reach
the parent page, the admin session, or cookies. The code is owner-authored and trusted, but
the sandbox costs nothing and contains anything pasted in from elsewhere later.

**No source is displayed on the page.** Getting the code requires downloading.

### The ZIP

Generated on demand from data already in the post — nothing extra to maintain or upload:

The filename derives from the post title, lowercased and stripped to `[a-z0-9-]`, falling
back to `post-<id>` when the title is empty or non-Latin (Russian titles included).

```
<post-slug>.zip
├── index.html      ← runnable standalone
├── style.css
├── script.js
└── assets/         ← every image/video attached to the post
```

For `paid` posts the server verifies the unlock **before** building the archive. Media keeps
its existing random-suffix filenames, so direct URLs cannot be guessed or passed around to
bypass payment.

### Transparent WebM

Alpha video renders as a black box against most backgrounds. Adds a per-post preview
background — dark / light / checkerboard — so no-background assets read as transparent
instead of broken.

---

## Out of scope

- **`initData` is never validated.** The Telegram user id arrives as a plain query
  parameter (`/api/media?uid=…`) and is not verified against Telegram's HMAC. Any id can be
  claimed: likes and stats can be forged, and a locked item is viewable by anyone who names
  a uid that already paid. Contained (~20 lines: verify `initData` against `BOT_TOKEN`,
  derive the uid from it) but separate work. It matters more once a second person's copy is
  public — and more again once paid downloads exist, since unlocks are keyed on that same
  spoofable uid.
- **`/admin/login` has no rate limiting** — brute-forceable on a public host.
- **Hosting.** Undecided, and blocks none of the above.

## Open question: hosting

Cloudflare Workers cannot run this app as written: Flask is WSGI with a background thread,
`database.py` is synchronous `sqlite3`, uploads need a filesystem, and the Stars poller is a
long-running `getUpdates` loop. Porting means rewriting `app.py` and `database.py` against
D1 and R2, and converting the poller to a `setWebhook` endpoint. That last change is a real
improvement — it removes the "only one instance may ever run" constraint — but the whole is
a rewrite, not a deploy.

Two viable paths:

1. **VPS (UpCloud) + R2 for media.** No rewrite. Needs: a domain for HTTPS, `gunicorn -w 1`
   (more than one worker means duplicate pollers and Telegram 409s), and a startup hook or
   separate systemd unit — `start_poller()` only runs under `if __name__ == "__main__"`, so
   gunicorn would silently never start it. Also `client_max_body_size 64m` in nginx to match
   `MAX_UPLOAD_MB`.
2. **Full Cloudflare port.** Larger effort, better long-run operational story.

Cloudflare ships quickly and this analysis predates verification; confirm the current state
of Python Workers and Containers before committing to path 2.

## Build order

1. Vendor fonts and icons; wire up real `@font-face`. *(Unblocks the Russian copy.)*
2. Extract strings to `lang/en.json`; add the language setting; translate to `ru.json`.
3. Appearance tab: colours, fonts, radius. De-brand in the same pass.
4. Layout fixes: image cap, `aspect-ratio` sizing, placeholders, dead code.
5. Stars modes and the donation/unlock split.
6. Downloads and snippets.

Steps 1–5 are the shared base and must be finished before the recipient's copy is handed
over. Step 6 is owner-only and can follow at any time.
