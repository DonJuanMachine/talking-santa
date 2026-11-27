"""The ONE place where reply rules live. Pure functions, no I/O, no config, no model.

Two kinds of rules:
  SAFETY  enforced. A sentence that trips one is never spoken (see santa/speech.py):
          blocklist words, gift promises, AI/brand identity claims, "naughty list", private details.
  SHAPE   measured, never enforced by rewriting: number of questions, sentences, words, markup, stage directions.
          The only shape rule that acts is the hard cap (MAX_WORDS / opener + MAX_CONTENT_SENTENCES), and it only
          ever stops at a sentence boundary.

Text handling is remove-only: clean() deletes markdown, emoji and stage directions. It never adds, reorders or
rewrites words or punctuation.

Sentences are found in two steps, both streaming-safe (see split_raw):
  1. the RAW reply is cut into segments after . ! ? (plus closing quotes/brackets/asterisks) followed by whitespace,
     never after Mr. Mrs. Ms. Dr. St.;
  2. each segment is cleaned on its own and split again (cleaning can remove a stage direction that was glued to
     the punctuation).
So the same sentences come out whether the reply arrives whole or in chunks.
"""
import dataclasses
import functools
import re

MAX_WORDS = 45
MAX_CONTENT_SENTENCES = 3   # plus one leading interjection opener ("Ho ho ho!"), which is free

FALLBACK = "Santa is listening. Can you tell your grown-up too?"

# =============================================================================================== SAFETY rules
# Kid-gift nouns: a promise is only a *gift* promise when one of these follows within six words.
# P1-3: common toddler gifts added (as nouns, plus a "doll" stem and three two-word toys). Kept to toy nouns: a word
# here only counts after a gift verb + a recipient, or in the few fixed shapes below.
_GIFTS = ("toy toys present presents gift gifts truck trucks pony ponies puppy puppies kitten kittens dinosaur "
          "dinosaurs rocket rockets bike bikes bicycle train trains robot robots ball balls bear teddy "
          "game games lego legos scooter drum guitar tablet phone horse unicorn car cars puzzle puzzles wagon "
          "sled skateboard kite bunny bunnies kitty kitties doggy doggies barbie barbies book books crayons "
          "blocks ipad ipads slime").split()
_GIFT_PHRASES = [r"doll\w*", r"fire\s+(?:engine|truck)s?", r"play\s+kitchens?", r"paw\s+patrol"]
_GIFT_ALT = "|".join(_GIFT_PHRASES + _GIFTS)
# A word starts with a letter or digit; ' ’ - only join letters ("teddy-bear", "Santa's"). A run of dashes or
# apostrophes can then be read only one way (as a gap between words), which keeps these patterns fast: an
# overlap between "gap" and "word" characters made matching time explode on text like "I will bring ------x".
_GAP_WORD = r"\w+(?:['’-]\w+)*"
# The same overlap exists between a joiner and a gap in "a-a-a-a": each ' ’ - can be read as joining two letters of ONE
# word or as the gap between TWO words, and the number of readings doubles with every unit (exponential time on
# "I will bring a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-x"). The words below are therefore atomic: a word
# takes every joiner it can, so there is one reading. A gift word may still start right after a joiner ("super-toy"),
# which the second alternative covers; a joined word counts as one word, as before.
_WORD_ATOMIC = r"(?>" + _GAP_WORD + r")"


def _words_then(k: int, sep: str, target: str) -> str:
    """At most k words, each after a gap `sep`, then a gap, then `target` (spliced in as written)."""
    plain = r"(?:" + sep + _WORD_ATOMIC + r"){0," + str(k) + r"}?" + sep + target
    if k < 1:
        return plain
    after_joiner = (r"(?:" + sep + _WORD_ATOMIC + r"){0," + str(k - 1) + r"}?" + sep
                    + r"\w+(?:['’-]\w+)*?['’-]" + target)
    return r"(?:" + plain + r"|" + after_joiner + r")"


_PROMISE_GIFT = (r"\b(?:i['’]ll bring you|i will bring you|you['’]ll get|you will get|you['’]ll receive|"
                 r"you will receive|i['’]ll make sure you get|i promise)\b"
                 + _words_then(5, r"[^\w]+", r"(?:" + _GIFT_ALT + r")\b"))
# D1: a gift promise needs BOTH a specific gift noun (_GIFTS) and a recipient ("you" / "your" as words, not
# you'll / you're). "I'll give you a big hug!", "The elves will make toys all night long!" and "Santa will bring you
# something special!" are spoken; "I'll put a dinosaur under your tree!" is not.
# Every window below stays inside one sentence (never crosses . ! ?), because the speech gate checks the sentences
# said so far joined together ("I'll bring my sleigh! Do you want a truck?" is two harmless sentences).
_GIFT_RX = r"(?:" + _GIFT_ALT + r")\b"
_YOU_RX = r"your?(?![\w'’])"                     # you / your, not you'll / you're / yours / yourself


def _within(n: int, target: str) -> str:
    """Lookahead: `target` starts one of the next n words, in the same sentence."""
    return r"(?=" + _words_then(n - 1, r"[^\w.!?]+", target) + r")"


# (a) a future marker or "tell/ask/have my elves (to)", then a gift verb, then a gift noun AND a recipient within the
# next 8 words, in either order. P1-3: "can/could" after I/we/Santa/elves ("I can bring you a bike!", never "can't"),
# and up to four words between the marker and the verb ("I will definitely, absolutely, for sure bring you a bike!").
_FUTURE = (r"(?:\bwill|['’]ll|\bshall|\bgoing\s+to|\bgonna"
           r"|\b(?:i|we|santa|elves|reindeer)\s+(?:can(?!['’]t)|could)\b)")
_BETWEEN = r"(?:[\s,]+[\w'’-]+){0,4}?"
_GIFT_VERB = r"(?:bring|give|make|send|get|put|leave|wrap|buy|deliver|surprise|drop)"
_ELVES_TO = r"\b(?:tell|ask|have)\s+(?:my|the)\s+elves(?:\s+to)?"
_WILL_VERB = r"(?:" + _FUTURE + _BETWEEN + r"|" + _ELVES_TO + r")[\s,]+" + _GIFT_VERB + r"\b"
# E2: present-progressive and "be sure to / going to" forms ("Santa's bringing you a new train!", "I'll be sure to
# bring you a doll.").
_NOW_VERB = r"(?:\b(?:is|are|am)|['’](?:s|re|m))\s+(?:bringing|giving|sending|getting|leaving)\b"
# P1-3: building / making / wrapping, only with the recipient right after the verb or "for you" ("My elves are building
# you a train right now!"); "The elves are making cat toys right now - do you think ...?" is not a promise.
_MAKING = r"(?:\b(?:is|are|am)|['’](?:s|re|m))\s+(?:building|making|wrapping)\b"
_SURE_VERB = r"\b(?:be\s+sure|going)\s+to\s+(?:bring|give|send|get)\b"
# P1-3: a gift "under the tree" / "in your stocking"
_TREE = r"(?:under|beneath|by|next\s+to)\s+(?:the|your)\s+(?:christmas\s+)?tree\b|in\s+your\s+stocking\b"
_AFFIRM = r"\b(?:yes|yeah|yep|okay|ok|sure|of\s+course|absolutely)\b"
_NOT_FUN = r"(?!\s+(?:so\s+much\s+|lots\s+of\s+|a\s+lot\s+of\s+)?fun\b)"      # "You can have fun with your truck!"


