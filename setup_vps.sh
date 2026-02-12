#!/usr/bin/env bash
# BunnyTweets – VPS Setup Script (Ubuntu 22.04 / Debian 12)
# Run as root or with sudo.

set -euo pipefail

echo "=== BunnyTweets VPS Setup ==="

# 1. System updates
echo "[1/6] Updating system packages..."
apt-get update && apt-get upgrade -y

# 2. Install Python 3.11+
echo "[2/6] Installing Python..."
apt-get install -y python3 python3-pip python3-venv git curl wget

# 3. Install Google Chrome (for Selenium fallback outside Docker)
echo "[3/6] Installing Google Chrome..."
wget -q https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
apt-get install -y ./google-chrome-stable_current_amd64.deb || true
rm -f google-chrome-stable_current_amd64.deb

# 4. Install Docker & Docker Compose (optional)
echo "[4/6] Installing Docker..."
if ! command -v docker &>/dev/null; then
    curl -fsSL https://get.docker.com | sh
    systemctl enable --now docker
fi
if ! command -v docker-compose &>/dev/null; then
    apt-get install -y docker-compose-plugin || pip3 install docker-compose
fi

# 5. Set timezone
echo "[5/6] Setting timezone to America/New_York..."
timedatectl set-timezone America/New_York || true

# 6. Project setup
echo "[6/6] Setting up BunnyTweets..."
PROJECT_DIR="/opt/bunnytweets"
if [ ! -d "$PROJECT_DIR" ]; then
    mkdir -p "$PROJECT_DIR"
    echo "Created $PROJECT_DIR – copy your project files here."
fi

cd "$PROJECT_DIR"
if [ -f requirements.txt ]; then
    python3 -m venv venv
    source venv/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt
    echo "Python dependencies installed in $PROJECT_DIR/venv"
fi

# Create data dirs
mkdir -p data/downloads data/logs data/database config/credentials

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Next steps:"
echo "  1. Copy config/accounts.yaml.example -> config/accounts.yaml and edit it"
echo "  2. Copy config/settings.yaml.example -> config/settings.yaml and edit it"
echo "  3. Place your Google credentials JSON in config/credentials/"
echo "  4. Make sure Dolphin Anty is running on this machine"
echo "  5. Run:  cd $PROJECT_DIR && source venv/bin/activate && python main.py"
echo "     Or:   cd $PROJECT_DIR && docker compose up -d"
echo ""
