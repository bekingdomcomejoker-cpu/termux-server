# Conversation Transcript: GPT_API_free (chatanywhere) Setup in Termux

**Date:** ~2026-07  
**Topic:** Cloning GPT_API_free proxy, obtaining free API key via GitHub bind, Python OpenAI client + interactive CLI chat loop on Termux.

**Note:** API keys have been redacted before publishing.

---

## User
Walk on the carpet.

## Assistant
```bash
git clone https://github.com/chatanywhere/GPT_API_free.git
```

## User
Zauber

## Assistant
It looks like you've successfully pasted the command. Now, you can change into the new directory by typing `cd GPT_API_free`.

## User
No, I don't think so.

## Assistant
I see what happened. You tried running that command with a 'bash' prefix, which isn't correct for cloning a repository. Let's try that again by just typing 'git clone' followed by the URL.

## User
Please provide me the exact blocks so I can copy and paste them.

## Assistant
```bash
git clone https://github.com/chatanywhere/GPT_API_free.git
cd GPT_API_free
```

## User
Would you tell me exactly how it is that I run this and you instal it

## Assistant
```bash
git clone https://github.com/chatanywhere/GPT_API_free.git
cd GPT_API_free
```

## User
I confirmed it's downloaded. How do I install it?

## Assistant
GPT_API_free isn't a standalone application you run or install directly—it is a public API proxy service that provides free API keys and endpoints for OpenAI and DeepSeek model requests.

The repository itself contains documentation, usage examples, and client SDK configurations.

### How to Use the Endpoint

Instead of running a local server, you configure your scripts or tools to use their proxy endpoint (`https://api.chatanywhere.tech`) along with the API key provided on their site.

#### Example: Python Usage

Navigate into the cloned folder and install the openai Python SDK:

```bash
cd GPT_API_free
pip install openai
```

Create or edit a script (e.g., `test.py`) with the following setup:

```python
from openai import OpenAI

client = OpenAI(
    api_key="YOUR_FREE_API_KEY",  # Get key from https://api.chatanywhere.tech
    base_url="https://api.chatanywhere.tech/v1"
)

response = client.chat.completions.create(
    model="gpt-3.5-turbo",
    messages=[{"role": "user", "content": "Hello!"}]
)

print(response.choices[0].message.content)
```

#### Example: cURL Command

You can test requests directly from Termux using curl:

```bash
curl https://api.chatanywhere.tech/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_FREE_API_KEY" \
  -d '{
    "model": "gpt-3.5-turbo",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

## User
Okay, but where do I get the API key?

## Assistant
To get a free API key for the GPT_API_free endpoint, follow these steps:

1. **Visit the Registration Page**: Open your browser and go to https://api.chatanywhere.tech.
2. **Log In**: Click on the **"绑定GitHub免费使用"** (Bind GitHub to use for free) link.
3. **Authorize GitHub**: Log in with your GitHub account to authenticate.
4. **Copy Your Key**: Once authorized, the dashboard will display your free API key (it usually starts with `sk-...`).

After you copy it, replace `"YOUR_FREE_API_KEY"` in your script or curl command with the key provided on their dashboard.

## User
Add for me  
`sk-REDACTED`

## Assistant
Here is the complete Python script and cURL command with your API key already added and ready to run in Termux.

### 1. Python Setup

First, install the OpenAI package if you haven't already:

```bash
pip install openai
```

Then create your script (e.g., `main.py`):

```python
from openai import OpenAI

client = OpenAI(
    api_key="sk-REDACTED",
    base_url="https://api.chatanywhere.tech/v1"
)

response = client.chat.completions.create(
    model="gpt-3.5-turbo",
    messages=[{"role": "user", "content": "Hello!"}]
)

print(response.choices[0].message.content)
```

Run it with:

```bash
python main.py
```

### 2. Quick Test via cURL

You can also test it directly in your terminal using this single command:

```bash
curl https://api.chatanywhere.tech/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-REDACTED" \
  -d '{
    "model": "gpt-3.5-turbo",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

## User
[Pasted Python code directly into Bash → syntax errors]  
`python main.py` → file not found  
Then successful `curl` that returned a valid chat completion.

## Assistant
The curl command worked—your API key is valid and the endpoint returned a successful response.

### Why the Python script failed
The syntax errors happened because Python code was pasted directly into the **Bash shell prompt**. Bash tried to run Python commands like `from` and `print()` as terminal programs instead of Python code. When you ran `python main.py`, the file hadn't been created on disk yet.

### How to write and run the Python script

Run this exact block in Termux. It will create `main.py` for you and execute it immediately:

```bash
cat << 'EOF' > main.py
from openai import OpenAI

client = OpenAI(
    api_key="sk-REDACTED",
    base_url="https://api.chatanywhere.tech/v1"
)

response = client.chat.completions.create(
    model="gpt-3.5-turbo",
    messages=[{"role": "user", "content": "Hello!"}]
)

print(response.choices[0].message.content)
EOF

python main.py
```

## User
Can you run a script that doesn't immediately close afterwards it just keeps the CLI open for me?

## Assistant
Here is an interactive chat script that runs continuously in a loop, keeps context of your conversation, and stays open until you explicitly quit or press Ctrl+C.

Copy and paste this entire block directly into your Termux terminal:

```bash
cat << 'EOF' > chat.py
import sys
from openai import OpenAI

client = OpenAI(
    api_key="sk-REDACTED",
    base_url="https://api.chatanywhere.tech/v1"
)

messages = [
    {"role": "system", "content": "You are a helpful AI assistant."}
]

print("\n==================================================")
print("  Interactive CLI Chat Session")
print("  Type 'exit', 'quit', or press Ctrl+C to stop.")
print("==================================================\n")

while True:
    try:
        user_input = input("You: ")
        
        if user_input.strip().lower() in ["exit", "quit", "q"]:
            print("\nExiting chat. Goodbye!\n")
            break
            
        if not user_input.strip():
            continue

        messages.append({"role": "user", "content": user_input})

        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=messages
        )

        reply = response.choices[0].message.content
        print(f"\nAI: {reply}\n")

        messages.append({"role": "assistant", "content": reply})

    except (KeyboardInterrupt, EOFError):
        print("\n\nExiting chat. Goodbye!\n")
        break
    except Exception as e:
        print(f"\nError: {e}\n")
EOF

python chat.py
```

### Features
- **Continuous Loop:** Stays open and prompts you for input (`You:`) after every response.
- **Conversation History:** Remembers previous turns in the chat during the active session.
- **Graceful Exit:** Type `exit`, `quit`, or press Ctrl+C at any time to return to your normal shell.

## User
[Interactive session running successfully]

```
You: hi
AI: Hello! How can I assist you today?
You: what is your name?
AI: I’m called Assistant. How can I help you today?
You: gpt? gemini?
AI: I'm based on OpenAI's GPT architecture. Gemini is a different AI system developed by Google. If you have questions about either, feel free to ask!
```

## Assistant
It looks like your interactive chat session is running smoothly right in your Termux terminal!

You can continue chatting directly with the AI in Termux at that **You:** prompt. Whenever you want to end the session and return to your command line, just type **exit**, **quit**, or press **Ctrl+C**.

## User
Can we create a verbatim markdown of this entire conversation?

---

*End of Transcript (API key redacted for public repo safety)*