def _recipient_rules(rec: str, for_whom: str, poss: str, direct: str) -> list[str]:
    """The promise shapes that need a recipient. rec: a recipient anywhere in the next 8 words ("you"/"your");
    for_whom: who "for ..." names ("you"); poss: the possessive ("your"); direct: right after the verb ("you"/"your")."""
    return [
        # P1-3 part B: 12 words, not 8 ("I'll tell my elves to make that whoosh, a big, red truck just for you")
        _WILL_VERB + _within(12, _GIFT_RX) + _within(12, rec),
        _NOW_VERB + _within(8, _GIFT_RX) + _within(8, rec),
        _MAKING + r"(?:\s+(?:" + direct + r")" + _within(8, _GIFT_RX) + r"|" + _within(8, _GIFT_RX)
        + _within(8, r"for\s+(?:" + for_whom + r")") + r")",
        _SURE_VERB + _within(8, _GIFT_RX) + _within(8, rec),
        # P1-3 "There will be a puppy under your tree!"
        r"\bthere(?:['’]ll|\s+will|\s+is\s+going\s+to)\s+be\b" + _within(8, _GIFT_RX) + _within(8, rec),
        # P1-3 "Your new bike will be under the tree!"
        r"\b" + poss + r"(?:\s+[\w'’-]+){0,3}?\s+" + _GIFT_RX + r"\s+(?:will|['’]ll|is\s+going\s+to)\s+be\b"
        r"(?=[^.!?]*?(?:" + _TREE + r"))",
        # P1-3 two sentences: an affirmative, then a gift for you ("Yes! A pony for you!")
        _AFFIRM + r"[\s,!.]+(?:an?\s+|the\s+|some\s+|one\s+)?(?:[\w'’-]+\s+){0,3}?" + _GIFT_RX
        + r"\s+(?:just\s+)?for\s+" + for_whom,
    ]


def _subject_rules(subj_will: str) -> list[str]:
    """P1-3: the recipient is the subject ("You can have the truck!", "You're gonna get a bike!")."""
    return [subj_will + r"\s+(?:(?:get|receive|find)\b" + _within(8, _GIFT_RX)
            + r"|have\b" + _NOT_FUN + _within(4, _GIFT_RX) + r")"]


# The _PROMISE_GIFT phrases ("you'll get", "you will receive", ...) already name the recipient: a gift noun within
# 8 words in the same sentence is enough (so "You will get one great big shiny red new truck!" stays blocked).
_YOU_GET = (r"\b(?:i['’]ll bring you|i will bring you|you['’]ll get|you will get|you['’]ll receive|"
            r"you will receive|i['’]ll make sure you get)\b" + _within(8, _GIFT_RX))
_YOU_WILL = (r"\byou(?:['’]ll|\s+will|\s+can(?!['’]t)|['’]re\s+(?:going\s+to|gonna)|\s+are\s+(?:going\s+to|gonna))")
_PROMISE_MORE = _recipient_rules(_YOU_RX, r"you(?![\w'’])", r"your", _YOU_RX) + _subject_rules(_YOU_WILL) + [
    _YOU_GET,
    r"\byou(?:['’]re|\s+are)\s+(?:getting|going\s+to\s+get)\b" + _within(6, _GIFT_RX),   # (b) "you're getting a bike"
    r"\bpromises?\s+you(?![\w'’])",                                     # (d) "Santa promises you a pony"
    # (c) "wish(es) ... come true" only with a gift noun in the same sentence (after "wish", or before it)
    r"\bwish(?:es)?\b(?=[^.!?]*?\bcome\s+true\b)(?=[^.!?]*?\b" + _GIFT_RX + r")",
    r"\b" + _GIFT_RX + r"[^.!?]*?\bwish(?:es)?\b[^.!?]*?\bcome\s+true\b",
]


@functools.lru_cache(maxsize=64)
def _name_promise_re(names: tuple[str, ...]) -> "re.Pattern | None":
    """P1-3: the active child's name (and nicknames), from the caller, where "you" would be: "I'll bring Emma a bike!",
    "a bike for Emma", "Emma's tree", "Emma will get a bike!", "Emma's getting a bike!". A name alone (a vocative such
    as "Emma, the elves will make toys!") is not a recipient."""
    alts = sorted({n.strip() for n in names if isinstance(n, str) and re.search(r"[^\W\d_]", n)}, key=len, reverse=True)
    if not alts:
        return None
    nm = r"(?<![\w'’-])(?:" + "|".join(re.escape(a) for a in alts) + r")"
    end = r"(?![\w'’-])"
    pats = _recipient_rules(r"(?:for|to)\s+" + nm + end + r"|" + nm + r"['’]s\b", nm + end, nm + r"['’]s",
                            nm + end + r"|" + nm + r"['’]s\b")
    pats += _subject_rules(nm + r"(?:['’]ll|\s+will|\s+can(?!['’]t)|\s+is\s+(?:going\s+to|gonna)|['’]s\s+(?:going\s+to|gonna))")
    pats += [nm + r"(?:['’]s|\s+is)\s+getting\b" + _within(6, _GIFT_RX),
             r"(?:" + _WILL_VERB + r"|" + _NOW_VERB + r")\s+" + nm + end + _within(8, _GIFT_RX)]
    return re.compile("|".join(pats), re.IGNORECASE)


# Santa claiming to BE a brand/model ("I am / I'm / my name is X", "made by X", "X here!"). A mention is fine.
_BRANDS = r"(?:chatgpt|gpt|openai|anthropic|gemma|gemini|google|mistral|ministral|llama|qwen|deepseek|copilot|alexa|siri)"
_BRAND_CLAIM = (r"\b(?:i am|i['’]m|my name is|i['’]m called|they call me)\s+(?:an?\s+|the\s+)?" + _BRANDS + r"\b(?!['’]s)"
                r"|\b(?:made|built|created|trained|developed|programmed)\s+by\s+" + _BRANDS + r"\b"
                r"|(?:^|[.!?]\s+)" + _BRANDS + r"\s+here\b")

# (reason, patterns). Order matters only for which reason is reported first.
SAFETY_RULES = [
    ("naughty_list", [r"you(?:'re|’re| are) (?:on|in) the naughty", r"\bnaughty list\b"]),
    ("promise", [r"\bI promise\b", _PROMISE_GIFT] + _PROMISE_MORE),
    ("ai_identity", [r"\bas an ai\b", r"\blanguage model\b",
                     # flat denials such as "I'm not a computer" are allowed on purpose
                     r"\b(?:i am|i['’]m)\s+(?:an?\s+)?(?:ai|robot|computer|chatbot|language model|artificial)\b",
                     r"\b(?:i am|i['’]m)\s+(?:just|only)\s+an?\s+(?:computer|program|machine|robot)\b",
                     _BRAND_CLAIM]),
]
_SAFETY_RE = [(name, re.compile("|".join(pats), re.IGNORECASE)) for name, pats in SAFETY_RULES]


