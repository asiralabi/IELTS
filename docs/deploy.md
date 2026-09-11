# Deploying the app

Three containers behind one address: the FastAPI backend, the Next.js frontend,
and a Caddy proxy in front of both. The proxy is not decoration — it is what
makes the app reachable from a phone, a friend's laptop or a real domain
without rebuilding anything, because the browser then loads the page and calls
the API from the *same* origin.

```
                  :8080
  browser  ──►  Caddy  ──┬── /api/*    ──►  backend:8000   (prefix stripped)
                         ├── /assets/* ──►  backend:8000
                         └── everything ──►  frontend:3000
```

## What ships and what does not

**The image carries code only.** Everything the app reads or writes at runtime
is on a mounted volume:

| path | what it is |
|---|---|
| `data/ielts.db` | accounts, attempts, band history, the parsed Cambridge tests |
| `data/qdrant` | the knowledge base every generation is grounded on |
| `data/assets` | figure images served at `/assets` |
| `data/figure_knowledge` | figure conventions read while drawing |
| `data/tts_cache` | synthesised listening audio, regenerated on demand |

The last row is only durable storage because this volume is. On a platform
with no disk it is not, and `BLOB_READ_WRITE_TOKEN` is what replaces it — see
**Where the audio lives** below.

`books/` and `Audios/` are never in the image. They are the copyrighted source
material that grounds generation, and the north star is that a student sees
generated work, never a scanned page.

## Run it here

```bash
python scripts/env_for_docker.py     # derives .env.docker from backend/.env
docker compose up -d --build
```

Then open <http://localhost:8080>.

`env_for_docker.py` copies the provider and key you already run on, forces
`DEBUG=false`, and blanks `GENERATOR_MODEL`/`EVALUATOR_MODEL` — those name
fine-tuned checkpoints served by a local ollama that no container can reach, and
blank falls back to the hosted model. If `JWT_SECRET` is still the placeholder
it generates one, because with `DEBUG=false` the server *refuses to start* on a
secret that ships in git.

Watch it come up:

```bash
docker compose logs -f backend
```

First start is slow on purpose: it seeds the knowledge base, warms the embedding
model, and starts filling the practice pool. `curl localhost:8080/api/health`
answers `{"status":"ok"}` when it is ready.

## Letting someone else try it

### Same wifi

The proxy already listens on every interface, so nothing needs rebuilding —
your friend just needs the address and an open port.

1. Your LAN address is **192.168.0.210** (`ipconfig` if it changes — a laptop
   gets a new one on a different network).
2. Open the port once, in an **administrator** PowerShell:

   ```powershell
   New-NetFirewallRule -DisplayName "IELTS app 8080" -Direction Inbound `
     -Action Allow -Protocol TCP -LocalPort 8080
   ```

3. They open **http://192.168.0.210:8080** and register an account like anyone
   else.

If the page loads for you but not for them, it is the firewall rule or a wifi
network with client isolation (common on guest and campus networks) — try a
phone hotspot both devices join.

### Anywhere else

A tunnel gives a public https URL without a router, a domain or a fixed IP.
Nothing is installed here yet; with [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/):

```bash
cloudflared tunnel --url http://localhost:8080
```

It prints a `https://<random-words>.trycloudflare.com` address that works from
any network. Send that.

Four things worth saying out loud before you do:

* **It is public.** Anyone with the link reaches the login page. Accounts still
  gate what is behind it, but the link is not a secret.
* **It lives as long as the terminal does.** Close it and the URL is dead — a
  quick tunnel gets a new random address every run.
* **It is your machine serving it.** Their generation runs on your CPU, your
  RAM, and your free-tier model quota. Two people generating at once will feel
  it; a spent quota answers *"The examiner is busy right now."*
* **Speaking is the heavy part.** Transcription loads a Whisper model into the
  same container the rest of the app runs in. Measured here on one 20s clip:
  `large-v3` was **OOM-killed at 2.90GB**, `medium.en` took 95s at 2.74GB, and
  `small.en` took 28s at 1.33GB — which is why `small.en` is the default. All
  three transcribed the probe verbatim, but the probe was clean synthetic
  speech; on a real accented recording the larger models earn their size.

## Deploying to a host

The bind mount in `docker-compose.yml` points at this machine's corpus. On
another host, ship the runtime slice instead — 12GB down to about 220MB:

```bash
python scripts/make_data_bundle.py --archive
```

It copies only what `app/` reads while serving and prints what it skipped and
why. Unpack it on the target, point the mount at it, and change one line:

```yaml
volumes:
  - /srv/ielts-data:/app/data      # was ./backend/data
```

Any host that runs containers with a persistent disk works — Fly.io, Render,
Railway, a VPS. What it must have:

* **A disk that survives restarts.** SQLite and Qdrant are files. A platform
  with an ephemeral filesystem loses every account on each deploy.
* **RAM: ~1.4GB with `small.en`, ~2.8GB with `medium.en`, ~4GB for
  `large-v3`.** Measured, not estimated — the Docker VM here allows 3.674GB and
  `large-v3` died inside it (`OOMKilled=true`, exit 137). Whisper sets the
  floor; everything else together idles around 600MB.
