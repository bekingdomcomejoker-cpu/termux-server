import re

with open("api_server.py", "r") as f:
    content = f.read()

# Find and remove the broken proxy block
pattern = r'@app\.post\("/proxy/duckchat"\).*?(?=# ═══════════════════════════════════════════\n#  WebSocket Endpoints)'
match = re.search(pattern, content, re.DOTALL)

if not match:
    print("Proxy not found or already fixed")
    exit(0)

new_proxy = '''@app.post("/proxy/duckchat")
async def proxy_duckchat(request: Request):
    """Proxy Duck.ai chat API — server-side, no CORS issues."""
    data = await request.json()
    prompt = data.get("prompt", "")
    model = data.get("model", "gpt-4o-mini")
    vqd = data.get("vqd")

    import urllib.request
    import urllib.error

    # Fetch VQD token if not provided
    if not vqd:
        try:
            req = urllib.request.Request(
                "https://duckduckgo.com/duckchat/v1/status",
                headers={"x-vqd-accept": "1", "Accept": "*/*", "User-Agent": "Mozilla/5.0"}
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                vqd = resp.headers.get("x-vqd-4") or resp.headers.get("X-Vqd-4")
                if not vqd:
                    raw = resp.read()
                    if raw:
                        body = raw.decode("utf-8", errors="ignore")
                        try:
                            obj = json.loads(body)
                            vqd = obj.get("vqd")
                        except:
                            pass
                if not vqd:
                    return JSONResponse({"error": "No VQD token from DuckDuckGo"}, status_code=500)
        except urllib.error.HTTPError as e:
            return JSONResponse({"error": f"DuckDuckGo HTTP {e.code}: {e.reason}"}, status_code=502)
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
            "User-Agent": "Mozilla/5.0"
        },
        method="POST"
    )

    try:
        loop = asyncio.get_event_loop()
        def do_request():
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read()
                if not raw:
                    return ""
                return raw.decode("utf-8", errors="ignore")

        text = await asyncio.wait_for(loop.run_in_executor(None, do_request), timeout=65)

        response_text = ""
        for line in text.split("\n"):
            line = line.strip()
            if line.startswith("data: "):
                data_line = line[6:]
                if data_line == "[DONE]":
                    break
                try:
                    obj = json.loads(data_line)
                    if "message" in obj:
                        response_text += obj["message"]
                except:
                    pass

        return {"response": response_text, "vqd": vqd}

    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8", errors="ignore")[:500]
        except:
            err_body = ""
        return JSONResponse({"error": f"DuckDuckGo chat HTTP {e.code}: {e.reason}. {err_body}"}, status_code=502)
    except Exception as e:
        return JSONResponse({"error": f"Chat request failed: {e}"}, status_code=500)


'''

content = content[:match.start()] + new_proxy + content[match.end():]

with open("api_server.py", "w") as f:
    f.write(content)

print("✓ Fixed proxy endpoint")