def _any_of(pats: tuple[str, ...]) -> "re.Pattern | None":
    return re.compile("|".join(pats), re.IGNORECASE) if pats else None


# Intent rules: Santa suggesting something unsafe, judged by the shape of the sentence, not by one word. Each has
# exceptions ("unless") read in the SAME sentence only: "I'll come to your house on Christmas Eve" is the Santa story,
# "I'll come to your party" is a meeting. When one stops a reply, Santa says that topic's line (persona.TOPIC_LINES)
# instead of FALLBACK. Live baseline: tools/probes/topics_probe.py. Cases: tests/spec/test_blocklist_context.py.
@dataclasses.dataclass(frozen=True)
class Intent:
    name: str                     # the safety reason ("secret", "meeting", "danger", "price")
    shapes: tuple[str, ...]       # what Santa must not say (regexes)
    unless: tuple[str, ...] = ()  # fine after all when the same sentence holds one of these (regexes)


_SANTA_WILL = (r"\b(?:i['’]ll|i\s+will|i\s+can|i\s+could|i\s+am\s+going\s+to|i['’]m\s+going\s+to|i['’]m\s+gonna"
               r"|santa\s+will|santa['’]ll|santa\s+can|we['’]ll|we\s+will|we\s+can)")
_GROWN_UP = (r"\b(?:grown-?ups?|adults?|mommy|mom|mama|mum|daddy|dad|papa|parents?|grandma|grandpa|granny|nana"
             r"|teachers?|babysitter)\b")
_NEGATION = r"\b(?:never|don['’]?t|do\s+not|not|no|can['’]t|cannot|shouldn['’]t|mustn['’]t)\b"

INTENTS = [
    # Santa promising to keep a secret, or asking the child to keep one from their grown-ups. A secret that is only a
    # word ("The elves' toys are a secret!", "A secret? How exciting!") is fine.
    Intent("secret", (
        r"\bour\s+(?:little\s+|special\s+|big\s+|own\s+)?secrets?\b",
        r"\bjust\s+between\s+(?:us|you\s+and\s+me|me\s+and\s+you|the\s+two\s+of\s+us)\b",
        r"\b(?:don['’]?t|do\s+not)\s+tell\s+(?:your\s+|my\s+|the\s+)?(?:mom|mommy|mama|mum|dad|daddy|papa|parents?"
        r"|grown-?ups?|anyone|anybody|teachers?|grandma|grandpa|family|them|her|him)\b",
        r"\b(?:i|santa|we)\s+(?:won['’]t|will\s+not|wouldn['’]t|would\s+never|will\s+never|never)\s+tell\s+"
        r"(?:anyone|anybody|a\s+soul|your\s+\w+|mom|mommy|dad|daddy|them|her|him)\b",
        r"\b(?:i|santa|we)\s+(?:won['’]t|will\s+not|wouldn['’]t)\s+tell\s*(?:[,.!…]|$)",
        r"\b(?:i|santa|we)(?:['’]ll|\s+will|\s+can|\s+always|\s+promise\s+to)?\s+keeps?\s+(?:it|this|that|your|a|all"
        r"|the|any)\b[^.!?]{0,30}?\bsecrets?\b",
        r"(?:^|(?<=[.!?…]\s)|\blet['’]s\s+|\byou\s+(?:should|must|can|have\s+to|need\s+to)\s+|\bcan\s+you\s+)"
        r"keep\s+(?:it|this|that)\s+(?:a\s+|our\s+)?secret\b",
        r"\bpromise\s+(?:me\s+)?(?:not\s+to|you\s+won['’]t|you\s+will\s+not|to\s+never)\s+tell\b",
        r"\b(?:can|will)\s+you\s+keep\s+(?:a|this|my|our)\s+secret\b",
    ), unless=(r"\byour\s+(?:address|phone|number|password|last\s+name|full\s+name)\b", r"\bstrangers?\b")),
    # Santa coming to a real place: only the Christmas Eve story (after the child is asleep) is fine.
    Intent("meeting", (
        _SANTA_WILL + r"\s+(?:come|visit|stop\s+by|drop\s+by|swing\s+by|pop\s+by|fly)\s+(?:over\s+|down\s+|by\s+)?"
        r"(?:to\s+|at\s+)?(?:you\b|your\b|see\s+you\b|play\b|and\s+(?:see|play)\b)",
    ), unless=(r"\bchristmas\s+eve\b", r"\basleep\b", r"\bsleep(?:ing|s)?\b", r"\bin\s+bed\b", r"\bblink\b",
               r"\bchimney\b")),
    # The child seeing or meeting Santa, getting together, being alone, or where the child is. Never fine.
    Intent("meeting", (
        r"(?<!\bto\s)\bmeet\s+(?:me|up)\b",                     # "Meet me at the park"; not "you want to meet me"
        r"\blet['’]s\s+(?:meet|get\s+together|play\s+together|see\s+each\s+other)\b",
        r"\bwe\s+(?:can|could|should|will)\s+(?:meet|get\s+together|play\s+together|see\s+each\s+other)\b",
        r"\bcome\s+(?:and\s+)?(?:find|meet|visit)\s+me\b",
        r"\byou(?:['’]ll|\s+will|\s+can|\s+could|\s+might|\s+may)\s+(?:get\s+to\s+)?(?:see|meet|catch|spot)\s+"
        r"(?:me|santa)\b",
        r"\b(?:i['’]ll|i\s+will|we['’]ll|we\s+will)\s+see\s+(?:you|each\s+other)\s+(?:at|on|in|tomorrow|tonight|there"
        r"|then)\b",
        r"\b(?:stay|wait)\s+up\s+(?:late\s+)?(?:and|to)\s+(?:see|watch|meet|catch|spot)\b",
        r"\bwait\s+up\s+for\s+(?:me|santa)\b",
        r"\bjust\s+(?:you\s+and\s+me|the\s+two\s+of\s+us)\b",
        r"\bare\s+you\s+(?:all\s+)?(?:alone|by\s+yourself|home\s+alone)\b",
        r"\bis\s+any(?:one|body)\s+(?:else\s+)?(?:home|there|with\s+you)\b",
        r"\bwhere\s+(?:do\s+you\s+live|is\s+your\s+(?:house|home|school))\b",
        r"\bwhat\s+(?:school|street|town|city)\s+(?:do|are)\s+you\b",
        r"\bwhat(?:['’]s|\s+is)\s+your\s+(?:address|school|street)\b",
    )),
    # Santa telling the child to do something that can hurt. Fine with a grown-up, as a warning ("Never light
    # matches!"), or about the North Pole ("Mrs. Claus lights the candles").
    Intent("danger", (
        r"\b(?:light|lighting|strike|striking)\s+(?:a\s+|the\s+|some\s+|your\s+)?(?:match(?:es)?|candles?|fires?"
        r"|lighters?|fireworks?|sparklers?)\b",
        r"\bplay(?:ing)?\s+with\s+(?:the\s+|a\s+|some\s+)?(?:matches|fire|lighters?|knives|knife)\b",
        r"\b(?:turn|turning|switch|switching)\s+on\s+the\s+(?:stove|oven|burners?|fireplace|gas)\b",
        r"\btouch(?:ing)?\s+the\s+(?:stove|oven|fire|outlets?|plugs?|heater)\b",
        r"\b(?:use|using|grab|grabbing|get|take|hold|holding)\s+(?:a\s+|the\s+|your\s+|some\s+)?(?:sharp\s+|big\s+)?"
        r"(?:knife|knives|lighters?|matches)\b",
        r"\b(?:take|taking|eat|eating|swallow|swallowing)\s+(?:some\s+|the\s+|a\s+|your\s+)?(?:medicine|pills?"
        r"|vitamins?)\b",
        r"\bclimb(?:ing|s)?\s+(?:up\s+)?(?:on\s+)?(?:the\s+|a\s+|that\s+)?(?:big\s+|tall\s+)?(?:tree|roof|fence"
        r"|counter|shelf|shelves|bookcase|ladder|cabinet|window)\b",
        r"\b(?:go|going|walk|walking|play|playing)\s+(?:out|outside|to\s+the\s+park|in\s+the\s+street)\s+(?:all\s+)?"
        r"(?:by\s+yourself|alone|on\s+your\s+own)\b",
        r"\bopen\s+the\s+(?:front\s+)?door\b",
        r"\bcross\s+the\s+(?:street|road)\b",
    ), unless=(_GROWN_UP, _NEGATION, r"\b(?:claus|elves|elf|reindeer|rudolph)\b")),
    # Prices, money amounts, buying and stores (persona: "Never mention prices, brands, or stores"). Brands are not
    # here: "Lego" and "Barbie" are gifts children ask for by name.
    # A price word in a negated sentence is Santa deflecting: "I don't talk about prices", "made with love, not with
    # prices!" (live, 2026-11-27: both were stopped). An amount in it is still caught below.
    Intent("price", (
        r"\bcosts?\b(?!\s+(?:nothing|no\s+money))",
        r"\bprices?\b|\bpriced\b|\bexpensive\b|\bcheap\b|\bon\s+sale\b|\bafford\b",
    ), unless=(_NEGATION,)),
    # Amounts, buying and stores: never fine, refusal or not ("I don't talk about prices, but it's $500").
    Intent("price", (
        r"\$\s*\d",
        r"\b\d[\d,.]*\s*(?:dollars?|bucks|cents)\b",
        r"\b(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|twenty|thirty|forty|fifty"
        r"|sixty|seventy|eighty|ninety|hundred|thousand|million)\s+(?:dollars?|bucks|cents)\b",
        r"\b(?:you|mommy|mom|daddy|dad|your\s+(?:grown-?ups?|parents?|family)|we|they|grown-?ups?)"
        r"(?:\s+(?:can|could|should|might|will)|['’]ll)\s+buy\b",
        r"\bask\s+(?:your\s+)?\w+\s+to\s+buy\b",
        r"\bgo\s+(?:and\s+)?buy\b",
        r"\bbuy\s+(?:it|one|them|that|this|some)\s+(?:at|from|on|online)\b",
        r"\b(?:walmart|costco|best\s+buy|ebay|etsy|kmart|target\.com|toys\s*['’\"]?\s*r\s*['’\"]?\s*us|the\s+mall"
        r"|toy\s+store|the\s+store)\b",
        r"\b(?:at|from|to)\s+target\b",
    )),
]
_INTENTS_RE = [(i.name, re.compile("|".join(i.shapes), re.IGNORECASE), _any_of(i.unless)) for i in INTENTS]
# A sentence ends at . ! ? … but not after Mr. Mrs. Ms. Dr. St. (as split_raw).
_SENT_END_RX = re.compile(r"(?<!\bMrs)(?<!\bMr)(?<!\bMs)(?<!\bDr)(?<!\bSt)[.!?…]", re.IGNORECASE)


