"""Output guardrails for existing callers: a thin wrapper over santa/spec.py (every rule) and santa/speech.py
(the remove-only prefix filter). SANTA_FILTER=legacy routes sanitize through the old filter in santa/legacy/."""
from . import config, spec, speech
from .spec import (ADDRESS_MSG, FALLBACK, PHONE_MSG, BLOCK_RE as _BLOCK_RE, _SENT_SPLIT,  # noqa: F401
                   looks_private, looks_private_fact, private_kind)

_is_opener = spec.is_opener


def _clean(text: str) -> str:
    return spec.clean(text)


def legacy() -> bool:
    return config.SANTA_FILTER == "legacy"


def sanitize_ex(text: str) -> tuple[str, str | None]:
    """(what the child hears, why it is FALLBACK): None, "empty", "blocklist", "private_output" or "too_long"."""
    if legacy():
        from santa.legacy import safety as old
        return old.sanitize_ex(text)
    return speech.sanitize_ex(text)


def sanitize(text: str) -> str:
    return sanitize_ex(text)[0]


def redact_private(text: str) -> str:
    """Hide addresses/phone numbers from the model (and from memory/transcripts)."""
    kind = private_kind(text)
    if kind is None:
        return text
    return PHONE_MSG if kind == "phone" else ADDRESS_MSG
