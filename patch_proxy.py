import os

with open("api_server.py", "r") as f:
    content = f.read()

if "proxy/duckchat" in content:
    print("Already patched.")
    exit(0)

insert_marker = "# ═══════════════════════════════════════════\n#  WebSocket Endpoints"

proxy_code = '''
# ═══════════════════════════════════════════
#  Proxy Endpoints
# ═══════════════════════════════════════════

@app.post("/proxy/duckchat")
async def proxy_duckchat(request: Request):
    """Proxy Duck.ai chat API through the server to avoid CORS in browser workers."""
    data = await request.json()
    prompt = data.get("prompt", "")
    model = data.get("model", "gpt-4o-mini")
    vqd = data.get("vqd")

    import urllib.request
    import re as re_mod

    if not vqd:
        try:
            req = urllib.request.Request(
                "https://duckduckgo.com/duckchat/v1/status",
                headers={"x-vqd-accept": "1", "Accept": "*/*", "User-Agent": "Mozilla/5.0"}
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                vqd = resp.headers.get("x-vqd-4") or resp.headers.get("X-Vqd-4")
                if not vqd:
                    body = resp.read().decode("utf-8")
                    m = re_mod.search(r'"vqd"\\s*:\\s*"([^"]+)"', body)
                    if m:
                        vqd = m.group(1)
        except Exception as e:
            return JSONResponse({"error": f"VQD fetch failed: {e}"}, status_code=500)

    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}]
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://duckduckgo.com/duckchat/v1/chat",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-vqd-4": vqd,
            "Accept": "text/event-stream",
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
        },
        method="POST"
    )

    try:
        loop = asyncio.get_event_loop()
        def do_request():
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read().decode("utf-8", errors="ignore")
        
        text = await asyncio.wait_for(loop.run_in_executor(None, do_request), timeout=65)
        
        response_text = ""
        for line in text.split("\\n"):
            line = line.strip()
            if line.startswith("data: "):
                data_line = line[6:]
                if data_line == "[DONE]":
                    break
                try:
                    obj = json.loads(data_line)
                    if "message" in obj:
                        response_text += obj["message"]
                except json.JSONDecodeError:
                    pass
        
        return {"response": response_text, "vqd": vqd}

    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


'''

new_content = content.replace(insert_marker, proxy_code + insert_marker)

with open("api_server.py", "w") as f:
    f.write(new_content)

print("✓ Patched api_server.py with /proxy/duckchat")
