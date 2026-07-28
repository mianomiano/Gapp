# Deploying to Railway with Cloudflare R2

Media goes to R2, the database to a Railway volume, and Telegram gets an HTTPS
URL. Roughly 20 minutes start to finish.

## The one thing that will bite you

**Railway wipes the container filesystem on every redeploy.** Without a volume,
`gallery.db` is recreated empty each time — losing posts, likes, stats, and
every setting. R2 covers uploaded media; it does *not* cover the database.
Step 3 is not optional.

---

## 1. Cloudflare R2

1. Cloudflare dashboard → **R2** → **Create bucket**. Any name; `gallery-media`
   works. Location: Automatic.
2. Open the bucket → **Settings** → **Public access**:
   - Either enable the **r2.dev development URL** (fine to start), giving you
     `https://pub-xxxxxxxx.r2.dev`,
   - or connect a custom domain, which is faster and has no rate limits.

   Copy that URL — it becomes `R2_PUBLIC_URL`.
3. R2 home → **Manage API Tokens** → **Create API token**:
   - Permission: **Object Read & Write**
   - Scope: this bucket only
   - Copy the **Access Key ID** and **Secret Access Key** — the secret is shown
     once and never again.
4. Your **Account ID** is on the R2 overview page, right-hand side.

> Public bucket is deliberate: this app has always served media from public
> URLs under unguessable random filenames, and hides the URL rather than the
> file. Paid downloads, when added, are served through the app so the server
> can check the unlock first.

## 2. Push the code to GitHub

Railway deploys from a repo.

```bash
git checkout master
git merge feat/shared-base          # or deploy the branch directly
gh repo create <name> --private --source=. --push
```

`.env`, `gallery.db`, and `static/media/` are gitignored — secrets and content
stay out of the repo, which is why steps 3 and 4 exist.

## 3. Railway service and volume

1. **New Project** → **Deploy from GitHub repo** → pick it.
2. It builds automatically. `railway.json` pins the start command to
   `python app.py` and one replica.
3. **Add a volume**: service → **Variables** tab → **+ Volume**.
   - Mount path: `/data`
4. **Settings → Networking → Generate Domain.** You get
   `https://<name>.up.railway.app`.

> **One replica only.** The Stars poller uses Telegram long-polling; a second
> instance causes `getUpdates` conflicts and payments break for both. Never
> raise the replica count, and do not set a Telegram webhook on the same bot.

## 4. Environment variables

Railway service → **Variables** → paste:

```
BOT_TOKEN=<from @BotFather>
ADMIN_PASSWORD=<a long one — this is on the public internet now>
SECRET_KEY=<long random string>

DB_PATH=/data/gallery.db

R2_ACCOUNT_ID=<from step 1.4>
R2_ACCESS_KEY_ID=<from step 1.3>
R2_SECRET_ACCESS_KEY=<from step 1.3>
R2_BUCKET=gallery-media
R2_PUBLIC_URL=https://pub-xxxxxxxx.r2.dev
```

Do **not** set `PORT` — Railway provides it.

All five `R2_*` must be present together. Miss one and the app logs
`R2 partially configured` and quietly serves from local disk, which on Railway
means media vanishes on the next deploy.

## 5. Move existing media into the bucket

From your machine, with the same `R2_*` values in your local `.env`:

```bash
python tools/migrate_media_to_r2.py            # dry run, lists files
python tools/migrate_media_to_r2.py --upload
```

It prints a URL at the end — open it. If the image loads, public access is set
up correctly. If it 401s, revisit step 1.2.

Nothing is deleted locally.

## 6. Move the existing database

The volume starts empty. To carry your current content over, upload
`gallery.db` to `/data/gallery.db` — via `railway run` with the CLI, or start
fresh and re-add content through `/admin`.

Starting fresh is often simpler, and is exactly what the second copy does.

## 7. Point Telegram at it

1. @BotFather → `/mybots` → your bot → **Bot Settings** → **Configure Mini App**
2. Paste `https://<name>.up.railway.app`
3. Open the Mini App from your bot.

Then in the app's own `/admin` → Settings → Telegram: set your bot username and
mini app short name, so Share and Copy-link hand out the `t.me/…` address
rather than the Railway URL.

---

## Verifying it worked

| Check | How |
|---|---|
| App is up | open the Railway domain in a browser |
| Media from R2 | a wall image's URL should start with your `R2_PUBLIC_URL` |
| Database persists | change the logo text, redeploy, confirm it survived |
| Poller alive | Railway logs show `[stars] payment poller started.` |
| Storage backend | logs show `[storage] using R2 bucket '<name>'` |
| Real server | logs show `[server] waitress on 0.0.0.0:<port>` |

If the logs say `using local disk`, an `R2_*` variable is missing or misspelled.

## Costs

- **R2**: 10 GB storage free, **zero egress**. Your media is well under it.
- **Railway**: usage-based; a small always-on service is a few dollars a month.
  Volumes are billed separately by size.

Do not let the service sleep. A sleeping app is not polling Telegram, so Stars
payments stall until something wakes it.

## Known constraints

- **One instance, always.** See step 3.
- **SQLite on a volume** is right for this scale. It would need to become
  Postgres only if you ever ran more than one instance — which the poller
  forbids anyway.
- **Uploads are capped at 64 MB** (`MAX_UPLOAD_MB` in `app.py`).
- **Fonts uploaded through the admin panel** land on the container filesystem,
  not R2, so they are lost on redeploy. Either commit them to `static/fonts/`
  in the repo, or mount the volume there too. Set-and-forget, so it rarely
  matters — but it will surprise you once.
