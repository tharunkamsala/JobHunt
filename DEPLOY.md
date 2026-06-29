# Deploy JobHunt (7–8 months free)

Repo: https://github.com/tharunkamsala/JobHunt

## Stack

- **App server:** DigitalOcean 4 GB Droplet ($24/mo, covered by GitHub Student $200 credit)
- **Database:** Supabase Postgres (`DATABASE_URL`)
- **Domain:** Name.com `.dev` / `.app` (GitHub Student, year 1 free)
- **HTTPS:** Caddy on the droplet

## 1. Push code to GitHub

```bash
cd job_tracker
git init
git add .
git commit -m "Initial JobHunt app"
git branch -M main
git remote add origin https://github.com/tharunkamsala/JobHunt.git
git push -u origin main
```

`.env` is gitignored — never commit secrets.

## 2. Supabase

1. Create project at https://supabase.com
2. Copy **Database → Connection string → URI**
3. Locally: copy `.env.example` → `.env`, paste `DATABASE_URL`
4. Initialize schema: `python -c "from db import init_db; init_db()"`
5. Migrate local SQLite (optional): `python migrate_to_supabase.py`

On the server, create `/opt/JobHunt/.env` with the same `DATABASE_URL` plus:

```
HOST=0.0.0.0
PORT=5055
```

## 3. DigitalOcean Droplet

1. Claim $200 credit from [GitHub Student Pack](https://education.github.com/pack)
2. Create Droplet: **Ubuntu 24.04**, **4 GB RAM / 2 vCPU**, no backups
3. Note the public IP

## 4. DNS (Name.com)

| Type | Host | Value        |
|------|------|--------------|
| A    | @    | Droplet IP   |
| A    | www  | Droplet IP   |

## 5. Server setup

SSH in, then:

```bash
apt update && apt upgrade -y
apt install -y git python3 python3-venv python3-pip caddy \
  libnss3 libatk-bridge2.0-0 libdrm2 libxkbcommon0 libgbm1 \
  libasound2t64 libxcomposite1 libxdamage1 libxfixes3

cd /opt
git clone https://github.com/tharunkamsala/JobHunt.git
cd JobHunt

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
playwright install-deps chromium

nano .env   # DATABASE_URL, HOST=0.0.0.0, PORT=5055

python -c "from db import init_db; init_db()"
```

## 6. HTTPS (Caddy)

```bash
cp deploy/Caddyfile.example /etc/caddy/Caddyfile
nano /etc/caddy/Caddyfile   # set your domain
systemctl restart caddy && systemctl enable caddy
```

## 7. Run 24/7 (systemd)

```bash
cp deploy/job-tracker.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable job-tracker
systemctl start job-tracker
journalctl -u job-tracker -f
```

## 8. Firewall

```bash
ufw allow OpenSSH
ufw allow 80
ufw allow 443
ufw enable
```

## Cost (7–8 months)

| Item              | Monthly | 8 months |
|-------------------|---------|----------|
| DO 4 GB Droplet   | $24     | $192     |
| Supabase          | $0      | $0       |
| Domain (year 1)   | $0      | $0       |
| **Total**         |         | **$192** (within $200 credit) |
