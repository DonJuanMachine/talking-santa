"""Per-child memory stored as plain JSON (text only, no audio)."""
import difflib
import json
import os
import re
import shutil
import sys
from pathlib import Path

from . import config, safety, spec


def _warn(msg: str) -> None:
    print(f"\n!!! WARNING (memory): {msg}\n", file=sys.stderr, flush=True)


def _bak(path: Path) -> Path:
    return path.with_name(path.name + ".bak")


NICKNAME_MAX, FAMILY_MAX, NAME_LEN = 12, 12, 40


def _clean_nicknames(child, raw) -> list[str]:
    """"nicknames": ["Noni", "Lolo"] (a single string is fine too). Strings only, one line, no duplicates."""
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        _warn(f"nicknames of {child!r} were not a list; ignored")
        return []
    out = []
    for n in raw:
        n = " ".join(n.split())[:NAME_LEN] if isinstance(n, str) else ""
        if n and n.casefold() not in (o.casefold() for o in out):
            out.append(n)
    return out[:NICKNAME_MAX]


def _clean_family(child, raw) -> dict:
    """"family": {"mom": "Mom", "grandmother": ["Gammy", "Nana"]} -> {relation: [names]}. Relation -> what the child
    calls that person. Strings only, one line."""
    if not isinstance(raw, dict):
        _warn(f"family of {child!r} was not an object; ignored")
        return {}
    out = {}
    for rel, names in raw.items():
        names = [names] if isinstance(names, str) else names
        if not isinstance(names, list):
            continue
        rel = " ".join(str(rel).split())[:NAME_LEN]
        good = [" ".join(n.split())[:NAME_LEN] for n in names if isinstance(n, str) and n.strip()]
        if rel and good:
            out[rel] = good
    return dict(list(out.items())[:FAMILY_MAX])


def _repair(children) -> dict:
    """Return a dict of dicts, each with a list-of-str "facts". Repairs (with a warning) instead of crashing."""
    if children is None:
        return {}
    if not isinstance(children, dict):
        raise ValueError(f"'children' should be an object, found {type(children).__name__}")
    clean = {}
    for name, p in children.items():
        if isinstance(p, list):                       # hand-edit: "Emma": ["has a cat"]
            _warn(f"profile {name!r} was a list; treating it as that child's facts")
            p = {"facts": p}
        elif not isinstance(p, dict):
            _warn(f"profile {name!r} was not an object; reset to empty")
            p = {}
        facts = p.get("facts", [])
        if not isinstance(facts, list):
            _warn(f"facts of {name!r} were not a list; reset to empty")
            facts = []
        p = dict(p)
        p["facts"] = _dedupe([f for f in facts if isinstance(f, str)])
        if "nicknames" in p:
            p["nicknames"] = _clean_nicknames(name, p["nicknames"])
        if "family" in p:
            p["family"] = _clean_family(name, p["family"])
        clean[str(name)] = p
    return clean


def _read(path: Path) -> dict:
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError("top level is not an object")
    if not isinstance(data.get("children"), dict):   # e.g. {"Emma": {...}} with no "children" wrapper
        raise ValueError("top level has no 'children' object")
    return _repair(data["children"])


def load(path: Path = config.PROFILES_PATH) -> dict:
    path = Path(path)
    if not path.exists():
        return {}
    try:
        return _read(path)
    except (ValueError, OSError) as e:
        _warn(f"{path.name} is unreadable ({e}).")
    try:  # keep the broken file for the adult to inspect; save() will overwrite the original
        shutil.copyfile(path, path.with_name(path.name + ".corrupt"))
    except OSError:
        pass
    bak = _bak(path)
    if bak.exists():
        try:
            profiles = _read(bak)
            _warn(f"Recovered the children's profiles from {bak.name} (the last good save).")
            return profiles
        except (ValueError, OSError) as e:
            _warn(f"{bak.name} is unreadable too ({e}).")
    _warn("Starting with NO remembered children. Re-add them with /add Name.")
    return {}