* **No request timeout under ~10 minutes.** Generating a full exam is minutes of
  model time, which is why the proxy sets a 30-minute response timeout.
* **One backend replica.** The practice-pool warmer runs a thread per process,
  and a second copy would generate against the same SQLite file.

An empty `data/` volume still boots: `seed_knowledge_base()` falls back to the
markdown seed bundled in `app/rag/seed/`. Generation works, grounded on that
seed instead of the Cambridge corpus.

## Where the audio lives

A Listening recording is ~100 seconds of neural synthesis and 1-3.5MB of MP3,
so it is cached rather than made twice. Under this compose stack the cache is
`data/tts_cache` on the volume and there is nothing else to set up.

Serverless is the case that needs `BLOB_READ_WRITE_TOKEN`, because there the
disk is a lie twice over: an instance gets a fresh `/tmp` and is killed when it
goes idle, and the CI job that warms the practice pool deletes its whole runner
when it finishes. Both were voicing recordings into storage that was about to
be thrown away, so the wait the warm pool exists to remove landed on the
student anyway. Linking a Blob store puts the recording somewhere both can
reach:

```bash
cd backend
vercel blob create-store oratio-audio --access public --yes
```

That sets the variable on the project by itself. Copy the same value into the
`BLOB_READ_WRITE_TOKEN` repository secret so the pool warmer writes to the
store the app reads from — without it the workflow still runs, and still
achieves nothing for the audio.

Two consequences worth knowing before changing any of it:

* **The store is public and the blobs are named by a sha256 of the script.**
  That is what lets `/listening/audio/{id}` answer with a 307 the browser
  follows to the edge — a Vercel function response is capped at 4.5MB and a
  Part 3 recording has measured 3.25MB, so the MP3 could not keep travelling
  through the function. The address is unguessable, but it is not access
  controlled: anyone holding the URL can play the recording.
* **`tools/blob_store_check.py` is the thing to run when audio is slow.** The
  suite mocks the store, so it cannot tell you the wire contract still holds.
  `python tools/blob_store_check.py --env-file .env.local` does a real
  put/head/get and checks the CORS and range headers the player depends on.

## Before real students use it

* **`JWT_SECRET`** — a fresh random value per deployment, never the placeholder.
* **`CORS_ORIGINS`** — behind this proxy the browser makes no cross-origin call
  and the setting is unused. It matters only if the frontend moves to a
  different origin (Vercel, say): name that origin instead of leaving `*`, which
  lets any site on the internet call the API with a logged-in student's token.

  🚨 **A new frontend domain is not just a DNS change.** The Vercel deployment
  pins this to the exact origins it serves, so adding
  `oratio-ielts.vercel.app` without adding it here too gives a site that loads
  and then fails every API call — the preflight answers 400 and the student
  sees a working page that cannot log in. Add the origin, redeploy the API,
  and check a preflight before sharing the link:

  ```bash
  curl -sD - -o /dev/null -X OPTIONS https://YOUR-API/feedback     -H "Origin: https://YOUR-NEW-DOMAIN"     -H "Access-Control-Request-Method: POST" | grep -i access-control-allow-origin
  ```

  Keep the OLD origin in the list too; a link someone already has should not
  stop working the day you rename.
* **HTTPS** — a tunnel supplies it. On your own domain, remove `auto_https off`
  from the `Caddyfile` and replace `:8080` with the hostname; Caddy then gets
  and renews a certificate by itself.
* **Backups** — `data/ielts.db` is every account and every band score anyone has
  earned. Copy it somewhere.
* **`FEEDBACK_ADMIN_TOKEN`** — needed only to READ the pilot feedback box back.
  Leaving the box itself unconfigured is fine: `POST /feedback` is public so a
  tester who never registered can still report a bug. Set the token and the
  inbox opens to whoever holds it:

  ```bash
  curl -s https://YOUR-HOST/api/feedback -H "X-Admin-Token: $FEEDBACK_ADMIN_TOKEN"
  ```

  Left unset, that route answers 403 to everyone — which is the safe default,
  since the rows carry every tester's email address.

## Troubleshooting

| symptom | cause |
|---|---|
| backend exits at boot, `JWT_SECRET is still the placeholder` | working as intended — set it in `.env.docker` |
| every generation 502s, pages fine | `OPENAI_API_KEY` empty or rejected; `docker compose logs backend` shows the upstream status |
| *"The examiner is busy right now"* | free-tier quota spent, or the provider is rate-limiting. Wait |
| figures missing, questions fine | the volume has no `data/assets` — rebuild the bundle |
| answers ignore the Cambridge corpus | `data/qdrant` is missing, so it fell back to the seed KB |
| Speaking returns 502 after minutes, backend restarted | Whisper was OOM-killed. Confirm with `docker inspect ielts-backend-1 --format '{{.State.OOMKilled}} {{.State.ExitCode}}'` — `true 137` is the signature. Drop `WHISPER_MODEL` a size |
