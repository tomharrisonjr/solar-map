# CI/CD on GitHub Actions: build once, deploy by IAM

- GitHub Issue: #53
- Date: 2026-10-06
- Status: Draft

## Steps

| Status | # | Step |
|--------|---|------|
| ⬜ Pending | 1 | CI workflow: check on PRs, build and push the image on main |
| ⬜ Pending | 2 | Deploy script and SSM document |
| ⬜ Pending | 3 | OIDC provider, per-env deploy roles, GitHub environments |
| ⬜ Pending | 4 | Deploy workflow with smoke test and rollback |
| ⬜ Pending | 5 | First prod deploy, rollback drill and docs |

## Context

Dev and prod exist on Lightsail with SSM-only access (#51/#52), but nothing runs tests on a PR
and every deploy is hand-typed commands over `task ssm` (prod isn't deployed at all yet). Goal: a
pipeline where CI gates merges, an image is built once per commit, and a deploy is one click that
authenticates to AWS purely with GitHub OIDC, with no long-lived keys anywhere.

Starting point (verified): no workflows, no GitHub Environments, no branch protection, no OIDC
provider in the personal AWS account; the repo is public; `task check` is the local gate.

## Decisions (made with the user)

- **Image: built in CI, pushed to GHCR** (`ghcr.io/tomharrisonjr/solar-map-web:<sha>`), pulled by
  the host. The repo is public so the package is public and the host needs no registry
  credentials. Immutable per commit; rollback = deploy an older sha; the 2 GB box never builds.
  (ECR rejected: a Lightsail host can't have an instance profile, so it would need a stored key.)
- **Deploys are manual for both environments** (`workflow_dispatch`: env + sha). Merging to `main`
  builds and tests but never deploys. GitHub Environments `dev` and `prod` exist to scope the
  OIDC trust (`...:environment:prod`), not to add approval gates (single owner).
- **Mechanism: GitHub OIDC -> per-env IAM role -> `ssm:SendCommand`** of one Terraform-managed SSM
  document. The role can run that document, not arbitrary shell, and only on its own env's node.
  No secrets in GitHub: the role ARN is a non-secret environment variable.

## Step 1 — CI workflow

- `.github/workflows/ci.yml`, on `pull_request` and `push` to `main`:
  - Job `check`: checkout, `arduino/setup-task`, `hashicorp/setup-terraform`, `task env`
    (creates `backend/.env` from the example), then `task check` (ruff, tests against the compose
    PostGIS, `terraform fmt`/`validate`). Reusing the Taskfile keeps CI and local identical.
  - Job `image` (push to `main` only, `needs: check`): `docker/login-action` to GHCR with
    `GITHUB_TOKEN` (`packages: write`), `docker/build-push-action` for `./backend`, tags `:<sha>`
    and `:main`, label `org.opencontainers.image.source` so GHCR links it to the repo, GHA layer
    cache. Skips if the sha tag already exists.
- `docker-compose.prod.yml`: `web` gets `image: ${WEB_IMAGE:-solar-map-web:local}` beside the
  existing `build: ./backend`, so local `up --build` still works and the host can `pull`.
- Make the package public once (GHCR defaults can be private for user packages); verify an
  anonymous `docker pull` works before relying on it.
- Branch protection on `main`: require `check` to pass (via `gh api`, with the user's approval,
  since it changes repo settings).
- Concurrency group per ref cancels superseded PR runs. Official actions pinned to major versions.

## Step 2 — Deploy script and SSM document

- `scripts/deploy.sh <sha>` (POSIX sh, in the repo so it is versioned with the app), run as
  `ubuntu` in `~/solar-map`. Idempotent; the same script does first deploy and updates:
  1. If `backend/.env` is missing, create it (`SITE_ADDRESS` from the document parameter,
     `SECRET_KEY`/`DATABASE_PASSWORD` generated on the host with `openssl rand`, `umask 077`).
  2. Record the currently running image as the rollback target, set `WEB_IMAGE` to `<sha>`.
  3. `docker compose ... pull`, `up -d --wait` (compose healthchecks gate "up"), `manage.py
     migrate --noinput`, then `load_uspvdb --if-empty` (new flag + test in
     `facilities/management/commands/load_uspvdb.py`) so a fresh host loads data automatically.
  4. On any failure after step 2: print container logs, re-`up` the previous image, exit non-zero.
  5. Prune dangling images; print the running image tag.
- `infra/main.tf`: `aws_ssm_document` `solar-map-<env>-deploy` (Command type, `aws:runShellScript`):
  parameters `sha` (validated as 40 hex) and `siteAddress` (default `local.fqdn`); steps `git
  fetch origin`, `git checkout --detach <sha>`, `exec scripts/deploy.sh <sha>` as `ubuntu`. Fetching
  first means the script that runs is the one from the deployed commit.
- Verify by hand once on dev with `aws ssm send-command` before any workflow exists.

## Step 3 — OIDC provider, per-env deploy roles, GitHub environments

- `infra/bootstrap/main.tf` (account-wide, applied once per account, like the state bucket):
  `aws_iam_openid_connect_provider` for `https://token.actions.githubusercontent.com`, client id
  `sts.amazonaws.com`.
- `infra/main.tf` (per workspace): `data "aws_iam_openid_connect_provider"`;
  `aws_iam_role.github_deploy` named `solar-map-<env>-deploy`, trust policy
  `StringEquals token.actions.githubusercontent.com:sub = repo:tomharrisonjr/solar-map:environment:<env>`
  and `aud = sts.amazonaws.com`; inline policy: `ssm:SendCommand` on the env's document ARN plus
  the managed-instance ARN restricted by `ssm:resourceTag/Name = solar-map-<env>` (the activation
  already tags nodes; **verify the tag reaches the registered node, else scope another way**), and
  read-only `ssm:GetCommandInvocation`, `ListCommandInvocations`, `DescribeInstanceInformation`.
  Output `deploy_role_arn`.
- `Taskfile.yml`: `task gh:env ENV=dev` creates the GitHub environment and sets the non-secret
  variables `AWS_DEPLOY_ROLE_ARN`, `AWS_REGION`, `SITE_URL` from `tf:output` (`gh api` / `gh
  variable set --env`). No GitHub secrets.
- Verify with `aws iam simulate-principal-policy`: dev role allowed on the dev document and node,
  denied on prod's and on `AWS-RunShellScript`.

## Step 4 — Deploy workflow

`.github/workflows/deploy.yml`, `workflow_dispatch` inputs `environment` (dev|prod) and `sha`
(default: head of `main`):

- `permissions: id-token: write, contents: read`; `concurrency: deploy-<env>` (no overlap);
  `environment: <env>`.
- Guard: fail early unless the `ci.yml` run for that sha succeeded and the image `:<sha>` exists.
- `aws-actions/configure-aws-credentials` with `vars.AWS_DEPLOY_ROLE_ARN`; `aws ssm send-command`
  with the env's document and `sha`; poll `get-command-invocation`; print the output; fail if the
  status isn't `Success`.
- Smoke test from the runner against `vars.SITE_URL`: `/` returns 200, a vector tile returns 200,
  `/api/facilities/nearest/?lat=35&lon=-118` returns features. Failure fails the run (the host has
  already rolled back if the deploy itself failed).
- Job summary: env, sha, image, URL.

## Step 5 — First prod deploy, rollback drill and docs

1. Merge steps 1-4; user applies Terraform: `task tf:bootstrap` (OIDC provider), then `task
   tf:apply ENV=dev` and `ENV=prod` (additions only: document, role; no instance replacement).
2. `task gh:env ENV=dev`, `task gh:env ENV=prod`.
3. Run the deploy workflow for dev, then prod: this is prod's first deploy and the `.env`/data
   bootstrap happens automatically. Register `solar-map.tomharrisonjr.com` in Stadia if not yet.
4. Drill: deploy a deliberately broken sha to dev and confirm the old version keeps serving;
   deploy an older good sha to prove rollback; `tf:rebuild ENV=dev` then re-run deploy to prove a
   rebuilt box needs no hand steps.
5. Docs: write `docs/deploy.md` (pipeline, deploy and rollback, first-time setup, rebuild, stale
   SSM nodes, refreshing data); link from `README.md`; update `AGENTS.md` layout/commands and
   `docs/requirements.md`; mark step 6 of `aws-single-instance-hosting.md` and its `Status` complete.

## Risks / open items

- GHCR package visibility (see step 1); fall back to a one-time UI change.
- SSM tag-scoped `SendCommand` (see step 3); fall back to document-only scoping.
- Destructive Django migrations are not reversed by the rollback (only the image is);
  fine for a read-only dataset app, noted in `docs/deploy.md`.
- Out of scope: staging, uptime monitoring, Dependabot, scheduled data refresh.

## Verification

PR CI green and `check` required on `main`; an image appears in GHCR per merge; anonymous pull
works; `simulate-principal-policy` results as above; dev and prod deploy via the workflow with the
smoke test passing at `dev.solar-map...` and `solar-map.tomharrisonjr.com` (HTTPS, tiles, nearest,
admin redirect, 6,611 facilities, port 22 still dropped); broken-sha and rollback drills pass;
`task check` stays green.
