# One-command data bootstrap (USPVDB download + load)

- GitHub Issue: #14
- Date: 2026-09-29
- Status: Draft

## Steps

| Status | # | Step |
|--------|---|------|
| ⬜ Pending | 1 | `load_uspvdb` accepts zip/URL and defaults to the official source |
| ⬜ Pending | 2 | Taskfile: `data:load` and `setup` |
| ⬜ Pending | 3 | Getting-started docs + wrap-up |

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

## Step 1 — `load_uspvdb` accepts zip/URL and defaults to the official source

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

## Step 2 — Taskfile: `data:load` and `setup`

`Taskfile.yml`: `data:load` (`task migrate` first, then
`docker compose run --rm web python manage.py load_uspvdb`); `setup` = create `backend/.env`
from `.env.example` if missing, `docker compose build web`, then `data:load`. Reuse the existing
`migrate` task.

## Step 3 — Getting-started docs + wrap-up

- New short `README.md` (prereqs: Docker, Task; `task setup`; `docker compose up`; open
  `/`); mention `task data:load` for refreshes and that upsert never deletes rows removed
  upstream (a `--prune` flag is deferred).
- `AGENTS.md` Commands + `docs/requirements.md` ingestion note; plan `Status: Complete`.
- Note the local-DB-volume recreate step (`down -v`) for old-image volumes.

## Verification

`task check`; then from a clean worktree (`task wt:new`): `task setup` → 6,611 rows
(`manage.py shell -c ...count()`), second `task data:load` → 0 created / 6,611 updated.

## Deferred to a later pass (not in this slice)

- `--prune` for facilities dropped upstream.
- Download caching across worktrees.
