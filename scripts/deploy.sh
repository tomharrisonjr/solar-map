#!/bin/sh
# Deploy one commit to this host: pull the image CI built for it, restart the stack, migrate, and
# load the dataset if the database is empty. Idempotent: the same script does a first deploy
# (it creates backend/.env) and every later update. If the new version doesn't come up healthy it
# puts the previous image back and exits non-zero.
#
#   scripts/deploy.sh <git-sha> <site-address>
#
# Run as the login user (ubuntu) from the repo checkout, which is already at <git-sha>; the SSM
# document `solar-map-<env>-deploy` does that, see infra/main.tf and docs/deploy.md.
set -eu

sha=${1:?usage: scripts/deploy.sh <git-sha> <site-address>}
site_address=${2:?usage: scripts/deploy.sh <git-sha> <site-address>}
IMAGE_REPO=${IMAGE_REPO:-ghcr.io/tomharrisonjr/solar-map-web}

case $sha in
  *[!0-9a-f]* | "") echo "sha must be lowercase hex" >&2; exit 2 ;;
esac

cd "$(dirname "$0")/.."

compose() {
  docker compose --env-file backend/.env -f docker-compose.prod.yml "$@"
}

# First deploy on a fresh host: create the production .env. Secrets are generated here and never
# leave the box (so they are in neither Terraform state nor GitHub). Existing files are kept.
if [ ! -f backend/.env ]; then
  echo "==> creating backend/.env"
  (
    umask 077
    {
      echo "SITE_ADDRESS=$site_address"
      echo "SECRET_KEY=$(openssl rand -base64 48 | tr -d '\n=+/')"
      echo "DATABASE_PASSWORD=$(openssl rand -hex 24)"
    } > backend/.env
  )
fi

# Image to fall back to: whatever the web container runs now (empty on a first deploy).
previous_image=$(docker inspect --format '{{.Config.Image}}' "$(compose ps -q web 2>/dev/null)" 2>/dev/null || true)

rollback() {
  echo "==> deploy failed; recent web logs:" >&2
  compose logs --tail 60 web >&2 || true
  if [ -n "$previous_image" ]; then
    echo "==> rolling back to $previous_image" >&2
    WEB_IMAGE=$previous_image compose up -d --wait --remove-orphans >&2 || echo "rollback also failed" >&2
  else
    echo "==> no previous image to roll back to" >&2
  fi
}

# `set -e` is switched off inside functions that run under `||` or `if`, so every step that must
# succeed goes through here and triggers the rollback explicitly.
step() {
  "$@" || { rollback; exit 1; }
}

WEB_IMAGE="$IMAGE_REPO:$sha"
export WEB_IMAGE

# Pulling first means a missing or unreachable image fails before anything running is touched.
echo "==> pulling $WEB_IMAGE"
compose pull web

echo "==> starting the stack"
step compose up -d --wait --remove-orphans

echo "==> migrating"
step compose exec -T web python manage.py migrate --noinput

echo "==> loading data if the database is empty"
step compose exec -T web python manage.py load_uspvdb --if-empty

docker image prune -f >/dev/null
echo "==> deployed $WEB_IMAGE"
compose ps
