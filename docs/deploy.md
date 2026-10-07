# Deploying solar-map

How code gets from `main` to the Lightsail hosts, and how to operate them. Design and rationale:
[`docs/plans/ci-cd-github-actions.md`](plans/ci-cd-github-actions.md) and
[`docs/plans/aws-single-instance-hosting.md`](plans/aws-single-instance-hosting.md).

## How it fits together

```
PR ──► ci.yml: `task check` (ruff, tests, terraform fmt/validate)       required to merge
main ─► ci.yml: check, then build ghcr.io/tomharrisonjr/solar-map-web:<sha>
you ──► deploy.yml (manual: environment + sha)
          └─ GitHub OIDC ─► IAM role solar-map-<env>-deploy
                └─ ssm:SendCommand ─► SSM document solar-map-<env>-deploy, on that env's node only
                      └─ git checkout <sha> && scripts/deploy.sh <sha> <hostname>
                            pull image, `up -d --wait`, migrate, load data if empty,
                            roll back to the previous image if anything fails
          └─ smoke test from the runner against the site's public URL
```

- **Nothing deploys on merge.** Merging builds and tests; you choose when to deploy and where.
- **No keys anywhere.** GitHub holds no secrets, only four non-secret variables per environment.
  The role trusts only workflow runs that target its own GitHub Environment, and may only run its
  own deploy document on its own instance.
- **The host never builds.** It pulls an immutable image tagged with the commit sha.
- **Environments:** `dev` (`dev.solar-map.tomharrisonjr.com`) and `prod`
  (`solar-map.tomharrisonjr.com`). Staging exists in Terraform but isn't applied or deployable.

## Day to day

Deploy (blank sha = head of `main`; the commit's CI run must have passed):

```
gh workflow run deploy.yml -f environment=dev
gh workflow run deploy.yml -f environment=prod -f sha=<40-char sha>
gh run watch                      # or the Actions tab
```

Roll back by deploying an older sha the same way: every commit that reached `main` has an image.
A deploy that fails on the host puts the previous image back by itself and fails the run. Database
migrations are **not** reversed by a rollback (only the image is); migrations here are additive.

Logs and a shell: `task ssm ENV=dev` (see the README). The deploy's full output is in the run log.

## First-time setup (once per AWS account / environment)

Do these in order; the Terraform steps create IAM and SSM resources only, never replacing an
instance. All use the AWS profile that owns the state bucket (`export AWS_PROFILE=...`).

1. **Merge this work to `main`**, so CI builds the first image (check the *Actions* tab for the
   `image` job) and the deploy script and document exist in the repo the hosts clone.
2. **Make the image public** (first time only). GHCR packages published from a workflow are
   linked to the repo, but check *github.com/tomharrisonjr → Packages → solar-map-web → Package
   settings* and set visibility to **Public** if it isn't. Verify with no login:
   `docker pull ghcr.io/tomharrisonjr/solar-map-web:main`. (The deploy workflow also checks this.)
3. `task tf:bootstrap`: creates the account-wide GitHub OIDC provider.
4. `task tf:apply ENV=dev`, then `task tf:apply ENV=prod`: each adds the deploy document and role
   (the plan should show only additions).
5. `task gh:env ENV=dev` and `task gh:env ENV=prod`: create the GitHub Environments and set
   `AWS_DEPLOY_ROLE_ARN`, `AWS_REGION`, `DEPLOY_DOCUMENT`, `SITE_URL` from Terraform's outputs.
   Needs `gh` logged in with admin rights on the repo.
6. **Require CI on `main`** (repo setting, once): Settings → Branches → rule for `main` → require
   status check `check`. Or: `gh api -X PUT repos/tomharrisonjr/solar-map/branches/main/protection --input -`
   with `required_status_checks.contexts=["check"]`.
7. **Register the hostname in Stadia** (Basemap authenticates by domain): `solar-map.tomharrisonjr.com`
   covers its subdomains.
8. Deploy `dev`, then `prod`, with the commands above. On a fresh host the first deploy creates
   `backend/.env` (secrets generated on the box with `openssl`, never sent from here) and loads
   the USPVDB dataset because the database is empty; later deploys skip both.

## Rebuilding an environment

`task tf:rebuild ENV=dev` destroys and recreates the instance together with a fresh SSM
activation; the static IP and DNS stay. The box comes up empty (Docker, the repo clone, SSM):
run the deploy workflow again and it rebuilds `.env`, the stack and the data with no hand steps.
The old box's SSM node lingers as `ConnectionLost`; tidy with
`aws ssm deregister-managed-instance --instance-id mi-...`. Deploys and `task ssm` already pick the
most recently pinged node, so it's cosmetic.

## Refreshing the dataset

`load_uspvdb` upserts by `case_id`, so re-running refreshes in place:
`task ssm ENV=prod -- sh -c 'cd solar-map && docker compose --env-file backend/.env -f docker-compose.prod.yml exec -T web python manage.py load_uspvdb'`.
Deploys only load when the table is empty (`--if-empty`).

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Deploy fails at "Require a successful CI run" | The sha isn't on `main`, or its CI run failed or is still going. |
| "Require the image to exist" fails | The `image` job hasn't finished, or the GHCR package is private (step 2 above). |
| `AccessDenied` assuming the role | The job's environment doesn't match the role's trust (`environment: <env>` must be `dev` or `prod`), or `AWS_DEPLOY_ROLE_ARN` is stale: re-run `task gh:env`. |
| "no SSM node registered" | The instance is down or still booting (the agent registers in the first minute); check `task ssm ENV=<env>`. |
| Deploy fails, run log shows the host rolled back | Read the `deploy failed; recent web logs` block in the run log; the previous version is still serving. |
| `tf:plan` errors reading the IAM OIDC provider | `task tf:bootstrap` hasn't been applied in this account yet (step 3). |
| Site unreachable right after a fresh deploy | Caddy is still obtaining its certificate (a minute or two), or DNS is cached locally (`dig` works but `curl` doesn't: flush the OS cache). |
