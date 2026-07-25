# AskRain / Google AI Selenium Session Transcript

Archived engineering session notes (Termux + Selenium automation).

**Date:** 2026-07-25

**Note:** Session IDs in AskRain URLs have been redacted before publishing.

---

This archive covers:

1. **AskRain Selenium automation** (`askrain_selenium.py`) — headless Chromium on Termux to drive the Rain support chat for a remote router reset, with keyword state machine + optional `qwen_bridge.ask` fallback.
2. **Setup on Termux** — `mkdir`, `qwen_bridge` stub, `pip install selenium`, Chromium/chromedriver paths under `/data/data/com.termux/files/usr/bin/`.
3. **Google AI Mode Selenium** (`google_ai_selenium.py`) — attempt to click Google “AI Mode” and capture a reply; chromedriver ARM64 / version mismatch issues on Termux Chromium 151.
4. **Driver troubleshooting** — `webdriver-manager` failing with `No such driver version … for None-arm64`; fallback to manual chromedriver; proot Ubuntu vs pure Termux environment confusion.
5. **PCAP / Scapy notes** — HTTPS traffic; SNI extraction via `strings` rather than plaintext HTTP hosts.

## Key paths (Termux)

```text
~/askrain_automation/askrain_selenium.py
~/askrain_automation/google_ai_selenium.py
~/qwen_bridge.py
~/askrain_logs/
~/google_ai_logs/
CHROME=/data/data/com.termux/files/usr/bin/chromium-browser
CHROMEDRIVER=/data/data/com.termux/files/usr/bin/chromedriver
```

## Practical takeaways

- Prefer **Termux-native** Python + Selenium over Ubuntu proot for the Android Chromium binary.
- `webdriver-manager` often cannot supply drivers for Termux’s Chromium builds on **arm64**; ship or pin a matching `chromedriver` binary yourself.
- Shadow DOM (`ai-chat-bot`) scraping is brittle; keep loaders/timeouts defensive.
- Do not commit live support-session query tokens to public repos.

Full raw terminal transcript was large; this file is the curated engineering summary. Original automation scripts can live under `askrain_automation/` if added in a follow-up commit.
