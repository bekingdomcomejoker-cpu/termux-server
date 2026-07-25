#!/bin/bash
# install_duckai_playwright.sh
# Installs Playwright and Chromium for Duck.ai automation on Termux/Linux

set -e

echo "[+] Installing Playwright..."
pip3 install playwright

echo "[+] Installing Chromium browser binaries..."
python3 -m playwright install chromium

if [ -n "$TERMUX_VERSION" ]; then
    echo "[+] Termux detected. Ensuring dependencies..."
    pkg install -y x11-repo
    pkg install -y chromium
    echo "[+] Set these environment variables:"
    echo "    export CHROME_BINARY=/data/data/com.termux/files/usr/bin/chromium"
    echo "    export CHROMEDRIVER_PATH=/data/data/com.termux/files/usr/bin/chromedriver"
fi

echo "[+] Done. Test with:"
echo "    python3 tools/duck_ai_playwright.py 'Hello world'"