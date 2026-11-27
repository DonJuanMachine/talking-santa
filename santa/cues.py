"""Conversation cues (not safety rules; those live in spec.py): small word checks on what the child just said."""
import re

# "see you" is a goodbye only as one: "see you later/soon/tomorrow", "see ya", or a bare "see you" that opens what the
# child says ("see you Santa!", "ok, see you"). "Can I stay up and see you?" is not one (it got the goodbye's time
# note, and Santa said "Good morning" mid-call; 2026-11-27).
GOODBYE_WORDS = re.compile(
    r"\b(?:bye|goodbye|bye-bye|good ?night|see you (?:later|soon|tomorrow|next time|again)|see ya|have to go|got to go"
    r"|gotta go|need to go|i'm leaving|im leaving|going now|time to go)\b"
    r"|(?:^|[,.!]\s*|\b(?:ok|okay|alright|well)[\s,]+)see you\b", re.I)


def sounds_like_goodbye(text: str) -> bool:
    """The child seems to be saying goodbye (used to add the time-of-day note on that turn)."""
    return GOODBYE_WORDS.search(str(text).replace("’", "'")) is not None


SAD_WORDS = re.compile(
    r"\b(died|dies|dead|death|die|passed away|sad|cry|cried|crying|miss|missed|missing|hurt|hurts|scared|afraid"
    r"|sick|lost|gone|lonely|upset|mad|angry)\b", re.I)


# "I've been good!" is the usual answer to Santa's "how are you?" (the guide's hello), so a plain "been good" needs a
# list context ("this year", "for Santa"); asking ("have I been good?") or "naughty" about the child is enough. A bare
# "naughty" about someone else ("my dog is naughty") is not.
_YEAR = r"(?:this year|all year|this christmas|for (?:you|santa)|enough)"
NICE_LIST_WORDS = re.compile(
    r"\b(?:nice list|naughty list|good list|bad list|naughty or nice|nice or naughty"
    r"|(?:have|was|am) i (?:been )?(?:good|bad|nice|naughty)(?! at)"
    r"|(?:i'?ve|i have|i'?m|i am|i was) (?:been )?(?:not |so |really |very )?naughty"
    r"|(?:i'?ve|i have|i'?m|i am|i was) (?:been )?(?:so |really |very )?(?:good|nice|bad) " + _YEAR + r")\b", re.I)


def talks_nice_list(text: str) -> bool:
    """The child asks or talks about the nice or naughty list, or whether they have been good (santa/guide.py).
    Not "I've been good!" on its own: that is how children answer "how are you?"."""
    return NICE_LIST_WORDS.search(str(text).replace("’", "'")) is not None


def sounds_sad(text: str) -> bool:
    """The child's words sound sad or scared (pauses the gift question; makes Santa gentle for a few turns)."""
    return SAD_WORDS.search(str(text).replace("’", "'")) is not None


# Santa says "Ho ho ho" once, when he answers. After that only when the child sings or tells a joke (SANTA_HO_ONCE).
JOKE_WORDS = re.compile(
    r"\b(knock[\s,]*knock|jokes?|joking|riddles?|why did the|why does the|why do|what do you call|"
    r"what do you get (?:if|when)|what's (?:black|brown|green|red|white|orange) and|how do you make)\b", re.I)
SING_WORDS = re.compile(
    r"\b(sing|sings|singing|sang|song|songs|la la|fa la|jingle bells?|deck the halls|rudolph the red|"
    r"we wish you a merry|twinkle,? twinkle|frosty the|silent night|happy birthday to)\b|[♪♫]", re.I)


def sings_or_jokes(text: str) -> bool:
    """The child is singing (or wants to sing) or telling a joke: the only turns where Santa may laugh "Ho ho ho"."""
    t = str(text).replace("’", "'")
    return JOKE_WORDS.search(t) is not None or SING_WORDS.search(t) is not None


# Topics Santa answers with care (persona.TOPIC_NOTES; Santa's side is guarded by spec.INTENTS). Broad on purpose: a
# wrong guess only adds a careful note to the prompt. Checked in this order; the first that matches wins.
# Not here: "fire" in "fire truck", "alone" without going out ("I'm scared to sleep alone" is a sad turn).
TOPIC_WORDS = [
    ("secret", re.compile(r"\bsecrets?\b|\b(?:don'?t|do not)\s+tell\b|\bpromise\s+not\s+to\s+tell\b", re.I)),
    # Someone hurting someone: "my brother hit me", "I want to punch my sister", "can you hurt them". Not "my tummy
    # hurts", not "fighting bad guys" (pretend play), not "kick the ball".
    ("violence", re.compile(
        r"\b(?:hit|hits|hitting|punch\w*|kick\w*|bit|bite|bites|biting|slap\w*|push|pushed|pushes|pushing|shov\w*"
        r"|hurt|hurts|hurting|beat\s+up|beats\s+up|kill\w*|chok\w*)\s+(?:me|him|her|them|us|you|someone|somebody"
        r"|my\s+(?:brother|sister|friend|mom|mommy|dad|daddy|baby|dog|cat|teacher|cousin)s?)\b", re.I)),
    # Before "meeting": "Can I stay up and see you?" gets the Christmas Eve story, not "Santa is busy".
    ("christmas_eve", re.compile(
        r"\bchristmas\s+eve\b|\b(?:stay|wait)\s+up\b|\b(?:are|will)\s+you\s+(?:be\s+)?coming\b"
        r"|\bdown\s+(?:the|my|our)\s+chimney\b", re.I)),
    ("meeting", re.compile(
        r"\b(?:can|could|will|would)\s+you\s+(?:please\s+)?(?:come|visit|stop\s+by)\b"
        r"|\bcome\s+(?:over|to\s+my|play\s+with\s+me|see\s+me|to\s+see\s+me)\b"
        r"|\b(?:can|could|may)\s+i\s+(?:please\s+)?(?:meet|see|visit)\s+you\b"
        r"|\bmeet\s+you\b|\bsee\s+you\s+for\s+real\b", re.I)),
    ("danger", re.compile(
        r"\b(?:knife|knives|stove|oven|matches|lighter|candles?|fireworks|medicine|pills?|climb\w*)\b"
        r"|\bfire\b(?![\s-]*(?:trucks?|engines?|fighters?|station|dogs?|hydrants?))"
        r"|\b(?:go|going|walk|play)\s+(?:out|outside)\b[^.?!]*\b(?:by\s+myself|alone|on\s+my\s+own)\b", re.I)),
    ("price", re.compile(
        r"\b(?:cost|costs|price|prices|expensive|cheap|money|dollars?|bucks|buy|store|shop|pay)\b|\$\s*\d", re.I)),
]


def topic(text) -> str | None:
    """"secret" | "violence" | "christmas_eve" | "meeting" | "danger" | "price" when the child's words raise one of
    these topics, else None."""
    t = str(text or "").replace("’", "'")
    return next((name for name, rx in TOPIC_WORDS if rx.search(t)), None)
