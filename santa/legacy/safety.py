"""Output guardrails applied to every Santa reply before it is shown or spoken."""
import re

from . import config

# Kid-gift nouns: a promise (below) is only a *gift* promise when one of these follows it.
_GIFTS = ("toy toys present presents gift gifts truck trucks pony ponies puppy puppies kitten kittens dinosaur "
          "dinosaurs rocket rockets bike bikes bicycle doll dolls train trains robot robots ball balls bear teddy "
          "game games lego legos scooter drum guitar tablet phone horse unicorn car cars puzzle puzzles wagon "
          "sled skateboard kite").split()
_PROMISE_GIFT = (r"\b(?:i['’]ll bring you|i will bring you|you['’]ll get|you will get|you['’]ll receive|"
                 r"you will receive|i['’]ll make sure you get|i promise)\b"
                 r"(?:[^\w]+[\w'’-]+){0,5}?[^\w]+(?:" + "|".join(_GIFTS) + r")\b")
# "I am / I'm / my name is X", "made by X", "built by X", "X here!" -- Santa claiming to BE a brand/model.
# A mere mention ("Hello, Gemma!") is fine.
_BRANDS = r"(?:chatgpt|gpt|openai|anthropic|gemma|gemini|google|mistral|ministral|llama|qwen|deepseek|copilot|alexa|siri)"
_BRAND_CLAIM = (r"\b(?:i am|i['’]m|my name is|i['’]m called|they call me)\s+(?:an?\s+|the\s+)?" + _BRANDS + r"\b(?!['’]s)"
                r"|\b(?:made|built|created|trained|developed|programmed)\s+by\s+" + _BRANDS + r"\b"
                r"|(?:^|[.!?]\s+)" + _BRANDS + r"\s+here\b")

# Words/phrases Santa should never say to a toddler. Extend freely.
BLOCKLIST = [
    r"\bkill(?:s|ed|ing)?\b", r"\bdead\b(?!-end)", r"\bdie\b(?!\s+(?:of\s+laughter|laughing))", r"\bdeath\b",
    r"\bblood(?:y)?\b", r"\bguns?\b", r"\bweapon",
    r"\bmonster", r"you(?:'re| are) (?:on|in) the naughty", r"\bnaughty list\b", r"\bcoal\b",
    r"\bas an ai\b", r"\blanguage model\b",
    r"\bI promise\b", r"\bdollars?\b", r"\bamazon\b",
    # promises of specific gifts (see PROMISE in evals/bench.py); "You'll get a big hug!" is fine
    _PROMISE_GIFT,
    # AI / brand identity (flat denials such as "I'm not a computer" are allowed on purpose)
    r"\b(?:i am|i['’]m)\s+(?:an?\s+)?(?:ai|robot|computer|chatbot|language model|artificial)\b",
    _BRAND_CLAIM,
]
_BLOCK_RE = re.compile("|".join(BLOCKLIST), re.IGNORECASE)

_ACTIONS = {"waves", "giggles", "chuckles", "laughs", "winks", "nods", "smiles", "sighs",
            "grins", "claps", "twirls", "bows", "jingles", "gasps", "whispers"}
# Extra words that only ever appear inside a stage direction like *waves happily*.
# Never put negations or ordinary content words here: spans made of anything else are kept.
_STAGE_WORDS = {"jingle", "jingling", "softly", "happily", "gently", "warmly", "loudly", "quietly",
                "merrily", "cheerfully", "excitedly", "brightly", "kindly", "and",
                "laughing", "smiling", "winking", "nodding", "chuckling", "waving", "giggling",
                "twinkles", "beams", "pauses", "hugs"}
_BARE = "giggles|chuckles|laughs|winks|nods|smiles|sighs|waves"

FALLBACK = "Ho ho. Santa is listening. Can you tell your grown-up too?"

# Sentence boundary: after . ! ? but not after Mr. Mrs. Ms. Dr. St.
_SENT_SPLIT = re.compile(r"(?<!\bMr\.)(?<!\bMrs\.)(?<!\bMs\.)(?<!\bDr\.)(?<!\bSt\.)(?<=[.!?])\s+")
# A last sentence that only sets up a reveal ("You know what?") is never left hanging.
_TEASER_RE = re.compile(
    r"^(?:(?:and|but|oh|well)[,\s]+)?(?:do you know what|you know what|guess what|know what"
    r"|(?:do you )?want to (?:hear|know) a (?:secret|surprise)|i have a (?:secret|surprise)(?: for you)?"
    r"|here'?s a secret)(?:,\s*[\w'-]+)?\W*$", re.I)