def _sentence_at(text: str, start: int, end: int) -> str:
    """The sentence of `text` that holds text[start:end]."""
    begin = 0
    for m in _SENT_END_RX.finditer(text, 0, start):
        begin = m.end()
    m = _SENT_END_RX.search(text, end)
    return text[begin:m.end() if m else len(text)]


def intent_reason(text: str) -> str | None:
    """The first intent rule `text` breaks ("secret" | "meeting" | "danger" | "price"), or None."""
    for name, rx, unless in _INTENTS_RE:
        for m in rx.finditer(text):
            if unless is None or not unless.search(_sentence_at(text, m.start(), m.end())):
                return name
    return None


# The "blocklist" rule: words Santa never says (violence, death, fear, money, a store), each with the harmless
# things that only share the word ("gun" in "water gun", "monster" in "monster truck"). A word is blocked unless
# every place it appears lies inside one of its safe phrases, so "A water gun is fun, but a real gun is not" is
# still blocked. A safe phrase names a harmless thing (a toy, a food, a place, an idiom). An if_asked phrase is
# fine only when the child's words this turn hold it too: Santa never brings it up, but answers when asked. A grief
# word is fine only next to who the child just said died: "my dog died" lets Santa say "your dog is dead", never
# "everyone will be dead someday". Cases: tests/spec/test_blocklist_context.py.
@dataclasses.dataclass(frozen=True)
class Term:
    word: str                      # the blocked word (a regex)
    safe: tuple[str, ...] = ()     # phrases that contain the word and are always fine to say (regexes)
    if_asked: tuple[str, ...] = ()   # phrases fine only when the child said one of them this turn (regexes)
    grief: bool = False            # fine next to who the child said died this turn (_grief_spans)


# Who the child says died: "my dog died" -> "dog", "Mittens passed away" -> "Mittens", "my grandpa is dead" ->
# "grandpa". A pronoun is not a who ("she died": Santa may say "died", which is never blocked).
_LOSS_RX = re.compile(r"\b([^\W\d_][\w'’-]*)\s+(?:has\s+)?(?:died|passed\s+away|(?:is|was)\s+dead|(?:got|was)\s+killed"
                      r"|went\s+to\s+heaven|is\s+in\s+heaven)\b", re.IGNORECASE)
_NOT_WHO = {"he", "she", "it", "they", "who", "that", "this", "one", "someone", "somebody", "everyone", "everybody"}


@functools.lru_cache(maxsize=64)
def _grief_rx(who: str) -> "re.Pattern":
    """Santa's words about that one loss: "your dog is dead", "Grandma's death", "the death of your goldfish"."""
    w = re.escape(who)
    return re.compile(rf"\b{w}\s+(?:is|was)\s+(?:\w+\s+)?dead\b|\b{w}['’]s\s+death\b"
                      rf"|\bdeath\s+of\s+(?:your\s+|my\s+|our\s+|the\s+)?(?:\w+\s+)?{w}\b", re.IGNORECASE)


