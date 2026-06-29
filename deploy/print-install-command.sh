#!/usr/bin/env bash
# Run on your Mac from the job_tracker folder:
#   bash deploy/print-install-command.sh YOUR_DROPLET_IP
set -euo pipefail

IP="${1:-}"
if [[ -z "$IP" ]]; then
  echo "Usage: bash deploy/print-install-command.sh YOUR_DROPLET_IP"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
if [[ ! -f "$SCRIPT_DIR/.env" ]]; then
  echo "Missing .env in $SCRIPT_DIR"
  exit 1
fi

# shellcheck disable=SC1091
source "$SCRIPT_DIR/.env"

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "DATABASE_URL not set in .env"
  exit 1
fi

echo "=============================================="
echo "STEP 1 — SSH into your server (enter password):"
echo "  ssh root@${IP}"
echo ""
echo "STEP 2 — Paste this entire block on the server:"
echo "=============================================="
cat <<EOF
apt update && apt install -y git curl
curl -fsSL https://raw.githubusercontent.com/tharunkamsala/JobHunt/main/deploy/setup-server.sh -o /tmp/setup.sh
chmod +x /tmp/setup.sh
bash /tmp/setup.sh --domain geetha.dev --database-url '${DATABASE_URL}'
EOF
echo "=============================================="
echo "STEP 3 — Open https://geetha.dev (wait ~15 min for DNS)"
echo "Logs on server: journalctl -u job-tracker -f"
