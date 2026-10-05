# SSM access (no SSH) and subdomain-per-environment hostnames

- GitHub Issue: #51
- Date: 2026-10-05
- Status: Complete

## Steps

| Status | # | Step |
|--------|---|------|
| ✅ Done | 1 | Env hostnames: bare prod, subdomains for dev/staging |
| ✅ Done | 2 | SSM access: hybrid activation, agent in user_data, close port 22 |
| ✅ Done | 3 | Tasks and docs: `task ssm`, `tf:rebuild`, README/AGENTS/plan updates |
| ✅ Done | 4 | Rebuild dev and verify |

## Context

The first dev deploy exposed two problems with the Terraform from step 4:

1. **SSH is the wrong access model.** Port 22 is gated on a personal IP (`ssh_allowed_cidr`),
   which breaks across two machines and changing home IPs, and needs a long-lived key pair.
   Wanted: shell access authorised purely by IAM, like ECR, with no inbound ports.
2. **Hostnames are awkward.** `solar-map-<env>` names plus a prod-only alias CNAME and a Caddy
   redirect exist only so prod can be `solar-map.*`. Stadia allows subdomains of a registered
   domain, so envs can live *under* the prod name.

Also fixed in passing: `user_data` failed silently under `dash` (re-exec-under-bash guard already
made, uncommitted, in `infra/user_data.sh.tftpl`). The dev instance is disposable and gets
rebuilt, which doubles as the planned rebuild drill.

## Decisions (made with the user)

- **Prod hostname: bare `solar-map.tomharrisonjr.com`**, no `prod.` prefix. The public name is the
  one real A record. dev/staging: `dev.solar-map.tomharrisonjr.com`, `staging.solar-map...`.
  Rationale: prod's URL is the one people use and Stadia registers; a `prod.` name would only
  bring back the alias/redirect machinery this removes.
- **Port 22 closed fully.** No SSH rule, no key pair, no `ssh_allowed_cidr`. Break-glass if the
  agent ever fails to register: Lightsail console/CLI (open the port temporarily there).
