"""santa/legacy/safety.py does `from . import config`: reuse the live config (MAX_SENTENCES, MAX_WORDS)."""
from santa.config import *  # noqa: F401,F403