def _is_direction(inner: str) -> bool:
    words = re.findall(r"[a-z']+", inner.lower())
    return bool(words) and all(w in _ACTIONS or w in _STAGE_WORDS for w in words)


def _emphasis(m: "re.Match") -> str:
    """*x* / **x** / __x__: unwrap to plain text; delete only if it is purely a stage direction."""
    inner = m.group(1)
    return "" if _is_direction(inner) else inner


def _clean(text: str) -> str:
    text = re.sub(r"\*+([^*]+?)\*+", _emphasis, text)       # *x*, **x**, *x y*: keep the words
    text = re.sub(r"__([^_]+?)__", _emphasis, text)         # __x__
    text = re.sub(r"[*_#`>]+", "", text)                     # leftover markdown
    text = re.sub(r"\(([^)]*)\)|\[([^\]]*)\]",               # (giggles) removed; [a surprise] kept
                  lambda m: "" if _is_direction(m.group(1) if m.group(1) is not None else m.group(2))
                  else (m.group(1) if m.group(1) is not None else m.group(2)), text)
    text = re.sub(r"[\U0001F000-\U0001FAFF☀-➿⬀-⯿‍️]", "", text)  # emoji, ZWJ, VS16
    text = re.sub(r"—{2,}", "—", text)
    # "Ho ho giggles!" -> "Ho ho!"  (a bare action word straight after Ho ho)
    text = re.sub(rf"\b(ho(?:[\s,]+ho)*)[\s,]+(?:{_BARE})\b(?=\s*[.!?,;—-]|\s*$)", r"\1", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip()
    # a sentence that is only an action word ("Giggles.") is a stage direction; "Mommy laughs!" is not
    text = " ".join(s for s in _SENT_SPLIT.split(text) if not re.fullmatch(rf"(?:{_BARE})\W*", s, re.I))
    text = re.sub(r"\s+([.!?,;])", r"\1", text)     # " ." -> "."
    return re.sub(r"[,;]+\s*([.!?])", r"\1", text)  # ",." -> "."


# A leading interjection-only opener ("Ho ho ho!", "Ooooh!", "Well, wow!"): at most 3 words, all from this set.
# It does not count toward MAX_SENTENCES (its words still count toward MAX_WORDS).
_INTERJECTION = r"(?:ho(?:ho)*|o+h+|ah+|aha|oh+|well|wow|hey|yay|whee+|hooray|hmm+)"
_OPENER_RE = re.compile(rf"^\W*{_INTERJECTION}(?:[\s,\-]+{_INTERJECTION})*\W*$", re.I)


def _is_opener(sentence: str) -> bool:
    return len(sentence.split()) <= 3 and bool(_OPENER_RE.match(sentence))


def _truncate(text: str) -> str:
    sentences = _SENT_SPLIT.split(text)
    cap = config.MAX_SENTENCES + (1 if len(sentences) > 1 and _is_opener(sentences[0]) else 0)
    kept = sentences[:cap]
    # If the cap would remove the reply's final question, keep it: opener + first content sentence + the question
    # (middle sentences are dropped, nothing is rewritten) -- but only if that still fits in MAX_WORDS.
    last = len(sentences) - 1
    if last >= cap and "?" in sentences[last]:
        lead = sentences[:1] if cap > config.MAX_SENTENCES else []
        content = next((x for x in sentences[len(lead):last] if not _TEASER_RE.match(x.strip())), None)
        if content is not None:
            keep_q = lead + [content, sentences[last]]
            if len(" ".join(keep_q).split()) <= config.MAX_WORDS:
                kept = keep_q
    while len(kept) > 1 and _TEASER_RE.match(kept[-1].strip()):   # don't end on "You know what?"
        kept.pop()
    text = " ".join(kept)
    words = text.split()
    if len(words) > config.MAX_WORDS:
        text = " ".join(words[: config.MAX_WORDS]).rstrip(",;:") + "!"
    return text


def _one_question(text: str) -> str:
    """At most one question per reply. Keep the LAST one; earlier ones become statements.
    Nothing is deleted: 'Mittens, you said? I remember her! Do you like lights?' keeps all three."""
    sentences = _SENT_SPLIT.split(text)
    asking = [i for i, s in enumerate(sentences) if "?" in s]
    for i in asking[:-1]:
        sentences[i] = re.sub(r"\?+", ".", sentences[i])
    return " ".join(sentences)


def check(text: str) -> list[str]:
    """Return a list of problems (empty = fine). Used by the eval harness too."""
    problems = []
    if _BLOCK_RE.search(text):
        problems.append("blocklist")
    if len(text.split()) > config.MAX_WORDS + 5:
        problems.append("too_long")
    if text.count("?") > 1:
        problems.append("multiple_questions")
    return problems


def sanitize_ex(text: str) -> tuple[str, str | None]:
    """Like sanitize(), but also says why FALLBACK was used: None, "empty", "blocklist" or "private_output"."""
    # One-question rule FIRST, so the cap cannot cut the real question and leave an echo question ("Mittens, you
    # said?") as the only one. Then cap, then once more in case the word cap changed anything.
    text = _one_question(_truncate(_one_question(_clean(text))))
    if not text:
        return FALLBACK, "empty"
    if _BLOCK_RE.search(text):
        return FALLBACK, "blocklist"
    if looks_private(text):
        return FALLBACK, "private_output"
    return text, None


def sanitize(text: str) -> str:
    """Clean, truncate, enforce one question, and fall back if the reply trips the blocklist
    or contains an address / phone number."""
    return sanitize_ex(text)[0]


# ----------------------------------------------------------------- private details
_NUMWORDS = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
             "fifteen sixteen seventeen eighteen nineteen twenty thirty forty fifty sixty seventy "
             "eighty ninety hundred").split()
