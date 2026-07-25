#!/bin/bash
# install.sh — Termux Server v2.4 "The Pool"

set -e

REPO_DIR="${HOME}/termux-server"
PORT="${PORT:-8000}"
OWNER_SECRET="${OWNER_SECRET:-}"

echo "========================================"
echo "  Termux Server v2.4 — The Pool"
echo "========================================"

if [ -n "$TERMUX_VERSION" ]; then
    PLATFORM="termux"
    echo "[+] Termux detected"
    pkg update -y
    pkg install -y python python-pip sqlite
    if ! command -v chromium &> /dev/null; then
        echo "[!] Chromium not found. Install with: pkg install x11-repo && pkg install chromium"
    fi
else
    PLATFORM="linux"
    echo "[+] Linux detected"
    if command -v apt-get &> /dev/null; then
        sudo apt-get update
        sudo apt-get install -y python3 python3-pip sqlite3
    elif command -v pacman &> /dev/null; then
        sudo pacman -Sy --noconfirm python python-pip sqlite
    fi
fi

mkdir -p "$REPO_DIR/static"
mkdir -p "$REPO_DIR/tools"
mkdir -p "$REPO_DIR/logs"

echo "[+] Installing Python dependencies..."
pip3 install --user fastapi uvicorn websockets selenium 2>/dev/null || pip3 install fastapi uvicorn websockets selenium

cat > "$REPO_DIR/.env" <<EOF
PORT=${PORT}
OWNER_SECRET=${OWNER_SECRET}
TERMUX_HOME=${HOME}
EOF

echo "[+] Environment written to $REPO_DIR/.env"
echo "[+] PLATFORM: $PLATFORM"
echo ""
echo "========================================"
echo "  Next steps:"
echo "========================================"
echo "1. Copy api_server.py, worker_node.py, coordinator.py"
echo "   and the static/ + tools/ directories into $REPO_DIR"
echo ""
echo "2. Set your owner secret:"
echo "   export OWNER_SECRET=your-secret-here"
echo ""
echo "3. Start the server:"
echo "   cd $REPO_DIR && python3 api_server.py"
echo ""
echo "4. (Optional) Start workers:"
echo "   python3 worker_node.py"
echo "   python3 tools/duckai_worker.py"
echo ""
echo "5. Access the pool at http://localhost:${PORT}"
echo ""
echo "   Stealth auth: /pool?join=YOUR_SECRET"
echo "========================================"