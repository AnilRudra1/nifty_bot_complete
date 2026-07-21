#!/bin/bash
# ─────────────────────────────────────────────────────────────
# Nifty Bot — One-time EC2 Ubuntu Setup Script
# Run once on fresh Ubuntu EC2: bash setup.sh
# Assumes code is already pulled from GitHub
# ─────────────────────────────────────────────────────────────

set -e
echo "================================================"
echo " Nifty Bot Setup Starting..."
echo "================================================"

# ── Step 1: System update ─────────────────────────────────────
echo "[1/4] Updating system packages..."
sudo apt update -y && sudo apt upgrade -y

# ── Step 2: Install system dependencies ───────────────────────
echo "[2/4] Installing system dependencies..."
sudo apt install -y \
    python3 \
    python3-pip \
    build-essential \
    pkg-config \
    nano \
    htop \
    curl

# ── Step 3: Set timezone to IST ───────────────────────────────
echo "[3/4] Setting timezone to IST..."
sudo timedatectl set-timezone Asia/Kolkata
echo "Timezone: $(date)"

# ── Step 4: Add swap memory ───────────────────────────────────
echo "[4/4] Adding 2GB swap (prevents pip install crash)..."
if [ ! -f /swapfile ]; then
    sudo fallocate -l 2G /swapfile
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile
    sudo swapon /swapfile
    echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
    echo "Swap created"
else
    echo "Swap already exists, skipping"
fi

echo "================================================"
echo " System setup done. Installing Python packages..."
echo "================================================"

# ── Python packages ───────────────────────────────────────────
pip install \
    smartapi-python \
    pyotp \
    pandas \
    numpy \
    requests \
    python-dotenv \
    websocket-client \
    logzero \
    flask \
    flask-socketio \
    eventlet \
    ta \
    schedule \
    python-telegram-bot \
    aiohttp \
    --break-system-packages

echo ""
echo "================================================"
echo " All done! Now just run:"
echo ""
echo "   cd nifty_bot"
echo "   nano .env        (fill your credentials)"
echo "   nohup python3 main.py --mode paper > logs/stdout.log 2>&1 &"
echo "   tail -f logs/stdout.log"
echo "================================================"