_MY_BEFORE = re.compile(r"\b(?:my|our)\s+(?:[\w'’-]+\s+)?$", re.IGNORECASE)


def loss_of(child_said) -> tuple[str, str] | None:
    """(the child's words about the loss, who in Santa's words) for the first loss in `child_said`, else None:
    "my dog died" -> ("my dog died", "your dog"); "Mittens passed away" -> ("Mittens passed away", "Mittens").
    For the grief note (persona.grief_note); the same reading as the grief words above."""
    text = str(child_said or "")
    for m in _LOSS_RX.finditer(text):
        who = m.group(1)
        if who.lower() in _NOT_WHO:
            continue
        my = _MY_BEFORE.search(text[max(0, m.start() - 40):m.start()])
        if my is None:
            return text[m.start():m.end()], who
        your = re.sub(r"^(?:my|our)\b", "your", my.group(), flags=re.IGNORECASE)   # "my grandma's " -> "your grandma's "
        return text[m.start() - len(my.group()):m.end()], your + who
    return None


def _grief_spans(text: str, child_said: str) -> list[tuple[int, int]]:
    spans = []
    for m in _LOSS_RX.finditer(child_said):
        if m.group(1).lower() not in _NOT_WHO:
            spans += [x.span() for x in _grief_rx(m.group(1).lower()).finditer(text)]
    return spans


# Either name of the holiday: the child may ask with one and Santa answer with the other.
_DAY_OF_THE_DEAD = r"\bday\s+of\s+the\s+dead\b|\bd[ií]a\s+de\s+(?:los\s+)?muertos\b"

BLOCK_TERMS = [
    # Named water/foam/craft toys only. A bare "toy gun" stays blocked (it can be a replica).
    Term(r"\bguns?\b", (r"\b(?:water|squirt|nerf|bubble|foam|glue)[\s-]+guns?\b",)),
    # "monster truck(s)" and "Monster Jam" (the truck show) are toys, not monsters (2026-11-25: a child who likes
    # them got FALLBACK on every reply).
    Term(r"\bmonster", (r"\bmonsters?[\s-]*(?:trucks?|jam)\b", r"\bcookie[\s-]+monster\b", r"\bmonsters,?\s+inc\b")),
    # "a dead tree" stays blocked; "your goldfish is dead" only after the child said their goldfish died.
    Term(r"\bdead\b", (r"\bdead[\s-]+(?:ends?|batter(?:y|ies))\b",), if_asked=(_DAY_OF_THE_DEAD,), grief=True),
    Term(r"\bmuert[oa]s?\b", if_asked=(_DAY_OF_THE_DEAD,)),     # "dead" in Spanish, as in "Día de los Muertos"
    Term(r"\bdie\b", (r"\bdie\s+(?:of\s+laughter|laughing)\b", r"\b(?:roll|rolls|rolled|rolling)\s+(?:the|a|that|your)\s+die\b")),
    Term(r"\bdeath\b", grief=True),
    Term(r"\bkill(?:s|ed|ing)?\b", (r"\b(?:joke|riddle|you)\s+kills?\s+me\b",)),
    Term(r"\bblood(?:y)?\b", (r"\bblood\s+oranges?\b",)),
    Term(r"\bweapon"),
    # "a lump of coal" is a naughty-list threat; a toy train's coal car is not.
    Term(r"\bcoal\b", (r"\bcoal\s+(?:cars?|tenders?|wagons?)\b",)),
    Term(r"\bdollars?\b", (r"\bsand\s+dollars?\b", r"\b(?:toy|play|pretend)\s+dollars?\b")),
    Term(r"\bamazon\b", (r"\bamazon\s+(?:rainforest|river|jungle|parrots?)\b",)),
]
_BLOCK_TERMS_RE = [(re.compile(t.word, re.IGNORECASE), _any_of(t.safe), _any_of(t.if_asked), t.grief)
                   for t in BLOCK_TERMS]


def blocked_word(text: str, child_said: str = "") -> str | None:
    """The first blocklist word in `text` that is not inside one of its safe phrases, or None.
    child_said: the child's words this turn; an if_asked phrase counts as safe only when they hold one too, and a
    grief word only next to who they said died."""
    for word_rx, safe_rx, asked_rx, grief in _BLOCK_TERMS_RE:
        safe = [m.span() for m in safe_rx.finditer(text)] if safe_rx else []
        if asked_rx and child_said and asked_rx.search(child_said):
            safe += [m.span() for m in asked_rx.finditer(text)]
        if grief and child_said:
            safe += _grief_spans(text, child_said)
        for m in word_rx.finditer(text):
            if not any(a <= m.start() and m.end() <= b for a, b in safe):
                return m.group()
    return None


class _AnyRule:
    """BLOCK_RE for old callers (safety._BLOCK_RE, tools): .search(text) is truthy when any regex SAFETY rule, an intent
    rule or a blocklist word hits. Truthiness is the whole contract; the value is a Match, a reason or the word."""

    _RULES = re.compile("|".join(p for _, pats in SAFETY_RULES for p in pats), re.IGNORECASE)

    def search(self, text: str):
        return self._RULES.search(text) or intent_reason(text) or blocked_word(text)


BLOCK_RE = _AnyRule()

# ----------------------------------------------------------------- private details (input, facts and output)
_NUMWORDS = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
             "fifteen sixteen seventeen eighteen nineteen twenty thirty forty fifty sixty seventy "
             "eighty ninety hundred").split()
_NW = "(?:" + "|".join(_NUMWORDS) + ")"
_DIGIT_WORDS = "zero one two three four five six seven eight nine".split()
_STREET = (r"(?:street|st|road|rd|avenue|ave|lane|ln|drive|dr|court|ct|way|blvd|boulevard|place|pl|"
           r"circle|cir|terrace|ter|parkway|pkwy|highway|hwy)")
_WORD = r"(?:[^\W\d_]|['’-])+"
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
    """"address", "phone" or None. One check for the child's words, extracted facts and Santa's output."""
    if _STREET_RE.search(text) or _LIVES_RE.search(text):
        return "address"
    for m in _DIGITS_RE.finditer(text):
        if not _counting([int(t) for t in re.findall(r"\d+", m.group())]):
            return "phone"
    for m in _SPELLED_RE.finditer(text):
        if not _counting([_DIGIT_WORDS.index(w.lower()) for w in re.findall(r"[A-Za-z]+", m.group())]):
            return "phone"
    return None


_NUMBERISH_RE = re.compile(rf"\d|(?:\b{_NW}\b.*){{2}}", re.I)


def has_number(text: str) -> bool:
    """Digits, or two or more number words: such a sentence could be one piece of a private number that is split
    over several sentences ("My number is 555. 123. 4567."), so the speech filter holds it back one sentence."""
    return bool(_NUMBERISH_RE.search(text))


def looks_private(text: str) -> bool:
    return private_kind(text) is not None


