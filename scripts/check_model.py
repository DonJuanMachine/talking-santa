#!/usr/bin/env python3
"""Phase 0 smoke test: is Docker Model Runner reachable, and how fast is it?

    python scripts/check_model.py [model ...]
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openai import OpenAI  # noqa: E402

from santa import config  # noqa: E402


def main() -> None:
    client = OpenAI(base_url=config.BASE_URL, api_key="not-needed")
    try:
        available = [m.id for m in client.models.list().data]
    except Exception as e:
        sys.exit(f"Cannot reach {config.BASE_URL}\n  {e}\n"
                 "Start Docker Desktop and enable Settings > Model Runner > host-side TCP.")
    print("Models available:", ", ".join(available) or f"none (docker model pull {config.MODEL})")

    for model in sys.argv[1:] or [config.MODEL]:
        t0 = time.time()
        first = None
        text = ""
        stream = client.chat.completions.create(
            model=model, stream=True, max_tokens=60, extra_body=config.EXTRA_BODY,
            messages=[{"role": "system", "content": "You are Santa talking to a 4 year old. Reply in 1-2 short sentences."},
                      {"role": "user", "content": "Hi Santa, I'm Emma!"}])
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                first = first or time.time() - t0
                text += chunk.choices[0].delta.content
        total = time.time() - t0
        print(f"\n{model}: first token {first or 0:.2f}s, total {total:.2f}s\n  {text.strip()}")


if __name__ == "__main__":
    main()
