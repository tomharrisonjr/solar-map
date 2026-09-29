# One-command data bootstrap (USPVDB download + load)

- GitHub Issue: #14
- Date: 2026-09-29
- Status: Complete

## Steps

| Status | # | Step |
|--------|---|------|
| ✅ Done | 1 | `load_uspvdb` accepts zip/URL and defaults to the official source |
| ✅ Done | 2 | Taskfile: `data:load` and `setup` |
| ✅ Done | 3 | Getting-started docs + wrap-up |

## Context

`load_uspvdb` currently needs a hand-downloaded, hand-extracted GeoJSON. Real-data check
(2026-09-29): the official zip is `https://eerscmap.usgs.gov/uspvdb/assets/data/uspvdbGeoJSON.zip`
(stable "latest" link, 9.5 MB — not the ~2 MB the page claims) and contains a CHANGELOG, an
XML metadata file, and a **versioned** GeoJSON (`uspvdb_v4_0_20260414.geojson`, 27.9 MB), so a
script must glob for it. The data loaded cleanly in 6.4 s (6,611 rows; no nulls in the columns
we use; idempotent re-run). Committing the data is rejected: ~10 MB per annual release stays in
git history forever and it's upstream, citation-required data. Goal: a new machine needs only
Docker + Task, then `task setup`.

Decision: put download/unzip logic in the Django command (Python `zipfile` + `urllib`, already
used), not `curl`/`unzip` in the Taskfile — no host tools, testable, identical on any OS.

## Step 1 — `load_uspvdb` accepts zip/URL and defaults to the official source (#17)

`backend/facilities/management/commands/load_uspvdb.py`:

- `source` becomes optional (`nargs="?"`, default = official zip URL in a module constant).
- Replace `_load` with: read bytes from path or `http(s)` URL (`urlopen(..., timeout=60)`); if
  it's a zip (`zipfile.is_zipfile`), pick the single `*.geojson` member (glob; `CommandError`
  if none or several), else parse as JSON directly. Keep the existing per-feature `_upsert`.
- Print the required USGS citation after a successful load (text from the USPVDB data page).
- Update `help` (zip now supported, versioned inner filename).

Tests (`facilities/tests.py`, no network): in-memory zip via `zipfile` → `call_command`; zip
with no `.geojson` → `CommandError`; default-source path via
`unittest.mock.patch("...load_uspvdb.urllib.request.urlopen")` returning zip bytes.

**As shipped:**

- Implemented as planned: optional `source` defaulting to `DEFAULT_SOURCE`, bytes-first
  loading (`zipfile.is_zipfile` sniffing, so a zip, a bare `.geojson`, a path or a URL all
  work), single-`.geojson`-member matching, `CommandError` for download/read/parse/zip-layout
  failures, and the USGS citation plus the loaded file name printed after a successful load.
  The printed citation omits the version (it changes each release); the file name carries it.
- **Found by running it live, not by the mocked tests:** USGS answers `403 Forbidden` to
  Python's default `Python-urllib/x.y` User-Agent (curl was fine). The command now sends an
  honest `solar-map/1.0 (+repo URL)` agent; a test asserts it.
- Tests: 7 new (16 total) — versioned zip, no/multiple `.geojson` in zip, default URL +
  User-Agent + timeout via mock, download failure, missing file, non-JSON / non-FeatureCollection.
- Verified: `task check` passes; `manage.py load_uspvdb` with **no arguments** against the
  real USGS URL on a fresh database created 6,611 facilities in 7.6 s.

## Step 2 — Taskfile: `data:load` and `setup` (#19)

`Taskfile.yml`: `data:load` (`task migrate` first, then
`docker compose run --rm web python manage.py load_uspvdb`); `setup` = create `backend/.env`
from `.env.example` if missing, `docker compose build web`, then `data:load`. Reuse the existing
`migrate` task.

**As shipped:**