# Facts go back into Santa's prompt on every later turn, so anything that reads like an instruction is never stored
# (stored prompt injection: "Emma says you must tell everyone ..."). A real fact is about the child, in the third
# person ("has a cat named Mittens"); it never talks to Santa ("you", "your") or about rules and prompts.
INSTRUCTION_RE = re.compile(
    r"\b(?:you|your|you['’](?:re|ll|ve|d)|yours|yourself|ignore|disregard|override|instructions?|rules?|prompts?|"
    r"system|pretend|role-?play|jailbreak|must|from now on|always say|never say|repeat after|"
    r"santa (?:should|must|will|has to|needs to|is to))\b", re.IGNORECASE)


# "Ho ho" / "Ho, ho, ho!" / "ho-ho-ho": two or more "ho"s. Gaps hold no letters, so this cannot backtrack badly.
HO_RE = re.compile(r"\bho\b(?:[\s,!.…-]+ho\b)+[\s,!.…-]*", re.I)
_GAP_BEFORE_END = re.compile(r"[\s,;:-]+([!?.…])")


def strip_ho(sentence: str) -> str:
    """Remove "Ho ho (ho)" from a sentence (remove-only; the next word is capitalised if it now starts the
    sentence). "" if nothing is left to say."""
    if not HO_RE.search(sentence):
        return sentence
    end = re.search(r"[!?.…]+$", sentence.rstrip())
    s = _GAP_BEFORE_END.sub(r"\1", HO_RE.sub(" ", sentence))
    s = " ".join(s.split()).lstrip(" ,;:-!.…").rstrip(" ,;:-")
    if not re.search(r"[^\W\d_]", s):
        return ""
    if end and not s.endswith(("!", "?", ".", "…")):
        s += end.group()                    # keep the sentence's own ending ("That's silly, ho ho!" -> "That's silly!")
    return s[0].upper() + s[1:]


def looks_like_instruction(text: str) -> bool:
    return bool(INSTRUCTION_RE.search(text))


# Facts return to Santa's prompt as "Santa already knows this": a fact that claims what Santa promised, said or gave
# would read as Santa's own word (P4-6). Not an instruction, so INSTRUCTION_RE does not catch it. Facts only; replies
# use the promise rules. Every alternative is fixed words with single \s+ gaps: linear time.
SANTA_CLAIM_RE = re.compile(
    r"(?:^|[.!?;:]\s*)santa\b"                                          # Santa (or Santa's) as a sentence's subject
    r"|\bpromis(?:e|es|ed|ing)\b"
    r"|\bsaid\s+(?:i|she|he|they)\s+(?:can|could|will)\b"
    r"|\bfrom\s+santa\b"
    r"|\bsanta\s+(?:will|['’]ll|is\s+going\s+to|is\s+gonna)\b"
    r"|\bsanta\s+(?:to\s+)?(?:say|says|said|tell|tells|told)\b"         # "wants Santa to say ...", "Santa told her"
    r"|\bsanta\s+(?:gave|gives|brought|brings)\b",                       # not "wants Santa to bring": that is a wish
    re.IGNORECASE)


def looks_like_santa_claim(text: str) -> bool:
    return bool(SANTA_CLAIM_RE.search(text))


def looks_private_fact(text: str) -> bool:
    """For facts about to be stored in a profile: looks_private() plus last names."""
    return looks_private(text) or bool(_LASTNAME_RE.search(text))


def safety_reason(text: str, names=(), gift_turn: bool = False, child_said: str = "") -> str | None:
    """Why `text` must not be spoken: "secret" | "meeting" | "danger" | "price" | "naughty_list" | "promise" |
    "ai_identity" | "blocklist" | "private" | None.
    names: the active child's name and nicknames (P1-3: "I'll bring Emma a bike!" is a promise like "you").
    gift_turn: the child just asked for a gift (speech.is_gift_turn), so the pronoun rules apply too (P1-3 part B).
    child_said: the child's words this turn; a blocklist if_asked phrase ("Day of the Dead") is fine only when the
    child said it first. The only argument that can make a line pass that would fail without it.
    The intent rules come first, so "I promise to keep your secret" is a "secret" (and gets that topic's line)."""
    intent = intent_reason(text)
    if intent is not None:
        return intent
    for name, rx in _SAFETY_RE:
        if rx.search(text):
            return name
        if name == "promise" and names:
            nrx = _name_promise_re(tuple(names))
            if nrx is not None and nrx.search(text):
                return name
        if name == "promise" and gift_turn and gift_turn_promise(text):
            return name
    if blocked_word(text, child_said) is not None:
        return "blocklist"
    return "private" if looks_private(text) else None


# ----------------------------------------------------------------- P1-3 part B: after the child asked for a gift
# The child's request ("Can I have a pony?") makes Santa's pronoun the gift: "I'll bring it!", "Yes! You'll find it
# under the tree!". These rules apply only on a gift turn (speech.is_gift_turn) and never on a question sentence
# ("What would you like Santa to bring you?").
# Trigger (b): a request shape, or a gift noun, in the child's words (gifts.talks_gifts is checked by the caller).
GIFT_REQUEST_RE = re.compile(
    r"\b(?:(?:can|could|may)\s+i\s+(?:please\s+)?(?:have|get)"
    r"|(?:will|can|could|would)\s+you\s+(?:please\s+)?(?:bring|give|get)\s+me"
    r"|i\s+(?:really\s+)?(?:want|need|wish))\b"
    r"|\b" + _GIFT_RX, re.I)
_B_SUBJ = r"\b(?:i|we|santa|(?:my|the)\s+elves)"
_B_MODAL = (r"(?:\s+will|['’]ll|\s+shall|\s+can(?!['’]t)|\s+could"
            r"|(?:\s+(?:am|is|are)|['’](?:m|s|re))?\s+(?:going\s+to|gonna))")
_PRONOUN = r"(?:it|that|this|one|them|those|these)(?![\w'’])"
_B_AFFIRM = _AFFIRM + r"[\s,!.]+(?:and\s+)?"
_GIFT_TURN_RULES = [
    # B1 pronoun object: "I'll bring it!", "Yes, I'll bring you one!", "I'll put one in your stocking!".
    # "make it" + another word is not a gift ("I'll make it snow!"); "I'll make it for you!" is.
    _B_SUBJ + _B_MODAL + _BETWEEN + r"[\s,]+(?:make\s+(?:you\s+)?(?!it\s+(?!for\b|just\b)[^\W\d_])|(?!make\b)"
    + _GIFT_VERB + r"\s+(?:you\s+)?)" + _PRONOUN,
    # B1 you-subject: "Yes! You'll find it under the tree!", "I wrote it down, and you'll get it!"
    r"\byou(?:['’]ll|\s+will|\s+can(?!['’]t)|['’]re\s+(?:going\s+to|gonna)|\s+are\s+(?:going\s+to|gonna))"
    r"\s+(?:get|have|find|receive|see|open)\s+" + _PRONOUN,
    # B2 bare commitment: "Yes, I will!", "Yes, you can!"
    _B_AFFIRM + r"(?:i|you|we|santa)(?:\s+(?:will|can|shall)|['’]ll)(?=\s*(?:[.!…]+(?:\s|$)|$))",
    # B3 affirmative + commitment verb + gift noun: "Of course! I'll bring a pony!"
    _B_AFFIRM + r"(?:" + _B_SUBJ.removeprefix(r"\b") + _B_MODAL + _BETWEEN + r"|" + _ELVES_TO.removeprefix(r"\b")
    + r")[\s,]+" + _GIFT_VERB + r"\b" + _within(8, _GIFT_RX),
]
_GIFT_TURN_RE = re.compile("|".join(_GIFT_TURN_RULES), re.IGNORECASE)
_SENT_END = re.compile(r"[.!?…]+")


