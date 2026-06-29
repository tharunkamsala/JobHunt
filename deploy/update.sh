#!/usr/bin/env bash
# Pull latest code on the droplet and restart JobHunt.
# Uses fetch + reset (not git pull) so force-pushed history never blocks deploy.
#
# From your Mac:
#   export DO_PASSWORD='your-root-password'
#   bash deploy/update.sh
set -euo pipefail

DROPLET_IP="${DROPLET_IP:-67.205.130.17}"
APP_DIR="${APP_DIR:-/opt/JobHunt}"

if [[ -z "${DO_PASSWORD:-}" ]]; then
  read -rsp "DigitalOcean root password for ${DROPLET_IP}: " DO_PASSWORD
  echo ""
fi
export SSHPASS="$DO_PASSWORD"

sshpass -e ssh -o StrictHostKeyChecking=accept-new "root@${DROPLET_IP}" bash -s <<REMOTE
set -euo pipefail
cd "${APP_DIR}"
git fetch origin
git reset --hard origin/main
source .venv/bin/activate
python reapply_filters.py
systemctl restart job-tracker
systemctl is-active job-tracker
git log -1 --oneline
REMOTE

echo "Deploy done. Open https://geetha.dev"
