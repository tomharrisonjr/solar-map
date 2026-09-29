# Solar Map

A small learning project for PostGIS and GeoDjango. It loads the
[USPVDB](https://eerscmap.usgs.gov/uspvdb/) (USGS/LBNL United States Large-Scale Solar
Photovoltaic Database) — 6,600+ ground-mounted solar facilities with their panel-array
polygons — into a PostGIS database, exposes it as a GeoJSON API, and shows it on a map where
you can click anywhere to find the nearest facilities.

- **Backend:** Django + GeoDjango + Django REST Framework, PostGIS
- **Map:** a single server-rendered page using [MapLibre GL JS](https://maplibre.org/) (loaded from a CDN — no frontend build step)
- **Everything runs in Docker**, so you don't install Python, GDAL, GEOS or PostGIS on your machine

Design and goals: [docs/requirements.md](docs/requirements.md). Free to use, modify and share
under the [MIT License](LICENSE) (code only — see [Licensing](#acknowledgements-and-licensing)).

## Prerequisites

Install these first. Each row says how to check that it's installed.

| Tool | What it's for | Install | Check | Tested with |
| --- | --- | --- | --- | --- |
| **Docker** with **Compose v2** | Runs the database and the Django app | [Docker Desktop](https://docs.docker.com/get-docker/) (macOS, Windows) or [Docker Engine](https://docs.docker.com/engine/install/) + the [Compose plugin](https://docs.docker.com/compose/install/) (Linux) | `docker compose version` | Docker 29.8, Compose v5.5 |
| **Task** (go-task) | Runs the project's commands (`task setup`, `task check`, …) | [taskfile.dev/installation](https://taskfile.dev/installation/) — e.g. `brew install go-task` on macOS | `task --version` | Task 3.52 |
| **Git** 2.31 or newer | Cloning the repo; the Taskfile also uses it | [git-scm.com/downloads](https://git-scm.com/downloads) | `git --version` | Git 2.50 |

Also needed:

- **Docker must be running** (start Docker Desktop, or the Docker service on Linux) before you run any command below.
- **Internet access** for the first setup (pulls container images, installs Python packages, downloads the ~10 MB dataset from USGS) and whenever you view the map (MapLibre is loaded from a CDN and the basemap tiles come from OpenStreetMap).
- **Disk space:** about 3 GB (the container images are ~2.3 GB).
- **Free ports:** `5432` (Postgres) and `8000` (the web app). If either is taken, see [Configuration](#configuration).

You do **not** need Python, Node, PostgreSQL, PostGIS or GDAL on your machine — they all live in the containers. The container images are multi-architecture (Intel/AMD and Apple Silicon/ARM), so they run natively on either.

**Platforms:** developed and tested on macOS (Apple Silicon). Linux should work the same way. On Windows, use [WSL 2](https://learn.microsoft.com/windows/wsl/install) and run everything inside it (untested).

## Quick start

```sh
git clone https://github.com/tomharrisonjr/solar-map.git
cd solar-map

task setup            # one time: config file, build the image, create the DB, download + load the data
docker compose up     # start the database and the web app
```

Then open **<http://localhost:8000/>** and click anywhere on the map: the five nearest solar
facilities are highlighted and listed in the sidebar with their distance.

`task setup` takes a few minutes the first time (mostly building the Docker image). It:

1. creates `backend/.env` from `backend/.env.example` if it doesn't exist,
2. builds the Django image,
3. starts the database and applies migrations, and
4. downloads the official USPVDB release from USGS and loads it (~6,600 facilities, a few seconds).

It's safe to run again: nothing is duplicated and your `.env` is never overwritten.

> **Known limitation:** the map currently downloads every facility's polygon on page load
> (about 25 MB), so the first load can take several seconds. This is being replaced by vector
> tiles ([#15](https://github.com/tomharrisonjr/solar-map/issues/15)).

## Everyday commands

Run `task --list` to see them all.

| Command | What it does |
| --- | --- |
| `task setup` | First-time setup (see above) |
| `docker compose up` | Run the app at <http://localhost:8000/> (add `-d` to run in the background; `docker compose down` stops it) |
| `task check` | Lint (ruff) + run the tests — run this before calling a change done |
| `task lint` / `task test` | Just one half of `task check` |
| `task migrate` | Start the database and apply migrations |
| `task data:load` | Download and (re)load the USPVDB dataset — use this to refresh the data |
| `task env` | Create `backend/.env` from the example if missing (also done by `task setup`) |
| `docker compose run --rm web python manage.py createsuperuser` | Create an admin user for <http://localhost:8000/admin/> |
| `docker compose down -v` | Stop everything **and delete the database** (start over with `task setup`) |

### Without Task

Task is only a convenience wrapper. If you'd rather not install it, `task setup` is equivalent to:

```sh
[ -f backend/.env ] || cp backend/.env.example backend/.env   # only if it doesn't exist yet
docker compose build web
docker compose up -d --wait db
docker compose run --rm web python manage.py migrate
docker compose run --rm web python manage.py load_uspvdb
```

and `task check` to:

```sh
docker compose run --rm web ruff check .
docker compose run --rm web python manage.py test
```

## Configuration

Defaults work for local development; you normally change nothing.

- **`backend/.env`** — Django settings (`DEBUG`, `SECRET_KEY`, `ALLOWED_HOSTS`, database name/user/password). Created from [backend/.env.example](backend/.env.example) by `task setup`. Set a real `SECRET_KEY` and `DEBUG=False` for anything that isn't local development.
- **`.env`** (repo root, optional) — only if ports `5432` or `8000` are already in use on your machine: copy [.env.example](.env.example) to `.env` and set `DB_PORT` / `WEB_PORT` to free ports (then browse to `http://localhost:<WEB_PORT>/`).

Both files are gitignored.

## The data

The dataset is the [USPVDB](https://eerscmap.usgs.gov/uspvdb/data/) from the U.S. Geological
Survey and Lawrence Berkeley National Laboratory. It is **not stored in this repository**;
`load_uspvdb` downloads the official release (`uspvdbGeoJSON.zip`, ~10 MB), unpacks it in
memory and upserts the facilities by their stable `case_id`.

> **Citation** (required by USGS; the command also prints it): Fujita, K.S., Ancona, Z.H.,
> Kramer, L.A., Straka, M., Gautreau, T.E., Garrity, C.P., Robson, D., Diffendorfer, J.E.,
> and Hoen, B., 2023, United States Large-Scale Solar Photovoltaic Database: U.S. Geological
> Survey and Lawrence Berkeley National Laboratory data release. Cite the version shown on
> the [USPVDB data page](https://eerscmap.usgs.gov/uspvdb/data/).

- **Refresh** with `task data:load`. USPVDB is updated about once a year. Note that this
  only adds and updates facilities — a facility that USGS later removes stays in your
  database until you reset it (`docker compose down -v`, then `task setup`).
- **Load a file you downloaded yourself** (e.g. you're offline or the download is blocked):
  save the zip — or the extracted `.geojson` — **inside the `backend/` folder** (that's the
  only host folder the container can see), then run
  `task data:load -- uspvdbGeoJSON.zip` (the path is relative to `backend/`). A URL works
  too: `task data:load -- https://…`.

## API

| Endpoint | Returns |
| --- | --- |
| `GET /api/facilities/` | Every facility as a GeoJSON `FeatureCollection` (large — see the known limitation above) |
| `GET /api/facilities/nearest/?lat=<lat>&lon=<lon>&n=<count>` | The `n` closest facilities (default 5, max 25) to a point, nearest first, each with a `distance_m` property in metres. Invalid input returns `400`. |
| `GET /admin/` | Django admin (after creating a superuser) |

Example: `curl "http://localhost:8000/api/facilities/nearest/?lat=34.05&lon=-118.24&n=3"`

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `Cannot connect to the Docker daemon` | Start Docker Desktop (or the Docker service), then retry. |
| `port is already allocated` / `address already in use` | Something else is using `5432` or `8000`. Stop it, or set `DB_PORT` / `WEB_PORT` in a root `.env` (see [Configuration](#configuration)). |
| `task: command not found` | Install Task ([taskfile.dev/installation](https://taskfile.dev/installation/)) or use the [equivalent Docker commands](#without-task). |
| `template database "template1" has a collation version mismatch` | You have a database volume from an older checkout that used a different Postgres image. It's disposable: `docker compose down -v`, then `task setup`. |
| `Could not download …` from `task setup` / `task data:load` | No internet, or USGS is unreachable. Download the zip from the [data page](https://eerscmap.usgs.gov/uspvdb/data/), put it in `backend/`, and run `task data:load -- uspvdbGeoJSON.zip`. |
| The map loads but shows no solar facilities | The data isn't loaded: run `task data:load`. |
| Map tiles show `403 Access Blocked` | OpenStreetMap's public tile server blocked the request. It requires the browser to send a `Referer` header (the app is configured to allow this); browser privacy extensions that strip it can trigger the block. The public server is best-effort — see [OpenStreetMap's tile usage policy](https://operations.osmfoundation.org/policies/tiles/). |

## Contributing / project workflow

- [AGENTS.md](AGENTS.md) is the guide for contributors and coding agents (`CLAUDE.md` is a
  symlink to it): repo layout, commands, conventions, and the plan-doc → issue → worktree → PR
  workflow. `task wt:new` / `task wt:rm` manage per-branch git worktrees.
- Non-trivial features start with a plan doc in [docs/plans/](docs/plans/).
- `task check` (lint + tests) must pass before a change is considered done.

## Acknowledgements and licensing

- **Code:** [MIT License](LICENSE) © 2026 Tom Harrison — free to use, copy, modify, and
  distribute, including commercially, as long as the copyright and license notice are kept.
  This covers the code and docs in this repository **only**.
- **Facility data:** the USGS / LBNL USPVDB is not part of this repository and is not covered
  by the MIT License. It is downloaded from USGS when you run `task setup`; see the
  [citation above](#the-data) and the [USPVDB data page](https://eerscmap.usgs.gov/uspvdb/data/)
  for its terms.
- **Basemap:** © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors, made
  available under the [ODbL](https://opendatacommons.org/licenses/odbl/); tiles are served by
  OpenStreetMap's public server under its
  [tile usage policy](https://operations.osmfoundation.org/policies/tiles/).
- **Libraries** (Django, Django REST Framework, MapLibre GL JS, PostGIS, …) keep their own
  licenses.
