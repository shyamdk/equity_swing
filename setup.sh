#!/usr/bin/env bash
set -e

echo "=== Equity Swing Trading Setup ==="

# Check Python version
python3 --version || { echo "Python 3 is required"; exit 1; }

# Create virtual environment
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
    echo "Virtual environment created."
else
    echo "Virtual environment already exists, skipping creation."
fi

# Activate and install deps
echo "Installing dependencies..."
source venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt

# Create data directory
mkdir -p data

# Create .env if it doesn't exist
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo ""
    echo "=== ACTION REQUIRED ==="
    echo "Created .env from .env.example."
    echo "Please open .env and fill in your Angel One credentials:"
    echo "  ANGEL_API_KEY     - from https://developer.angelone.in"
    echo "  ANGEL_CLIENT_ID   - your trading account ID"
    echo "  ANGEL_PIN         - your 4-digit PIN"
    echo "  ANGEL_TOTP_SECRET - base32 TOTP secret from authenticator setup"
else
    echo ".env already exists, skipping."
fi

echo ""
echo "=== Setup Complete ==="
echo "Next steps:"
echo "  1. Fill in credentials in .env"
echo "  2. Activate venv: source venv/bin/activate"
echo "  3. Run ingestion: python main.py ingest"
echo "  4. Launch UI:     streamlit run app.py"