- Access is **SSM Session Manager via a hybrid activation** (Lightsail instances aren't EC2 and
  can't take an instance profile); standard tier is free.

## Step 1 — Env hostnames

- `infra/variables.tf`: `subdomain` stays the record name within the zone but may contain dots
  (`"dev.solar-map"`). Delete the `alias` variable and its validation.
- `infra/main.tf`: delete `aws_route53_record.alias` and `local.public_fqdn`; `local.fqdn` is the
  only name. The A record is unchanged apart from the name.
- `infra/envs/*.tfvars`: `prod` → `subdomain = "solar-map"`; `dev` → `"dev.solar-map"`;
  `staging` → `"staging.solar-map"`. Delete prod's `alias`.
- `infra/outputs.tf`: `site_url`/`site_address` from `local.fqdn`; remove `redirect_from`.
- Remove `REDIRECT_FROM`: `Caddyfile` (back to `{$SITE_ADDRESS} { reverse_proxy web:8000 }`, drop
  the `@elsewhere` redirect and its header comment), `docker-compose.prod.yml` (caddy env line),
  `backend/.env.example` (the REDIRECT_FROM block), `AGENTS.md` layout line for the Caddyfile.
  Validate with `caddy validate` via docker, as step 4 did.
- Stadia: one registration of `solar-map.tomharrisonjr.com` covers the subdomains (user-stated;
  verify with a tile request carrying a `dev.solar-map` Referer after the rebuild).
- Existing dev records (`solar-map-dev` A record) are destroyed/recreated by the rebuild.

## Step 2 — SSM access

All in `infra/main.tf` (+ `user_data.sh.tftpl`, `variables.tf`, tfvars files):

- `aws_iam_role` assumed by `ssm.amazonaws.com`, with `AmazonSSMManagedInstanceCore` attached.
  Named from `local.name`, so each env gets its own role.
- `aws_ssm_activation` (`iam_role`, `registration_limit = 5`, default 24h expiry, tag
  `Name`). SSM can't filter nodes by tag, so `task ssm` finds the node by its per-env role name
  (`describe-instance-information --filters Key=IamRole,...`).
- `user_data.sh.tftpl`: pass `activation_id`, `activation_code`, `aws_region`; run AWS's
  `ssm-setup-cli -register` (downloaded from the regional `amazon-ssm-<region>` bucket, arch from
  `dpkg`), which installs the agent and registers it. Do this **first**, with `set +x` so the code
  stays out of the cloud-init log, so a later failure still leaves a shell. Keep the bash re-exec
  guard.
- Activation code/ID end up in `user_data` and state: short-lived, registration-only, not
  app secrets (app secrets stay in the hand-made `backend/.env`). Note this in a comment.
- Delete `aws_lightsail_key_pair.this`, `key_pair_name`, the port-22 `port_info` block,
  `ssh_allowed_cidr`, `ssh_public_key_path`, and the `ssh_command` output (replace with
  `ssm_command` hint). Remove the matching lines from `terraform.tfvars.example`,
  `.envrc.example` and the local gitignored `infra/.envrc` (PUBLIC_IP / TF_VAR_ssh_allowed_cidr).
- **Rebuild gotcha:** `user_data` is `ignore_changes`, and the activation expires, so a rebuild
  must replace instance *and* activation together. Add `task tf:rebuild ENV=…` running
  `terraform apply -replace=aws_lightsail_instance.this -replace=aws_ssm_activation.this`.
  Stale `mi-…` registrations from destroyed instances linger in SSM; the rebuild notes
  say to deregister them (`aws ssm deregister-managed-instance`).

## Step 3 — Tasks and docs

- `Taskfile.yml`: `task ssm ENV=dev` — resolves the instance id with
  `aws ssm describe-instance-information --filters Key=tag:Name,Values=solar-map-<env>`, then
  `aws ssm start-session --target <id>` (lands as `ssm-user`; document `sudo -iu ubuntu`).
  Add `tf:rebuild`. Don't set an account-wide Session Manager "run as" preference: it's a
  singleton shared by every env and workspace.
- `README.md`: add the Session Manager plugin (`brew install --cask session-manager-plugin`) to
  the prerequisites; replace SSH-IP/key instructions; note that AWS_PROFILE must be the personal
  profile (`tharrisondev`) — the shell default `aec-developer` is the work account and 403s on
  the state bucket.
- `docs/plans/aws-single-instance-hosting.md`: update the as-shipped notes (alias removed, SSH
  replaced), and rewrite step 6 around SSM; `AGENTS.md` layout/commands updated.
- Commit the existing `user_data` fix with step 2.

## Step 4 — Rebuild dev and verify

1. `task tf:plan ENV=dev` — expect: instance, key pair, ports, A record, static IP attachment
   replaced/changed; IAM role and activation added. Nothing outside dev. User approves apply.
2. `task tf:rebuild ENV=dev` (billable resources; user runs or approves).
3. Wait for cloud-init; confirm `cloud-init status` AND the agent: `aws ssm describe-instance-information` shows the instance `Online`.
4. `task ssm ENV=dev` opens a shell; `docker --version` and `~/solar-map` present (proves the
   user_data fix too).
5. Create `backend/.env` on the host (secrets generated there), `docker compose … up -d --build`,
   `migrate`, `load_uspvdb`; check 6,611 facilities.
6. Over HTTPS at `dev.solar-map.tomharrisonjr.com`: cert issued, HTTP→HTTPS, `/`, a tile,
   `/api/facilities/nearest/`, `/admin/` redirect; basemap tiles load (Stadia registration).
7. Port 22 times out (check with a Python socket and a 5 s timeout: macOS `nc -w` ignores its
   timeout while connecting and waits ~75 s); `task check` passes (ruff, tests, `terraform fmt/validate`).

## As shipped

Everything above landed as planned, with these differences found by the dev rebuild drill:

- `task ssm` finds the node by the per-env IAM role name (`IamRole` filter), not by tag: SSM can't
  filter nodes by tag. It takes the node that **pinged most recently**, because a destroyed box's
  registration keeps reporting `Online` for a while. The command is passed in an env var and the
  JSON built in Python, since Task re-quotes `-- "a b"` and corrupted a hand-built JSON string.
  Use `task ssm ENV=dev -- docker ps` (unquoted).
- `user_data` aborted on `systemctl reload ssh`: Ubuntu 24.04 starts sshd on demand (socket
  activation) and port 22 is closed, so the service is inactive and `reload` fails under `set -e`.
  It now uses `try-reload-or-restart`. `cloud-init status` reported `error` while
  `cloud-init analyze` showed nothing wrong; the cause is only in `/var/log/cloud-init-output.log`.
  SSM registration runs first, so the box stayed reachable while it failed late.
- Replacing the instance left it on Lightsail's default firewall (22 and 80 open, 443 closed):
  `aws_lightsail_instance_public_ports` attaches by instance *name*, so Terraform saw no change.
  It now has `replace_triggered_by = [aws_lightsail_instance.this.id]`.
- Verified on dev at `dev.solar-map.tomharrisonjr.com`: certificate, HTTP to HTTPS, `/`, a tile,
  `nearest`, `/admin/` redirect, 6,611 facilities, Stadia tiles for the dev and prod referers,
  port 22 dropped, 80 and 443 open.
- Stale SSM registrations from rebuilt boxes stay listed offline; remove with
  `aws ssm deregister-managed-instance --instance-id mi-...`.

## Out of scope

Prod apply and `docs/deploy.md` (step 6 of the original plan); CI deploys via GitHub OIDC +
`aws ssm send-command` (the natural next step, enabled by this one).