def gift_turn_promise(text: str) -> bool:
    """A B-rule match whose sentence does not end in "?". A match never crosses . ! ? (except the affirmative's own
    punctuation in "Yes! I'll bring a pony!"), so its sentence ends at the next run of . ! ? … after it."""
    pos = 0
    while (m := _GIFT_TURN_RE.search(text, pos)) is not None:
        end = _SENT_END.search(text, m.end())
        if end is None or "?" not in end.group():
            return True
        pos = m.start() + 1
    return False


def is_gift_request(child_text) -> bool:
    """The child's words hold a request shape or a gift noun (trigger (b), together with gifts.talks_gifts)."""
    return bool(child_text) and GIFT_REQUEST_RE.search(str(child_text).replace("’", "'")) is not None


# A sentence that is only an affirmative ("Yes!", "Of course!", "Ho ho ho, okay!", "Oh, sure!"): on a gift turn it is
# held until the next sentence shows whether it goes with a promise.
_YES = r"(?:yes|yeah|yep|okay|ok|sure|of\s+course|absolutely)"


@functools.lru_cache(maxsize=64)
def _bare_affirm_named_re(names: tuple[str, ...]) -> "re.Pattern":
    """Built on first use: _INTERJECTION (the opener words) is defined further down."""
    alts = sorted({n.strip() for n in names if isinstance(n, str) and re.search(r"[^\W\d_]", n)}, key=len, reverse=True)
    vocative = r"(?:[\s,]+(?:" + "|".join(re.escape(a) for a in alts) + r"))?" if alts else ""
    return re.compile(r"\W*(?:" + _INTERJECTION + r"[\s,!.…-]+)*" + _YES + r"(?:[\s,!.…-]+" + _YES + r")*"
                      + vocative + r"\W*", re.I)


def is_bare_affirmative(sentence: str, names=()) -> bool:
    """Only an affirmative, optionally after an interjection opener and before the child's name ("Yes, Emma!")."""
    return bool(_bare_affirm_named_re(tuple(names or ())).fullmatch(sentence.strip()))


# =============================================================================================== cleaning
_ACTIONS = {"waves", "giggles", "chuckles", "laughs", "winks", "nods", "smiles", "sighs",
            "grins", "claps", "twirls", "bows", "jingles", "gasps", "whispers"}
# Words that only ever appear inside a stage direction like *waves happily*. Never put negations, ordinary content
# words or SOUND words here ("jingle jingle" is something Santa says).
_STAGE_WORDS = {"softly", "happily", "gently", "warmly", "loudly", "quietly", "merrily", "cheerfully",
                "excitedly", "brightly", "kindly", "and", "laughing", "smiling", "winking", "nodding", "chuckling",
                "waving", "giggling", "twinkles", "beams", "pauses", "hugs"}
# Sounds Santa may say out loud, also when the model wraps them in *...*.
SOUNDS = {"jingle", "jingling", "whoosh", "ho", "zoom", "beep", "choo", "ding", "dong", "brr", "vroom", "ring",
          "swish", "woosh", "whee", "roar", "rooar", "rawr", "boom", "honk", "toot", "moo", "meow", "woof", "neigh",
          "clop", "tick", "tock", "pop", "splash", "crunch", "yum", "yummy", "mmm", "sparkle", "twinkle", "purr",
          "purrr", "ooh", "oooh", "wow", "hooray", "yay", "bells", "ring-a-ling", "ha", "hee", "tee", "chugga"}
_BARE = "giggles|chuckles|laughs|winks|nods|smiles|sighs|waves"

# A leading interjection-only opener ("Ho ho ho!", "Ooooh!", "Well, wow!"): at most 3 words, all from this set.
_INTERJECTION = r"(?:ho(?:ho)*|o+h+|ah+|aha|oh+|well|wow|hey|yay|whee+|hooray|hmm+)"
_OPENER_RE = re.compile(rf"^\W*{_INTERJECTION}(?:[\s,\-]+{_INTERJECTION})*\W*$", re.I)
# A last sentence that only sets up a reveal ("You know what?") is never left hanging.
_TEASER_RE = re.compile(
    r"^(?:(?:and|but|oh|well)[,\s]+)?(?:do you know what|you know what|guess what|know what"
    r"|(?:do you )?want to (?:hear|know) a (?:secret|surprise)|i have a (?:secret|surprise)(?: for you)?"
    r"|here'?s a secret)(?:,\s*[\w'-]+)?\W*$", re.I)

_EMOJI_RE = re.compile(r"[\U0001F000-\U0001FAFF☀-➿⬀-⯿]")
_JOINERS_RE = re.compile(r"[‍️]")
_WORDS_RE = re.compile(r"[a-z0-9]+(?:['’][a-z]+)?")
_SPAN_RE = re.compile(r"\*+([^*]+?)\*+|\(([^)]*)\)")
_CLOSERS = "\"'”’)]*_"


def words_of(text: str) -> list[str]:
    return _WORDS_RE.findall(text.lower())


def _is_direction(inner: str) -> bool:
    """Only action/stage words (*waves happily*, (giggles)). Sound words never make a direction."""
    words = re.findall(r"[a-z']+", inner.lower())
    return bool(words) and all(w in _ACTIONS or w in _STAGE_WORDS for w in words) \
        and not all(w in SOUNDS for w in words)


def _only_sounds(inner: str) -> bool:
    w = words_of(inner)
    return bool(w) and all(x in SOUNDS for x in w)


def _drop_standalone(seg: str) -> str:
    """Delete a *span* / (span) that stands alone between sentences ("Ho ho! *nibbles* Yes!"), unless it is only
    sound words ("*Jingle jingle!*") or holds a negation ("Santa—*not*—a robot"; deleting it inverts the meaning).
    A span inside a sentence is emphasis and is kept (unwrapped later)."""
    def repl(m):
        inner = m.group(1) if m.group(1) is not None else m.group(2)
        before = seg[:m.start()].rstrip().rstrip(_CLOSERS + " ")
        after = seg[m.end():].lstrip()
        alone_b = not before or before[-1] in ".!?…—–-"
        # starts a new sentence, or is an aside between dashes ("Mittens—*purrs*—she's asleep")
        alone_a = not after or after[0].isupper() or after[0] in "\"“" or \
            (bool(before) and before[-1] in "—–" and after[0] in "—–")
        if alone_b and alone_a and not _only_sounds(inner) and \
                not re.search(r"\b(?:not|never|no|nobody|nothing)\b|n['’]t\b", inner, re.I):
            return " "
        return m.group(0)
    return _SPAN_RE.sub(repl, seg)


