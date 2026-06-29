#!/usr/bin/env bash
# One-shot server setup for JobHunt on Ubuntu 24.04.
# Run as root on the DigitalOcean droplet:
#   curl -fsSL https://raw.githubusercontent.com/tharunkamsala/JobHunt/main/deploy/setup-server.sh | bash -s -- \
#     --domain jobhunt.dev --database-url 'postgresql://...'
set -euo pipefail

DOMAIN=""
DATABASE_URL=""
REPO="https://github.com/tharunkamsala/JobHunt.git"
APP_DIR="/opt/JobHunt"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --domain) DOMAIN="$2"; shift 2 ;;
    --database-url) DATABASE_URL="$2"; shift 2 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

if [[ -z "$DOMAIN" || -z "$DATABASE_URL" ]]; then
  echo "Usage: setup-server.sh --domain YOUR.DOMAIN --database-url 'postgresql://...'"
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get upgrade -y -qq
apt-get install -y -qq git python3 python3-venv python3-pip caddy ufw \
  libnss3 libatk-bridge2.0-0 libdrm2 libxkbcommon0 libgbm1 \
  libasound2t64 libxcomposite1 libxdamage1 libxfixes3

if [[ -d "$APP_DIR/.git" ]]; then
  cd "$APP_DIR" && git pull
else
  git clone "$REPO" "$APP_DIR"
  cd "$APP_DIR"
fi

python3 -m venv .venv
source .venv/bin/activate
pip install -q -r requirements.txt
playwright install chromium
playwright install-deps chromium

cat > .env <<EOF
DATABASE_URL=${DATABASE_URL}
HOST=0.0.0.0
PORT=5055
EOF
chmod 600 .env

python -c "from db import init_db; init_db()"

cat > /etc/caddy/Caddyfile <<EOF
${DOMAIN}, www.${DOMAIN} {
    reverse_proxy localhost:5055
}
EOF
systemctl enable caddy
systemctl restart caddy

cp deploy/job-tracker.service /etc/systemd/system/job-tracker.service
systemctl daemon-reload
systemctl enable job-tracker
systemctl restart job-tracker

ufw allow OpenSSH
ufw allow 80
ufw allow 443
ufw --force enable

echo ""
echo "Done. Site: https://${DOMAIN}"
echo "Logs:  journalctl -u job-tracker -f"
