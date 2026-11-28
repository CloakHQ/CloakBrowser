# Control plane deployment

The control plane is a separate service from the browser/CDP runtime. Deploy it with `fly.dashboard.toml` and `Dockerfile.dashboard`; do not point the existing `fly.toml` at this app. The control plane does not launch browsers or expose CDP.

## Local authorized browser lab

The local-only browser lab is deliberately separate from the production image. It accepts only HTTP(S) URLs whose host is `localhost`, `127.0.0.0/8`, or `::1`; browser subresources, redirects, and WebSockets are intercepted too. It does not configure a proxy or expose CDP. Production startup refuses `LOCAL_BROWSER_ENABLED=1`.

On Linux with Docker, build the local image and start it with host networking so a browser inside the container can reach development servers bound to the machine's loopback interface:

```sh
docker build -f Dockerfile.local-browser -t cloakbrowser-local-browser .
docker volume create cloakbrowser-local-data
docker run -d --name cloakbrowser-local-browser --network host \
   --mount source=cloakbrowser-local-data,target=/data \
   -e SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')" \
   -e BOOTSTRAP_ADMIN_USERNAME="operator" \
   -e BOOTSTRAP_ADMIN_PASSWORD="replace-with-a-unique-password-at-least-12-chars" \
   cloakbrowser-local-browser
```

Open `http://127.0.0.1:8014`. Create a regular user from the admin console; that user sees the 本机浏览器 workbench. The signed browser binary and its Linux runtime libraries are installed in this isolated image. Stop the local container when finished with `docker stop cloakbrowser-local-browser`.

## Local development

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dashboard.txt
export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
export BOOTSTRAP_ADMIN_USERNAME="operator"
export BOOTSTRAP_ADMIN_PASSWORD="replace-with-a-unique-password-at-least-12-chars"
export DATABASE_PATH="$PWD/data/saas_accounts.sqlite3"
python control_plane.py
```

Open `http://127.0.0.1:8080`. The first administrator is created only when both bootstrap variables are configured. Keep the database directory private; it contains account records, password hashes, ticket content, and the points ledger.

## Fly.io

1. Choose a unique app name in `fly.dashboard.toml` and set its primary region before deploying. The configured volume and app must use the same region.
2. Create the app and its persistent volume:

   ```sh
   fly apps create YOUR_CONTROL_APP
   fly volumes create control_data --region YOUR_REGION --size 1 --app YOUR_CONTROL_APP
   ```

3. Set production secrets. Use a password manager to choose the initial administrator password:

   ```sh
   fly secrets set \
     SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')" \
     BOOTSTRAP_ADMIN_USERNAME="YOUR_ADMIN_LOGIN" \
     BOOTSTRAP_ADMIN_PASSWORD="YOUR_UNIQUE_PASSWORD" \
     --app YOUR_CONTROL_APP
   ```

4. Deploy only the control-plane config:

   ```sh
   fly deploy --config fly.dashboard.toml --app YOUR_CONTROL_APP
   ```

The production container serves Flask through Gunicorn over Fly's HTTPS proxy, keeps SQLite on its own volume, sets secure HTTP-only SameSite cookies, and drops process privileges after volume ownership is prepared. Use a single machine for this SQLite-backed version; do not scale horizontally. Back up the volume before upgrades. Payment is intentionally manual: a submitted recharge request never credits points until an administrator confirms receipt.

## Implemented scope and limits

User accounts, password changes, role checks, point adjustments, idempotent point debits, manual recharge review, user-owned support conversations, and service settings are persisted in SQLite. There is no payment gateway, public signup flow, remote browser runtime, or API-key issuance in this release. The local browser lab is a development/test utility only and is not part of the production control plane.