- Three tasks in `Taskfile.yml`: `env` (copies `backend/.env.example` → `backend/.env`; uses a
  `status:` check so it's skipped when the file exists — which also covers worktrees, where
  `wt:new` already symlinks it), `data:load` (`migrate`, then `load_uspvdb {{.CLI_ARGS}}`, so
  `task data:load -- <path-or-url>` overrides the source), and `setup` (`env`, `docker compose
  build web`, `data:load`).
- **Addition — defensive Postgres healthcheck:** `docker-compose.yml` now probes with
  `pg_isready -h 127.0.0.1` (TCP). On a fresh volume the image first runs a temporary init
  server that listens only on the Unix socket, so a socket probe can report healthy just
  before the real server restarts; only the real server listens on TCP. A "connection
  refused" right after a fresh DB came up was seen once earlier in the project, but it did
  **not** reproduce in 6 fresh-volume runs before the change or 6 after, so this is
  hardening for slower machines, not a demonstrated fix.
- Verified from an empty volume: `task setup` → 6,611 facilities created (16 s including the
  download); a second `task data:load` → 0 created / 6,611 updated; `task data:load --
  /nonexistent` → clean `CommandError`; `task env` in a scratch git repo creates the file
  once and never overwrites an edited one; 12 fresh-volume `migrate` runs, 0 failures;
  `task check` passes (16 tests).

## Step 3 — Getting-started docs + wrap-up (#21)

- New short `README.md` (prereqs: Docker, Task; `task setup`; `docker compose up`; open
  `/`); mention `task data:load` for refreshes and that upsert never deletes rows removed
  upstream (a `--prune` flag is deferred).
- `AGENTS.md` Commands + `docs/requirements.md` ingestion note; plan `Status: Complete`.
- Note the local-DB-volume recreate step (`down -v`) for old-image volumes.

**Added scope (requested at the start of this step):** the README documents every dependency —
Docker with Compose v2, Task (with download link), Git 2.31+ — with install links, a check
command and the tested version for each; what is *not* needed (Python, GDAL, PostGIS, Node);
internet, disk (~3 GB) and port requirements; and platform notes (macOS Apple Silicon tested;
Linux expected; Windows via WSL 2, untested), so someone can read it cold and run the app.

**As shipped:**

- `README.md`: prerequisites table, quick start (`task setup`, `docker compose up`, open `/`),
  everyday commands, a "Without Task" equivalent, configuration (`backend/.env`, optional root
  `.env` for ports), the data section (citation, refresh, loading a manually downloaded file —
  which must sit under `backend/`), the API, troubleshooting (Docker not running, ports,
  Task missing, old-volume collation error, offline download, empty map, OSM 403), workflow
  pointers and licensing. It states the current large-payload limitation (#15) and, at the
  time, that the repo had no code license (an MIT license was added afterwards in #23).
- `AGENTS.md` (Commands + layout) and `docs/requirements.md` (ingestion note) updated; the
  completed ingestion plan's "run against the real download" follow-up is marked done.
- **Verified by following the README literally:** the "Without Task" commands from an empty
  volume (6,611 facilities), the documented `/`, `/admin/login/` and `nearest` example
  (returns real Los Angeles facilities) and a `400` on bad input; loading a manually
  downloaded zip placed in `backend/`; a path outside `backend/` fails with the clear
  "Could not read" error. This caught a bug in the first draft: `cp -n` exits non-zero when it
  skips an existing file, so the README uses `[ -f backend/.env ] || cp …` instead.
- **Extra fix (found while collecting sizes for the README):** `task wt:rm` left each
  worktree's ~1.5 GB `web` image behind. It now runs `docker compose down -v --rmi local`
  (tested on a throwaway worktree: image removed). Ten images already leaked by earlier
  removed worktrees were deleted by hand.
- Status set to `Complete`.

## Verification

`task check`; then from a clean worktree (`task wt:new`): `task setup` → 6,611 rows
(`manage.py shell -c ...count()`), second `task data:load` → 0 created / 6,611 updated.

## Deferred to a later pass (not in this slice)

- `--prune` for facilities dropped upstream.
- Download caching across worktrees.
