"""Central config. Override any of these with environment variables."""
import os
from pathlib import Path

from santa import local

ROOT = Path(__file__).resolve().parent.parent

# Docker Model Runner exposes an OpenAI-compatible API on the host when
# "Enable host-side TCP support" is on (Docker Desktop > Settings > Model Runner).
BASE_URL = os.getenv("SANTA_BASE_URL", "http://localhost:12434/engines/v1")
MODEL = os.getenv("SANTA_MODEL", "ai/gemma4:e4b")

# Normal requests fail fast (a hung model runner must not silence Santa for minutes)...
REQUEST_TIMEOUT = float(os.getenv("SANTA_TIMEOUT", "15.0"))
# ...but loading a model into memory takes 6-30 s (measured), so warm-up gets a long timeout of its own.
WARMUP_TIMEOUT = float(os.getenv("SANTA_WARMUP_TIMEOUT", "90.0"))
# After a warm-up fails, a reply does not warm up again for this long: it goes straight to its request, which has the
# short REQUEST_TIMEOUT. A hung runner must not cost a second WARMUP_TIMEOUT inside the same reply.
WARMUP_RETRY_SECONDS = float(os.getenv("SANTA_WARMUP_RETRY", str(WARMUP_TIMEOUT)))
# If the last successful model call is older than this, Docker may have unloaded the model: warm up again first.
IDLE_REWARM_SECONDS = float(os.getenv("SANTA_IDLE_REWARM", "300"))

# Personal files live in local/ (gitignored; see santa/local.py).
PROFILES_PATH = Path(os.getenv("SANTA_PROFILES", str(local.profiles_path())))
TRANSCRIPT_DIR = local.LOCAL_DIR / "transcripts"
# Call page only: when each registered child called (santa/calllog.py). Next to the profiles when SANTA_PROFILES is set.
CALLS_PATH = local.calls_path(os.getenv("SANTA_PROFILES"))

# Generation settings tuned for short, calm, kid-friendly replies.
TEMPERATURE = float(os.getenv("SANTA_TEMP", "0.7"))
MAX_TOKENS = int(os.getenv("SANTA_MAX_TOKENS", "120"))

# Hard cap on what Santa says per turn: defined in spec.py (the only place reply rules live), re-exported here.
from .spec import MAX_CONTENT_SENTENCES as MAX_SENTENCES, MAX_WORDS  # noqa: E402

# Output filter: "prefix" (remove-only, streaming; santa/speech.py) or "legacy" (the old repair filter in
# santa/legacy/). Rolling back the filter = SANTA_FILTER=legacy.
SANTA_FILTER = os.getenv("SANTA_FILTER", "prefix")

# History: at most this many recent messages are sent verbatim. When the window would grow past it, the oldest
# HISTORY_TRIM_BLOCK messages are dropped at once (keeping at least 4), so the prompt prefix stays identical for
# several turns and the model server can reuse its prompt cache (measured: tools/probes/out/latency.md).
HISTORY_TURNS = 12
HISTORY_TRIM_BLOCK = 8

# Reasoning models (e.g. Gemma 4) "think" for seconds and eat the token budget.
# Santa needs instant, short replies, so turn thinking off. Non-thinking models ignore this.
EXTRA_BODY = {"chat_template_kwargs": {"enable_thinking": False}}
