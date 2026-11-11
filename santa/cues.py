"""Conversation cues (not safety rules; those live in spec.py): small word checks on what the child just said."""
import re

GOODBYE_WORDS = re.compile(r"\b(bye|goodbye|bye-bye|good ?night|see you|have to go|got to go|gotta go|need to go|"
                           r"i'm leaving|im leaving|going now|time to go)\b", re.I)


def sounds_like_goodbye(text: str) -> bool:
    """The child seems to be saying goodbye (used to add the time-of-day note on that turn)."""
    return GOODBYE_WORDS.search(str(text).replace("’", "'")) is not None


SAD_WORDS = re.compile(
    r"\b(died|dies|dead|death|die|passed away|sad|cry|cried|crying|miss|missed|missing|hurt|hurts|scared|afraid"
    r"|sick|lost|gone|lonely|upset|mad|angry)\b", re.I)


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