def save(profiles: dict, path: Path = config.PROFILES_PATH) -> None:
    """Atomic: write a temp file in the same folder, then os.replace. Keeps the previous good file as .bak."""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(json.dumps({"children": profiles}, indent=2) + "\n")
        with open(tmp, "rb") as f:
            os.fsync(f.fileno())
        if path.exists():
            try:
                _read(path)                          # only a valid file becomes the backup
                shutil.copyfile(path, _bak(path))
            except (ValueError, OSError):
                pass
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def remove_backup(path: Path = config.PROFILES_PATH) -> None:
    """Used by /forget: a wipe must not leave the old profiles behind in the backup files."""
    path = Path(path)
    for p in (_bak(path), path.with_name(path.name + ".corrupt")):
        try:
            p.unlink()
        except OSError:
            pass


def remove_transcripts(directory: Path | None = None) -> int:
    """Used by /forget in chat.py: delete the typed-chat transcripts (*.txt, this folder only). Returns how many were
    removed; a missing folder is not an error."""
    directory = Path(directory if directory is not None else config.TRANSCRIPT_DIR)
    removed = 0
    try:
        files = sorted(directory.glob("*.txt"))
    except OSError:
        return 0
    for p in files:
        try:
            if p.is_file() or p.is_symlink():
                p.unlink()
                removed += 1
        except OSError:
            pass
    return removed


def aliases(profiles: dict) -> dict[str, str]:
    """{nickname: child name} for every registered nickname. A nickname that is also a child's real name, or that
    two children share, is dropped (it would be ambiguous)."""
    real = {str(n).casefold() for n in profiles}
    seen: dict[str, str] = {}
    dup = set()
    for name, p in profiles.items():
        for nick in (p.get("nicknames") or []) if isinstance(p, dict) else []:
            k = str(nick).casefold()
            if k in real or (k in seen and seen[k] != name):
                dup.add(k)
            seen[k] = str(name)
    return {k: v for k, v in seen.items() if k not in dup}


def match_name(profiles: dict, text: str) -> str | None:
    """Return a registered child's name if it (or one of their nicknames) appears in text."""
    for name in profiles:
        if re.search(rf"\b{re.escape(name)}\b", text, re.IGNORECASE):
            return name
    for nick, name in aliases(profiles).items():
        if re.search(rf"\b{re.escape(nick)}\b", text, re.IGNORECASE):
            return name
    return None


def _norm(fact: str) -> str:
    return " ".join(fact.lower().split()).strip(" .!?")


FUZZY_MIN_LEN, FUZZY_RATIO = 12, 0.9


def _key(fact: str) -> str:
    """Letters and digits only, lower case: "likes Barbie Dream House" and "Likes Barbie Dreamhouse" match."""
    return re.sub(r"[^a-z0-9]", "", fact.lower())


def same_fact(a: str, b: str) -> bool:
    """True when two facts say the same thing: equal after dropping case, spaces and punctuation, or (for facts of
    at least FUZZY_MIN_LEN characters) very close. Short facts must match exactly: "likes cats" is not "likes cars"."""
    ka, kb = _key(a), _key(b)
    if ka == kb:
        return True
    return (min(len(ka), len(kb)) >= FUZZY_MIN_LEN
            and difflib.SequenceMatcher(None, ka, kb).ratio() >= FUZZY_RATIO)


def _dedupe(facts: list[str]) -> list[str]:
    """Drop later near-duplicates; the first wording stays."""
    out: list[str] = []
    for f in facts:
        if not any(same_fact(f, o) for o in out):
            out.append(f)
    return out


def looks_like_instruction(fact: str) -> bool:
    """Facts return to Santa's prompt on later turns: instruction-like text is never stored (spec.py)."""
    return spec.looks_like_instruction(fact)


