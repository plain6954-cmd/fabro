# Web Push release procedure for the Scaleway host

This repository contains a Docker Compose runtime (`compose.yaml`) and a **systemd example** (`fabro.service.example`). The live Scaleway checkout, branch, environment path, and service manager are not recorded here. Run the discovery commands on the host first; use only the matching procedure below. Do not replace an existing VAPID pair.

## Read-only discovery

From the existing application checkout on the host:

```bash
pwd -P
git rev-parse --show-toplevel
git branch --show-current
git rev-parse HEAD
git status --short
docker compose ps 2>/dev/null || true
systemctl list-units --type=service --all --no-pager | grep -Ei 'fabro|gunicorn' || true
```

Confirm the checkout is clean and on `main2` before updating it. `compose.yaml` names the service `web`, container `fabro-web`, and private environment file `.env.production`; the Dockerfile builds static files with `collectstatic`. The systemd file is a template, so identify the actual unit and `EnvironmentFile` on the host. Do not display environment-file contents in a shared terminal log.

## Common preparation

```bash
APP_DIR="$(git rev-parse --show-toplevel)"
cd "$APP_DIR"
test "$(git branch --show-current)" = main2
test -z "$(git status --porcelain)"
OLD_SHA="$(git rev-parse HEAD)"
BACKUP_DIR="$HOME/fabro-release-backups/$(date +%Y%m%d-%H%M%S)"
mkdir -p -m 700 "$BACKUP_DIR"
git rev-parse HEAD > "$BACKUP_DIR/previous-commit"
git fetch origin main2
git merge-base --is-ancestor HEAD origin/main2
```

Inspect `git log --oneline HEAD..origin/main2` before continuing. `git merge --ff-only` below stops if the server has diverged; never reset or force push. Back up the private environment file and any local reverse-proxy/service configuration using the actual paths discovered on the host. Preserve owner and mode; keep backups outside Git.

## Docker Compose path — only if the live service uses `compose.yaml`

```bash
cd "$APP_DIR"
test -f .env.production
cp -p .env.production "$BACKUP_DIR/env.production"
OLD_IMAGE="$(docker inspect fabro-web --format '{{.Image}}')"
docker image tag "$OLD_IMAGE" "fabro:rollback-$OLD_SHA"
git merge --ff-only origin/main2
docker compose build web
docker compose run --rm --no-deps web python manage.py check_web_push
docker compose run --rm --no-deps web python manage.py check --deploy
docker compose up -d --no-deps web
docker compose exec -T web python manage.py check_web_push
docker compose exec -T web python manage.py check
curl --fail --silent --show-error http://127.0.0.1:18000/health/
docker compose ps web
```

The image build runs `collectstatic --noinput` in the Dockerfile. Confirm `check_web_push` reports `configured: True` before making the new image live. If it does not, stop and restore the **existing** keys into `.env.production` from the approved secret source; rebuild and recheck. Do not rotate keys merely to clear this error.

Rollback, using the saved image and commit:

```bash
cd "$APP_DIR"
git switch --detach "$OLD_SHA"
docker image tag "fabro:rollback-$OLD_SHA" fabro:production
docker compose up -d --no-deps --no-build --force-recreate web
curl --fail --silent --show-error http://127.0.0.1:18000/health/
```

Keep the backup directory and record the detached checkout; restore `main2` through a reviewed follow-up update.

## systemd path — only if the live service matches the template

Find the real unit, service user, and environment file before setting `SERVICE`, `SERVICE_USER`, and `ENV_FILE`:

```bash
systemctl show <ACTUAL_UNIT> -p FragmentPath -p WorkingDirectory -p User -p EnvironmentFiles -p ExecStart -p ExecReload
```

The template uses Gunicorn from an absolute virtual-environment path, `fabro_leather.wsgi:application`, and an external `EnvironmentFile`. The actual paths and unit name must come from the host. Then run:

```bash
cd "$APP_DIR"
SERVICE=<ACTUAL_UNIT>
SERVICE_USER=<ACTUAL_SERVICE_USER>
ENV_FILE=<ACTUAL_ENVIRONMENT_FILE>
PYTHON=<ACTUAL_VENV_PATH>/bin/python
cp -p "$ENV_FILE" "$BACKUP_DIR/environment"
git merge --ff-only origin/main2
sudo systemd-run --wait --pipe --collect -p "User=$SERVICE_USER" -p "WorkingDirectory=$APP_DIR" -p "EnvironmentFile=$ENV_FILE" "$PYTHON" manage.py check_web_push
sudo systemd-run --wait --pipe --collect -p "User=$SERVICE_USER" -p "WorkingDirectory=$APP_DIR" -p "EnvironmentFile=$ENV_FILE" "$PYTHON" manage.py check --deploy
sudo systemd-run --wait --pipe --collect -p "User=$SERVICE_USER" -p "WorkingDirectory=$APP_DIR" -p "EnvironmentFile=$ENV_FILE" "$PYTHON" manage.py collectstatic --noinput
sudo systemctl restart "$SERVICE"
sudo systemctl status "$SERVICE" --no-pager
curl --fail --silent --show-error https://<PORTAL_DOMAIN>/health/
```

Use the transient `systemd-run` commands only after confirming the live unit's environment comes from that `EnvironmentFile`; copy any additional unit-level environment settings into the transient invocation. Rollback commands, with the variables above still set:

```bash
cd "$APP_DIR"
git switch --detach "$OLD_SHA"
# Restore "$BACKUP_DIR/environment" to "$ENV_FILE" only if the environment file was changed.
sudo systemd-run --wait --pipe --collect -p "User=$SERVICE_USER" -p "WorkingDirectory=$APP_DIR" -p "EnvironmentFile=$ENV_FILE" "$PYTHON" manage.py collectstatic --noinput
sudo systemctl restart "$SERVICE"
curl --fail --silent --show-error https://<PORTAL_DOMAIN>/health/
```

Do not run migrations for this release; it adds no schema change.

## VAPID and real-delivery checks

`python manage.py check_web_push` is read-only and prints only booleans: whether each variable is present in the process environment, whether each effective setting exists, whether the public and private keys have usable formats, whether they match, and whether Django considers Web Push configured. The subject has a Django fallback, so its environment-presence flag may be false even when the effective setting is present. Django uses `fabro_leather.settings`; process environment variables take precedence over the checkout's `.env`. Compose supplies `.env.production` through `env_file`. The systemd example supplies an external `EnvironmentFile`.

If either key is absent, first recover the currently deployed pair from the approved secret backup. Check whether active `PushSubscription` rows exist before considering any new pair. Replacing the pair invalidates those browsers' current subscriptions. The public key is a URL-safe base64 P-256 uncompressed point; the private key accepted by `py_vapid` is URL-safe base64 of the raw 32-byte scalar or DER key. Keep it in the private environment only. Never print it or commit it.

To restore a missing existing pair without echoing it to the terminal, edit the actual private source with `sudoedit "$APP_DIR/.env.production"` for the Compose path or `sudoedit "$ENV_FILE"` for the systemd path. Enter the original `WEBPUSH_VAPID_PUBLIC_KEY`, `WEBPUSH_VAPID_PRIVATE_KEY`, and `WEBPUSH_VAPID_SUBJECT` assignments from the approved secret backup. Preserve the file's restricted permissions, then rerun `check_web_push` in the same runtime before restarting or recreating the service. If the original pair cannot be found, stop: rotating keys requires a separate decision and browser resubscription plan.

After deployment, use dedicated authorized test accounts and non-customer test content. Subscribe a designer and the CAD/ED reviewers in Chrome; confirm each subscription belongs to the signed-in user. Submit a test design and verify CAD and ED each receive one in-app item and one real browser push. Have CAD and ED decide separately, then verify the submitting designer receives each decision, can read comments only inside Fabro, and unrelated accounts receive nothing. Repeat with a revised design. Check one notification with the page open and one with it closed. A mocked PushManager or mocked delivery does not prove this check.