_NW = "(?:" + "|".join(_NUMWORDS) + ")"
_DIGIT_WORDS = "zero one two three four five six seven eight nine".split()
_STREET = (r"(?:street|st|road|rd|avenue|ave|lane|ln|drive|dr|court|ct|way|blvd|boulevard|place|pl|"
           r"circle|cir|terrace|ter|parkway|pkwy|highway|hwy)")
_WORD = r"(?:[^\W\d_]|['’-])+"

# a house number (digits, or 2+ spelled-out number words), 1-2 words, then a street type
_STREET_RE = re.compile(rf"\b(?:\d+|(?:{_NW}[\s-]+)+{_NW}\b)\s+(?:{_WORD}\s+){{1,2}}{_STREET}\b", re.I)
_LIVES_RE = re.compile(
    rf"\b(?:lives?\s+at\s+(?:#\s*)?(?:\d|{_NW}\b)"
    r"|(?:house|home)(?:\s+(?:number|address))?\s+is\s+(?:#\s*)?\d"
    r"|address\s+is\s+(?:#\s*)?\d)", re.I)
_DIGITS_RE = re.compile(r"(?:\d[\s\-.()]*){7,}")
_SPELLED_RE = re.compile(rf"(?:\b(?:{'|'.join(_DIGIT_WORDS)})\b[\s,.\-]*){{4,}}", re.I)
_LASTNAME_RE = re.compile(r"\b(?:last|family)\s+name\b|\bsurname\b", re.I)

ADDRESS_MSG = "(the child said something private about where they live; do not repeat it)"
PHONE_MSG = ("(the child said a phone number or other private number; do not repeat it, "
             "and do not ask where they live)")


def _counting(tokens: list[int]) -> bool:
    """True for 1 2 3 4 ... (or a countdown): kids counting out loud are not giving a phone number."""
    return len(tokens) >= 2 and (
        all(b == a + 1 for a, b in zip(tokens, tokens[1:])) or all(b == a - 1 for a, b in zip(tokens, tokens[1:])))


def private_kind(text: str) -> str | None:
    """"address", "phone" or None. One check used on the child's words, extracted facts and Santa's output."""
    if _STREET_RE.search(text) or _LIVES_RE.search(text):
        return "address"
    for m in _DIGITS_RE.finditer(text):
        if not _counting([int(t) for t in re.findall(r"\d+", m.group())]):
            return "phone"
    for m in _SPELLED_RE.finditer(text):
        if not _counting([_DIGIT_WORDS.index(w.lower()) for w in re.findall(r"[A-Za-z]+", m.group())]):
            return "phone"
    return None


def looks_private(text: str) -> bool:
    return private_kind(text) is not None


def looks_private_fact(text: str) -> bool:
    """For facts about to be stored in a profile: looks_private() plus last names."""
    return looks_private(text) or bool(_LASTNAME_RE.search(text))


def redact_private(text: str) -> str:
    """Hide addresses/phone numbers from the model (and from memory/transcripts)."""
    kind = private_kind(text)
    if kind is None:
        return text
    return PHONE_MSG if kind == "phone" else ADDRESS_MSG
