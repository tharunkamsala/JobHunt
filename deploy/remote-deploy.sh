#!/usr/bin/env bash
# Deploy JobHunt to DigitalOcean from your Mac.
# Usage:
#   bash deploy/remote-deploy.sh
# You will be prompted for the DigitalOcean root password.
set -euo pipefail

DROPLET_IP="${DROPLET_IP:-67.205.130.17}"
DOMAIN="${DOMAIN:-geetha.dev}"
SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

if [[ ! -f "$SCRIPT_DIR/.env" ]]; then
  echo "Missing $SCRIPT_DIR/.env"
  exit 1
fi

# shellcheck disable=SC1091
source "$SCRIPT_DIR/.env"
if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "DATABASE_URL not set in .env"
  exit 1
fi

if ! command -v sshpass >/dev/null 2>&1; then
  echo "Installing sshpass..."
  if command -v brew >/dev/null 2>&1; then
    brew install hudochenkov/sshpass/sshpass
  else
    echo "Install sshpass first: brew install hudochenkov/sshpass/sshpass"
    exit 1
  fi
fi

if [[ -z "${DO_PASSWORD:-}" ]]; then
  read -rsp "DigitalOcean root password for ${DROPLET_IP}: " DO_PASSWORD
  echo ""
fi
export SSHPASS="$DO_PASSWORD"

echo "Connecting to ${DROPLET_IP} and installing (5-10 min)..."

REMOTE_SCRIPT=$(cat <<'REMOTE_EOF'
set -euo pipefail
apt-get update -qq
apt-get install -y -qq git curl
curl -fsSL https://raw.githubusercontent.com/tharunkamsala/JobHunt/main/deploy/setup-server.sh -o /tmp/setup.sh
chmod +x /tmp/setup.sh
REMOTE_EOF
)

sshpass -e ssh -o StrictHostKeyChecking=accept-new "root@${DROPLET_IP}" bash -s <<EOF
${REMOTE_SCRIPT}
bash /tmp/setup.sh --domain '${DOMAIN}' --database-url '${DATABASE_URL}'
EOF

echo ""
echo "Deploy finished. Open: https://${DOMAIN}"
echo "If DNS is not ready yet, try: http://${DROPLET_IP}:5055 after a few minutes"
echo "Server logs: ssh root@${DROPLET_IP} 'journalctl -u job-tracker -f'"
