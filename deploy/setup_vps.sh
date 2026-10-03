#!/usr/bin/env bash
# ==============================================================================
# ReconAI VPS Automated Setup Script (Ubuntu 22.04 / 24.04 LTS)
# ==============================================================================
set -euo pipefail

echo "========================================================"
echo " Starting ReconAI Production Setup"
echo "========================================================"

# 1. Update system packages
echo "--> Updating system packages..."
sudo apt-get update && sudo apt-get upgrade -y
sudo apt-get install -y curl git build-essential python3 python3-pip python3-venv nginx certbot python3-certbot-nginx

# 2. Install Node.js 20 LTS (NodeSource)
if ! command -v node &> /dev/null; then
    echo "--> Installing Node.js 20 LTS..."
    curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
    sudo apt-get install -y nodejs
fi
echo "Node version: $(node -v)"
echo "NPM version: $(npm -v)"

# 3. Create target directory if needed
APP_DIR="/var/www/reconai"
if [ ! -d "$APP_DIR" ]; then
    echo "--> Creating app directory at $APP_DIR..."
    sudo mkdir -p "$APP_DIR"
    sudo chown -R "$USER:$USER" "$APP_DIR"
    echo "Please copy/clone your repository into $APP_DIR"
fi

# 4. Setup Python virtual environment
if [ -d "$APP_DIR/backend" ]; then
    echo "--> Setting up Python backend virtual environment..."
    cd "$APP_DIR/backend"
    python3 -m venv .venv
    ./.venv/bin/pip install --upgrade pip
    ./.venv/bin/pip install -r requirements.txt
fi

# 5. Build Frontend
if [ -d "$APP_DIR/frontend" ]; then
    echo "--> Building frontend Next.js application..."
    cd "$APP_DIR/frontend"
    npm ci
    npm run build
fi

# 6. Configure Systemd Services
echo "--> Installing Systemd service units..."
if [ -f "$APP_DIR/deploy/reconai-backend.service" ]; then
    sudo cp "$APP_DIR/deploy/reconai-backend.service" /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable reconai-backend
    sudo systemctl restart reconai-backend
fi

if [ -f "$APP_DIR/deploy/reconai-frontend.service" ]; then
    sudo cp "$APP_DIR/deploy/reconai-frontend.service" /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable reconai-frontend
    sudo systemctl restart reconai-frontend
fi

# 7. Configure Nginx
echo "--> Configuring Nginx reverse proxy..."
if [ -f "$APP_DIR/deploy/reconai-nginx.conf" ]; then
    sudo cp "$APP_DIR/deploy/reconai-nginx.conf" /etc/nginx/sites-available/reconai.conf
    sudo ln -sf /etc/nginx/sites-available/reconai.conf /etc/nginx/sites-enabled/
    sudo rm -f /etc/nginx/sites-enabled/default
    sudo nginx -t && sudo systemctl restart nginx
fi

echo "========================================================"
echo " ReconAI Setup Complete!"
echo " Backend Status:  sudo systemctl status reconai-backend"
echo " Frontend Status: sudo systemctl status reconai-frontend"
echo " Nginx Status:    sudo systemctl status nginx"
echo " To obtain SSL certificate run: sudo certbot --nginx"
echo "========================================================"
