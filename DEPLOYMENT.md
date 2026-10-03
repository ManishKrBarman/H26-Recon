# ReconAI Production Deployment Guide

This guide covers everything required to deploy **ReconAI** to production environments, from single-node Docker Compose on cloud VPS instances (AWS EC2, DigitalOcean, Hetzner, GCP, Azure) to PaaS (Vercel + Render/Railway) and bare-metal Linux servers.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Prerequisites](#2-prerequisites)
3. [Method 1: Docker Compose (Recommended)](#3-method-1-docker-compose-recommended)
4. [Method 2: Production Nginx with SSL (Single Domain)](#4-method-2-production-nginx-with-ssl-single-domain)
5. [Method 3: Cloud PaaS (Vercel + Render / Railway)](#5-method-3-cloud-paas-vercel--render--railway)
6. [Method 4: Direct Bare-Metal / Ubuntu Linux VM (Systemd)](#6-method-4-direct-bare-metal--ubuntu-linux-vm-systemd)
7. [Data & Model Persistence Strategy](#7-data--model-persistence-strategy)
8. [Automated Database Backups](#8-automated-database-backups)
9. [Production Security & Hardening Checklist](#9-production-security--hardening-checklist)
10. [Troubleshooting & Monitoring Cheatsheet](#10-troubleshooting--monitoring-cheatsheet)

---

## 1. Architecture Overview

ReconAI consists of two lightweight, decoupled services:

```
                      Internet / Users
                            │
               ┌────────────┴────────────┐
               │    Nginx Reverse Proxy   │ (Port 80 / 443 with SSL)
               │ (gzip, 100MB body limit) │
               └────────────┬────────────┘
                            │
         ┌──────────────────┴──────────────────┐
         │                                     │
   / (all pages)                           /api/*
         │                                     │
         ▼                                     ▼
 ┌───────────────┐                     ┌───────────────┐
 │ Next.js 14    │                     │ FastAPI       │
 │ Frontend App  │                     │ Backend App   │
 │ (Port 3000)   │                     │ (Port 8000)   │
 └───────────────┘                     └───────┬───────┘
                                               │
                                 ┌─────────────┴─────────────┐
                                 ▼                           ▼
                        ┌────────────────┐          ┌────────────────┐
                        │ SQLite DB      │          │ Saved ML Models│
                        │ data/reconai.db│          │ models/*.joblib│
                        └────────────────┘          └────────────────┘
```

- **Frontend**: Next.js 14 (React 18), compiled to a lightweight standalone container (`~120MB`).
- **Backend**: FastAPI + Uvicorn/Gunicorn running Python 3.11 with scikit-learn, XGBoost, and pandas.
- **Persistence**: SQLite database stored in `./data/reconai.db` and serialized ML models stored in `./models/*.joblib`.
- **Zero-Config Startup**: On first boot, if no database exists, the backend automatically generates initial sample data and runs the reconciliation pipeline so the dashboard is immediately functional.

---

## 2. Prerequisites

### For Containerized Deployments (Methods 1 & 2):
- **Docker Engine** 24.0+ and **Docker Compose** v2+
- Minimum Server Specs:
  - **CPU**: 1 vCPU (2 vCPUs recommended for large ML batch runs)
  - **RAM**: 2 GB RAM (4 GB recommended if processing >100,000 invoices)
  - **Disk**: 15 GB SSD storage
  - **OS**: Ubuntu 22.04 / 24.04 LTS, Debian 12, or AlmaLinux

### For Bare-Metal / Native Deployments (Method 4):
- **Node.js** 20.x LTS & **npm**
- **Python** 3.11+
- **Nginx**

---

## 3. Method 1: Docker Compose (Recommended)

This is the fastest and cleanest way to deploy on any VPS (AWS EC2, DigitalOcean, Hetzner, Linode, etc.).

### Step 1: Clone Repository & Configure Environment

```bash
git clone https://github.com/ManishKrBarman/H26-Recon.git
cd Recon

# Copy environment template
cp .env.example .env
```

Review or modify `.env` as needed:
```ini
PORT=8000
HOST=0.0.0.0
CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000,http://your-server-ip:3000
NEXT_PUBLIC_API_URL=http://your-server-ip:8000
```

### Step 2: Build & Launch Services

```bash
docker compose up -d --build
```

### Step 3: Verify Container Health

```bash
# Check running containers
docker compose ps

# Inspect logs
docker compose logs -f backend
docker compose logs -f frontend
```

### Step 4: Access Application
- **Frontend Dashboard**: `http://<your-server-ip>:3000`
- **Backend API**: `http://<your-server-ip>:8000`
- **Interactive API Docs (Swagger)**: `http://<your-server-ip>:8000/docs`
- **Health Check**: `http://<your-server-ip>:8000/api/health`

---

## 4. Method 2: Production Nginx with SSL (Single Domain)

In enterprise production, you want a single public domain (e.g. `https://recon.yourcompany.com`) serving both the UI and API on ports 80/443 without opening extra ports or exposing raw backend services.

We have included a production configuration in `docker-compose.prod.yml` and `nginx/nginx.conf`.

### Step 1: Obtain a Free Let's Encrypt SSL Certificate

On your host machine, install Certbot and request a certificate:

```bash
sudo apt-get update && sudo apt-get install -y certbot

# Ensure port 80 is temporarily open and not blocked
sudo certbot certonly --standalone -d recon.yourcompany.com
```

### Step 2: Copy or Mount Certificates into `nginx/ssl`

```bash
sudo cp /etc/letsencrypt/live/recon.yourcompany.com/fullchain.pem ./nginx/ssl/
sudo cp /etc/letsencrypt/live/recon.yourcompany.com/privkey.pem ./nginx/ssl/
sudo chmod 600 ./nginx/ssl/privkey.pem
```

### Step 3: Uncomment SSL in `nginx/nginx.conf`

Edit `nginx/nginx.conf` to enable the HTTPS server block:

```nginx
server {
    listen 443 ssl http2;
    server_name recon.yourcompany.com;

    ssl_certificate /etc/nginx/ssl/fullchain.pem;
    ssl_certificate_key /etc/nginx/ssl/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    # File uploads up to 100MB
    client_max_body_size 100M;

    location /api/ {
        proxy_pass http://backend_upstream;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-Proto https;
        proxy_read_timeout 300s;
    }

    location / {
        proxy_pass http://frontend_upstream;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-Proto https;
    }
}

server {
    listen 80;
    server_name recon.yourcompany.com;
    return 301 https://$host$request_uri;
}
```

### Step 4: Launch Production Stack

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

---

## 5. Method 3: Cloud PaaS (Vercel + Render / Railway)

If you prefer managed cloud platforms without administering a Linux server:

### Part A: Deploy Backend on Render / Railway / Fly.io

1. **Deploy Repository**: Create a new Web Service pointing to your GitHub repository.
2. **Root Directory**: Set to `backend` (or repo root).
3. **Environment**: Python 3.
4. **Build Command**:
   ```bash
   pip install -r requirements.txt
   ```
5. **Start Command**:
   ```bash
   uvicorn app.api:app --host 0.0.0.0 --port $PORT
   ```
6. **Persistent Disk (Crucial)**:
   - Attach a Persistent Disk mounted at `/app/data` and `/app/models` (or set `RECON_DATA_DIR=/var/data` and `RECON_MODELS_DIR=/var/models`).
   - This ensures your SQLite reconciliation database and trained ML models are preserved across redeployments.
7. **Environment Variables**:
   - `CORS_ORIGINS`: `https://your-frontend-app.vercel.app`

### Part B: Deploy Frontend on Vercel

1. Import your GitHub repository into Vercel.
2. Set **Root Directory** to `frontend`.
3. Framework preset will automatically detect **Next.js**.
4. In **Environment Variables**, add:
   - `NEXT_PUBLIC_API_URL`: `https://your-backend-service.onrender.com`
5. Click **Deploy**.

---

## 6. Method 4: Direct Bare-Metal / Ubuntu Linux VM (Systemd)

For dedicated Linux servers or on-premise infrastructure without Docker:

### Automated Setup Script

We have provided an automated provisioning script in [setup_vps.sh](file:///m:/hub/Recon/deploy/setup_vps.sh):

```bash
chmod +x deploy/setup_vps.sh
./deploy/setup_vps.sh
```

### Manual Step-by-Step Setup

#### 1. Setup Backend Virtual Environment & Dependencies

```bash
cd /var/www/reconai/backend
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

#### 2. Build Frontend

```bash
cd /var/www/reconai/frontend
npm ci
npm run build
```

#### 3. Install Systemd Services

```bash
sudo cp deploy/reconai-backend.service /etc/systemd/system/
sudo cp deploy/reconai-frontend.service /etc/systemd/system/

sudo systemctl daemon-reload
sudo systemctl enable reconai-backend reconai-frontend
sudo systemctl start reconai-backend reconai-frontend
```

#### 4. Configure Host Nginx

```bash
sudo cp deploy/reconai-nginx.conf /etc/nginx/sites-available/reconai.conf
sudo ln -s /etc/nginx/sites-available/reconai.conf /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl restart nginx
```

---

## 7. Data & Model Persistence Strategy

ReconAI maintains two core state directories that must be persisted across deployments:

| Path | Purpose | Backup Priority |
|------|---------|-----------------|
| `data/reconai.db` | SQLite database storing all reconciliation cases, review decisions, audit logs, and metrics | **Critical** |
| `data/gst_knowledge_base.json` | Core GST compliance rules knowledge base for RAG | **Committed in Git** |
| `models/*.joblib` | Trained Isolation Forest, TF-IDF vectorizer, and statistical reference cache | **High** (Auto-regenerable via `/api/pipeline/run`) |

### Enabling SQLite WAL (Write-Ahead Logging) Mode

For production environments with concurrent writes (analyst reviews and batch uploads), enable SQLite WAL mode:

```bash
sqlite3 data/reconai.db "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;"
```

This improves read/write concurrency and prevents database lock contentions.

---

## 8. Automated Database Backups

Create a daily backup cron job on your host machine to snapshot `reconai.db`:

```bash
sudo nano /etc/cron.daily/reconai-backup
```

Add the following backup script:

```bash
#!/usr/bin/env bash
BACKUP_DIR="/var/backups/reconai"
DATE=$(date +%Y%m%d_%H%M%S)
mkdir -p "$BACKUP_DIR"

# Use sqlite3 online backup API to ensure consistent snapshot without taking system offline
sqlite3 /var/www/reconai/data/reconai.db ".backup '$BACKUP_DIR/reconai_$DATE.db'"

# Archive models directory
tar -czf "$BACKUP_DIR/models_$DATE.tar.gz" -C /var/www/reconai models/

# Keep only last 14 days of backups
find "$BACKUP_DIR" -type f -mtime +14 -delete
```

Make it executable:
```bash
sudo chmod +x /etc/cron.daily/reconai-backup
```

---

## 9. Production Security & Hardening Checklist

- [ ] **Lock Down CORS**: Set `CORS_ORIGINS` to your exact frontend domain rather than wildcard `*`.
- [ ] **Upload Body Limits**: Ensure Nginx has `client_max_body_size 100M;` so users can upload large invoice/ledger CSV files without HTTP 413 errors.
- [ ] **Firewall**: On your cloud VPS, only open ports 22 (SSH), 80 (HTTP), and 443 (HTTPS). Block direct external access to ports 3000 and 8000.
- [ ] **HTTPS / TLS**: Always enforce HTTPS using Let's Encrypt or your enterprise certificate.
- [ ] **Process Supervision**: In Docker, containers have `restart: unless-stopped` and active healthchecks; in bare-metal, systemd handles auto-restart on crashes.
- [ ] **Unprivileged User**: The frontend Dockerfile runs under an unprivileged user (`nextjs:nodejs`, UID 1001) for container security.

---

## 10. Troubleshooting & Monitoring Cheatsheet

### Check Container Status
```bash
docker compose ps
```

### View Live Logs
```bash
# View backend logs (API requests, pipeline execution, errors)
docker compose logs -f backend

# View frontend logs (page renders, client queries)
docker compose logs -f frontend
```

### Test Backend Health Check
```bash
curl -i http://localhost:8000/api/health
# Expected: {"status":"ok","service":"ReconAI API","version":"1.0.0"}
```

### Test Model Status
```bash
curl -i http://localhost:8000/api/models
# Displays loaded Isolation Forest and RAG model artifacts
```

### Force Pipeline Run via CLI
```bash
# Inside docker container or virtual environment:
curl -X POST http://localhost:8000/api/pipeline/run
```

### Restart Services
```bash
docker compose restart
# Or for systemd:
sudo systemctl restart reconai-backend reconai-frontend
```