def _one_line(text: str) -> str:
    """One line (a newline would add a line to the prompt), with no ( ) [ ]: the facts note is itself in brackets,
    so a fact must not be able to close it and open a note of its own (P4-6)."""
    return " ".join(re.sub(r"[()\[\]]", " ", str(text)).split())


def _refused(fact: str) -> bool:
    """Too long, private, instruction-like, or a claim about what Santa promised, said or gave (P4-6)."""
    return (len(fact) > 100 or safety.looks_private_fact(fact) or looks_like_instruction(fact)
            or spec.looks_like_santa_claim(fact))


def add_fact(profiles: dict, name: str, fact: str) -> bool:
    fact = _one_line(fact).rstrip(".")
    if not fact or _refused(fact):
        return False
    child = profiles.setdefault(name, {"facts": []})
    facts = child.setdefault("facts", [])
    if any(same_fact(fact, f) for f in facts):
        return False
    facts.append(fact)
    del facts[:-20]  # keep the most recent 20
    return True


LAST_CALL = "Last call: "


def set_last_call(profiles: dict, name: str, summary: str) -> bool:
    """Keep ONE "Last call: ..." fact per child (the newest replaces the old), at the end of the list.
    Same checks as add_fact: one line, no brackets, at most 100 characters, nothing private, nothing instruction-like,
    no claim about what Santa promised, said or gave (after "Last call:", Santa is still a sentence's subject)."""
    summary = _one_line(summary).strip(" .\"'")
    fact = LAST_CALL + summary
    if not summary or _refused(fact):
        return False
    child = profiles.setdefault(name, {"facts": []})
    facts = [f for f in child.setdefault("facts", []) if not f.startswith(LAST_CALL)]
    facts.append(fact)
    child["facts"] = facts[-20:]
    return True


def summarize_call(client, model: str, name: str, child_lines: list[str]) -> str:
    """Ask the LLM for one short line about what the child talked about. Only the child's own words are shown to
    it. Fails soft: returns "" on any error."""
    from .persona import SUMMARY_PROMPT

    try:
        child = "\n".join("- " + " ".join(t.split()) for t in child_lines)
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": SUMMARY_PROMPT.format(name=name, child=child)}],
            temperature=0.0,
            max_tokens=80,
            extra_body=config.EXTRA_BODY,
        )
        raw = resp.choices[0].message.content or ""
        decoder = json.JSONDecoder()
        for m in re.finditer(r"\{", raw):
            try:
                obj, _ = decoder.raw_decode(raw[m.start():])
            except ValueError:
                continue
            if isinstance(obj, dict) and isinstance(obj.get("summary"), str):
                return obj["summary"]
        return ""
    except Exception:
        return ""


def _parse_facts(raw: str) -> list[str]:
    """First JSON object in raw that has a "facts" key. "facts" must be a list; strings only."""
    decoder = json.JSONDecoder()
    for m in re.finditer(r"\{", raw):
        try:
            obj, _ = decoder.raw_decode(raw[m.start():])
        except ValueError:
            continue
        if isinstance(obj, dict) and "facts" in obj:
            facts = obj["facts"]
            return [f for f in facts if isinstance(f, str)] if isinstance(facts, list) else []
    return []


def extract_facts(client, model: str, name: str, child_text: str, santa_text: str | None = None) -> list[str]:
    """Ask the LLM for new facts about the child. Fails soft: returns [] on any error.

    Only the child's own words are shown to the model. santa_text is accepted for old callers and ignored,
    so Santa's guesses can never be stored as the child's facts."""
    from .persona import FACTS_PROMPT

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": FACTS_PROMPT.format(name=name, child=child_text)}],
            temperature=0.0,
            max_tokens=120,
            extra_body=config.EXTRA_BODY,
        )
        facts = _parse_facts(resp.choices[0].message.content or "")
        return [f for f in facts if not safety.looks_private_fact(f)][:2]
    except Exception:
        return []