def _unwrap(m: "re.Match") -> str:
    inner = m.group(1)
    return " " if _is_direction(inner) else inner


def clean_segment(seg: str) -> str:
    """Remove-only cleaning of one raw segment (see split_raw)."""
    had_markup = bool(re.search(r"[*_(\[]", seg))
    text = _drop_standalone(seg)
    text = re.sub(r"\*+([^*]+?)\*+", _unwrap, text)          # *x*, **x**, *x y*: keep the words
    text = re.sub(r"__([^_]+?)__", _unwrap, text)            # __x__
    text = re.sub(r"\(([^)]*)\)|\[([^\]]*)\]",                # (giggles) removed; [a surprise] / (real words) kept
                  lambda m: " " if _is_direction(m.group(1) if m.group(1) is not None else m.group(2))
                  else (m.group(1) if m.group(1) is not None else m.group(2)), text)
    text = re.sub(r"[*_#`>()\[\]]+", " ", text)               # leftover markup: a space, so "a#no" stays two words
    text = _EMOJI_RE.sub(" ", text)
    text = _JOINERS_RE.sub("", text)
    text = re.sub(r"—{2,}", "—", text)
    # "Ho ho giggles!" -> "Ho ho!"  (a bare action word straight after Ho ho)
    text = re.sub(rf"\b(ho(?:[\s,]+ho)*)[\s,]+(?:{_BARE})\b(?=\s*[.!?,;—-]|\s*$)", r"\1", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([.!?,;])", r"\1", text)               # " ." -> "."
    text = re.sub(r"[,;]+\s*([.!?])", r"\1", text)            # ",." -> "."
    text = text.lstrip(" ,;—–-")
    if re.fullmatch(rf"(?:{_BARE})\W*", text, re.I):          # "Giggles." alone is a stage direction
        return ""
    if had_markup and _is_direction(text):                    # "*waves happily." split across a boundary
        return ""
    if not re.search(r"\w", text):                            # only punctuation left
        return ""
    return text


# =============================================================================================== sentences
# A segment ends after . ! ? … (and closing quotes/brackets/asterisks) followed by whitespace; never after an
# abbreviation. The whitespace run must be followed by something, so a stream knows the boundary is final.
_BOUNDARY = re.compile(r"(?<!\bMr)(?<!\bMrs)(?<!\bMs)(?<!\bDr)(?<!\bSt)[.!?…]+[\"'”’)\]*_]*(?=\s)")
# The same rule on cleaned text (no markup left).
_SENT_SPLIT = re.compile(r"(?<!\bMr\.)(?<!\bMrs\.)(?<!\bMs\.)(?<!\bDr\.)(?<!\bSt\.)(?<=[.!?…])\s+")


def split_sentences(text: str) -> list[str]:
    """Sentences of already-cleaned text."""
    return [s for s in _SENT_SPLIT.split(text.strip()) if s.strip()]


def next_boundary(buf: str, start: int = 0):
    """(segment_end, next_start) of the first final boundary in buf[start:], or None if there is none yet.
    Final = the punctuation is followed by whitespace AND something after the whitespace."""
    for m in _BOUNDARY.finditer(buf, start):
        ws = re.match(r"\s+", buf[m.end():])
        nxt = m.end() + ws.end()
        if nxt < len(buf):
            return m.end(), nxt
        return None
    return None


def split_raw(raw: str) -> list[str]:
    """Raw segments of a complete reply (what a stream would deliver one by one)."""
    out, pos = [], 0
    while True:
        b = next_boundary(raw, pos)
        if b is None:
            break
        out.append(raw[pos:b[0]])
        pos = b[1]
    out.append(raw[pos:])
    return [s for s in out if s.strip()]


def sentences_of_segment(seg: str) -> list[str]:
    return split_sentences(clean_segment(seg))


def split_clean(raw: str) -> list[str]:
    """Cleaned sentences of a raw reply, in order. clean(raw) is these joined by spaces."""
    return [s for seg in split_raw(raw) for s in sentences_of_segment(seg)]


def clean(raw: str) -> str:
    """Remove-only: markdown, emoji and stage directions removed; words and punctuation otherwise untouched."""
    return " ".join(split_clean(raw))


def is_opener(sentence: str) -> bool:
    return len(sentence.split()) <= 3 and bool(_OPENER_RE.match(sentence))


def is_teaser(sentence: str) -> bool:
    return bool(_TEASER_RE.match(sentence.strip()))


def is_bare_action(sentence: str) -> bool:
    return bool(re.fullmatch(rf"(?:{_BARE})\W*", sentence, re.I))


def content_sentences(sentences: list[str]) -> int:
    return len(sentences) - (1 if len(sentences) > 1 and is_opener(sentences[0]) else 0)


# =============================================================================================== SHAPE (measured)
_MARKUP_RE = re.compile(r"\*\*|__|#|`|^\s*(?:[-•]|\d+\.)\s|\*[^*\s][^*]*\*|_[^_\s][^_]*_", re.M)
_QUESTION_RE = re.compile(r"\?+")
# Measurement only (persona score in the bench): ANY mention of being an AI or a brand, also "I'm Santa, not ChatGPT".
# Deliberately wider than the ai_identity SAFETY rule, which blocks only claims.
AI_MENTION_RE = re.compile(r"\b(i am|i'm|i’m)\s+(an?\s+)?(ai|robot|computer|chatbot|language model|artificial)\b"
                           r"|\bas an ai\b|\blanguage model\b"
                           r"|chatgpt|openai|anthropic|gemma|google|mistral", re.I)


def questions(text: str) -> int:
    """Number of questions ("??" counts once)."""
    return len(_QUESTION_RE.findall(text))


def has_stage_direction(raw: str) -> bool:
    """A stand-alone or action-only *span* / (span), or a bare action sentence ("Giggles.")."""
    for seg in split_raw(raw):
        if _drop_standalone(seg) != seg:
            return True
        if any(_is_direction(a or b) for a, b in _SPAN_RE.findall(seg)):
            return True
        if is_bare_action(seg.strip()):
            return True
    return False


def shape_flags(raw: str) -> list[str]:
    """SHAPE measurements on the raw model output (empty list = the reply already has the wanted shape).
    Never used to change what is spoken (except the hard cap in speech.py)."""
    if not raw.strip():
        return ["empty"]
    sents = split_clean(raw)
    f = []
    if questions(raw) > 1:
        f.append("questions>1")
    if content_sentences(sents) > MAX_CONTENT_SENTENCES:
        f.append("sentences>3")
    if sum(len(s.split()) for s in sents) > MAX_WORDS:
        f.append("words>45")
    if has_stage_direction(raw):
        f.append("stage")
    if _MARKUP_RE.search(raw):
        f.append("markup")
    if _EMOJI_RE.search(raw):
        f.append("emoji")
    return f


def mentions_ai(text: str) -> bool:
    return bool(AI_MENTION_RE.search(text))
