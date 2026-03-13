#!/bin/bash
# ═══════════════════════════════════════════════════
#  Supply Chain Control Tower — One-Command Launcher
# ═══════════════════════════════════════════════════
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DB="$SCRIPT_DIR/supplychain.db"

echo ""
echo "⚡ SUPPLY CHAIN CONTROL TOWER"
echo "══════════════════════════════"

# ── 1. Python deps ──
echo ""
echo "[1/4] Installing Python dependencies..."
pip install -r "$SCRIPT_DIR/requirements.txt" --quiet

# ── 2. Seed DB (only if empty or missing) ──
if [ ! -f "$DB" ] || [ "$(sqlite3 "$DB" "SELECT COUNT(*) FROM sqlite_master WHERE type='table';" 2>/dev/null || echo 0)" = "0" ]; then
    echo ""
    echo "[2/4] Seeding database..."
    python "$SCRIPT_DIR/setup_and_seed.py"
else
    echo ""
    echo "[2/4] Database already seeded — skipping (delete supplychain.db to re-seed)"
fi

# ── 3. React install ──
echo ""
echo "[3/4] Installing React dependencies..."
cd "$SCRIPT_DIR" && npm install --silent

# ── 4. Launch both ──
echo ""
echo "[4/4] Starting servers..."
echo "  → API  : http://localhost:8000"
echo "  → App  : http://localhost:3000"
echo ""

# Start API in background
uvicorn api_server:app --host 0.0.0.0 --port 8000 &
API_PID=$!

# Start React
REACT_APP_API_URL=http://localhost:8000/api npm start &
REACT_PID=$!

# Trap Ctrl+C to kill both
trap "kill $API_PID $REACT_PID 2>/dev/null; echo 'Stopped.'; exit" INT TERM

wait
