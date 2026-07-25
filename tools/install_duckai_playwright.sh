#!/data/data/com.termux/files/usr/bin/bash
# install_duckai_playwright.sh — one-shot Termux setup for Duck.ai (Playwright + Selenium)
set -euo pipefail

echo "=== Duck.ai automation setup (Termux) ==="

pkg update -y || true
pkg install -y python curl 2>/dev/null || true
if ! command -v chromium-browser >/dev/null 2>&1; then
  pkg install -y x11-repo || true
  pkg install -y chromium || true
fi

pip install -U pip setuptools wheel || true
pip install -U selenium playwright || pip install -U selenium playwright --no-build-isolation || true

export PLAYWRIGHT_BROWSERS_PATH=0
export CHROMIUM_PATH="${CHROMIUM_PATH:-$(command -v chromium-browser || true)}"
export CHROME_BIN="${CHROME_BIN:-$CHROMIUM_PATH}"

mkdir -p "$HOME/duckai_automation" "$HOME/duckai_logs"

BASE="https://raw.githubusercontent.com/bekingdomcomejoker-cpu/termux-server/master/tools"
for f in duck_ai_chat.py duck_ai_playwright.py; do
  curl -fsSL -o "$HOME/duckai_automation/$f" "$BASE/$f" || true
  chmod +x "$HOME/duckai_automation/$f" 2>/dev/null || true
done

echo ""
echo "Chromium: ${CHROME_BIN:-NOT FOUND}"
echo "Scripts:  $HOME/duckai_automation/"
echo "Logs:     $HOME/duckai_logs/"
echo ""
echo "=== Smoke test Playwright ==="
python3 - <<'PY'
import os, sys
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "0"
chrome = os.environ.get("CHROME_BIN") or os.environ.get("CHROMIUM_PATH") or ""
print("chrome path:", chrome or "(empty)")
try:
    from playwright.sync_api import sync_playwright
except Exception as e:
    print("playwright import failed:", e)
    sys.exit(0)
try:
    with sync_playwright() as p:
        kw = dict(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"])
        if chrome and os.path.exists(chrome):
            kw["executable_path"] = chrome
        b = p.chromium.launch(**kw)
        page = b.new_page()
        page.goto("https://duck.ai/", timeout=60000)
        print("title:", page.title())
        b.close()
    print("Playwright smoke: OK")
except Exception as e:
    print("Playwright smoke failed:", e)
    print("You can still use Selenium: duck_ai_chat.py")
PY

echo ""
echo "=== Run examples ==="
echo "  PLAYWRIGHT_BROWSERS_PATH=0 CHROME_BIN=\$(which chromium-browser) \\"
echo "    python3 \$HOME/duckai_automation/duck_ai_playwright.py \"Hello from Termux\""
echo ""
echo "  DUCKAI_MODE=selenium DUCKAI_HEADLESS=1 \\"
echo "    python3 \$HOME/duckai_automation/duck_ai_chat.py \"Hello from Termux\""
echo ""
echo "Done."
