# Troubleshooting Termux Server Installation

If you encounter `ModuleNotFoundError: No module named 'fastapi'` or errors building `pydantic-core` on Python 3.14+, use this fix ladder.

---

## Fix 1: Termux Native Package (No Compiling)
Termux maintains pre-built packages for common Python libraries. Try this first:

```bash
pkg install python-fastapi python-uvicorn python-websockets -y
```

---

## Fix 2: Set Android API Level + Install Build Tools
If Fix 1 fails, set the environment variable the error asks for, then install the Rust toolchain so `pydantic-core` can compile:

```bash
# Set Android API level (auto-detects from device)
export ANDROID_API_LEVEL=$(getprop ro.build.version.sdk)
echo "API Level: $ANDROID_API_LEVEL"

# Install Rust + build essentials
pkg install rust binutils-is-llvm lld -y

# Re-run pip
pip install --upgrade pip
pip install fastapi uvicorn websockets selenium
```

---

## Fix 3: Use Pre-Built Wheels (Avoid Rust Entirely)
Force pip to use only pre-built wheels. This may use older versions but avoids compilation:

```bash
export ANDROID_API_LEVEL=$(getprop ro.build.version.sdk)
pip install --only-binary :all: fastapi uvicorn websockets selenium
```

---

## Fix 4: Downgrade Python (Nuclear Option)
Python 3.14 is very new. If nothing else works, use a more mature version:

```bash
# Install Python 3.12 if available
pkg install python3.12 -y
python3.12 -m pip install fastapi uvicorn websockets selenium
python3.12 api_server.py
```

---

## Quick Diagnostic
Run this to see your environment details:

```bash
echo "API: $(getprop ro.build.version.sdk)"
echo "Python: $(python3 --version)"
pkg search python-fastapi 2>/dev/null | head -5
```
