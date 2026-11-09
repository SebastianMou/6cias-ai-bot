"""
Test Gemini from the terminal.

Run it in your project folder (where .env is):
    python test_gemini.py
Try another model without editing anything:
    python test_gemini.py gemini-3.7-flash
"""
import os
import sys
from pathlib import Path


def load_env(path=".env"):
    """Read KEY=VALUE lines from .env (no extra packages needed)."""
    if not Path(path).exists():
        return
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        # .env wins over old values exported in the terminal
        os.environ[key.strip()] = value.strip().strip('"').strip("'")


KEY_SOURCE = "terminal environment" if os.environ.get("GEMINI_API_KEY") else "not found"
load_env()
if Path(".env").exists() and "GEMINI_API_KEY" in Path(".env").read_text(encoding="utf-8"):
    KEY_SOURCE = ".env file"

try:
    import google.genai as genai
except ImportError:
    sys.exit("❌ google-genai is not installed. Run: pip install -U google-genai")

api_key = os.environ.get("GEMINI_API_KEY")
model = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")

print("─" * 50)
print(f"google-genai version : {getattr(genai, '__version__', 'unknown')}")
print(f"Model                : {model!r}")
print(f"API key found        : {'yes (...' + api_key[-4:] + ')' if api_key else 'NO'}")
print(f"Key comes from       : {KEY_SOURCE}")
print("─" * 50)

if not api_key:
    sys.exit("❌ No GEMINI_API_KEY. Put it in .env as: GEMINI_API_KEY=your-key")

TIMEOUT_SECONDS = 60
client = genai.Client(api_key=api_key, http_options={"timeout": TIMEOUT_SECONDS * 1000})  # milliseconds


def ask(question, survey_settings):
    config = None
    if survey_settings:
        # Same settings the survey uses in main.py
        config = {"max_output_tokens": 4096, "thinking_config": {"thinking_level": "low"}}
    response = client.models.generate_content(
        model=model,
        contents=[{"role": "user", "parts": [{"text": question}]}],
        config=config,
    )
    return response.text


# Test 1: plain call. Test 2: the survey's exact settings.
import time

for name, survey_settings in [("Plain call", False), ("Survey settings", True)]:
    print(f"⏳ {name}: asking Gemini (gives up after {TIMEOUT_SECONDS}s)...", flush=True)
    start = time.time()
    try:
        reply = ask("Responde solo con: hola", survey_settings)
        print(f"   answered in {time.time() - start:.1f}s")
        if reply:
            print(f"✅ {name}: {reply.strip()}")
        else:
            print(f"⚠️  {name}: Gemini answered but the text is EMPTY")
    except Exception as e:
        print(f"❌ {name} FAILED after {time.time() - start:.1f}s")
        print(f"   {type(e).__name__}: {e}")

print("─" * 50)
print("Type a question to chat (or 'exit' to quit).")
while True:
    try:
        question = input("\nYou: ").strip()
    except (EOFError, KeyboardInterrupt):
        break
    if question.lower() in ("exit", "quit", "salir"):
        break
    if not question:
        continue
    try:
        print(f"Gemini: {ask(question, survey_settings=True)}")
    except Exception as e:
        print(f"❌ {type(e).__name__}: {e}")