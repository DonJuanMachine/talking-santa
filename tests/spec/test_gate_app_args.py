"""P7-2: the gate properties (S1-S6, S11) and the corpus gates, run with the arguments the app really uses.

santa/brain.py builds the gate as
    speech.Gate(allow_ho=not self.ho_once or cues.sings_or_jokes(text), names=self._names(speaker), child_turn=text)
and feeds it the model's stream through speech.Segmenter + spec.sentences_of_segment, chunk by chunk. The S1-S6 tests
in test_spec.py use allow_ho=True, no name and no child turn, and their vocabulary never reaches a safety rule. Here
the replies are built from a vocabulary that reaches every rule (gift verbs and nouns, the child's name, numbers,
AI and brand words, blocklist words, commitment phrases, bare affirmatives), and every example is run with "Ho ho"
allowed or removed, names=("Juniper",), and a child turn that is a gift request, an ordinary line or absent.

The one rewrite the gate is allowed: when "Ho ho" is removed from the start of a sentence, the next word is
capitalised (spec.strip_ho; P1-11, docs claim G4). Everything else is removal only.
"""
import _support  # noqa: F401  (temp profiles; must come first)

import re
from collections import Counter

from _support import E4B_V1, GOLDEN, STORED
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

import _quality as Q
from santa import cues, songs, spec, speech
from test_spec import is_subsequence, make_santa, neg, punct_counts

FB = spec.FALLBACK
NAMES = ("Juniper",)
SAFETY_REASONS = {"naughty_list", "promise", "ai_identity", "blocklist", "private"}
HYP = settings(database=None, derandomize=True, max_examples=400, deadline=None,
               suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large])


# ======================================================================== the gate, called the way brain.py calls it
def app_gate(chunks, allow_ho, child_turn):
    """brain.reply_stream's gate loop (prefix filter path), without the model and the P1-2 tail."""
    gate = speech.Gate(allow_ho=allow_ho, names=list(NAMES), child_turn=child_turn)
    seg = speech.Segmenter()
    for piece in chunks:
        if gate.stopped:
            continue
        for s_raw in seg.feed(piece):
            for s in spec.sentences_of_segment(s_raw):
                gate.push(s)
    for s_raw in seg.finish():
        for s in spec.sentences_of_segment(s_raw):
            gate.push(s)
    gate.finish()
    return gate


def heard(raw, allow_ho, child_turn):
    return app_gate([raw], allow_ho, child_turn).text


def kept_sentences(raw, allow_ho):
    """(index into split_clean(raw), sentence as the gate sees it) for every sentence the gate does not skip:
    "Ho ho" removed when allow_ho is False, empty and bare-action sentences dropped. The S1 oracle."""
    out = []
    for i, s in enumerate(spec.split_clean(raw)):
        t = s if allow_ho else spec.strip_ho(s)
        if t.strip() and not spec.is_bare_action(t):
            out.append((i, t))
    return out


_WORD_CS = re.compile(r"[^\W_]+(?:['’][^\W_]+)*")


def words_in_order_with_ho_capital(heard_text, raw, allow_ho):
    """Case-sensitive: the heard words are an in-order subsequence of the raw words. The only difference allowed is
    an upper-cased first letter on the first word of a heard sentence, and only when "Ho ho" is being removed."""
    starts = set()
    pos = 0
    for s in spec.split_sentences(heard_text):
        ws = _WORD_CS.findall(s)
        if ws:
            starts.add(pos)
        pos += len(ws)
    hw, rw = _WORD_CS.findall(heard_text), _WORD_CS.findall(raw)
    it = iter(rw)

    def same(i, w, x):
        if w == x:
            return True
        return (not allow_ho) and i in starts and w == x[:1].upper() + x[1:]

    return all(any(same(i, w, x) for x in it) for i, w in enumerate(hw))


# ======================================================================== replies that reach every rule
PLAIN_WORDS = ["snow", "Juniper", "trucks", "cookies", "reindeer", "sleigh", "big", "red", "happy", "elves", "love",
               "you", "like", "the", "a", "is", "so", "fun", "not", "never", "no", "don't", "can't", "whoosh", "it",
               "your", "tree", "under", "for", "one", "find"]
COMMIT = ["I'll bring", "I will bring", "Santa will bring", "You'll get", "I promise", "My elves will make",
          "You're getting", "I'll put", "We'll bring", "You can have", "Juniper will get"]
RECIPIENT = ["you", "Juniper", "for you", "for Juniper", "your", "Juniper's", ""]
GIFT = ["a puppy", "a bike", "a pony", "a tractor", "a toy", "it", "one", "a teddy bear", "a drum", "them"]
RISKY = [
    "you're on the naughty list", "the naughty list", "you are on the naughty list", "my naughty list",
    "I'm a robot", "as an AI", "I am ChatGPT", "I'm Gemma, made by Google", "a language model", "I'm not a computer",
    "the monster", "a dead tree", "coal", "ten dollars", "Amazon",
    "555 123 4567", "12 Oak Lane", "five five five one two one two", "2 reindeer", "three elves and four reindeer",
    "call 555 867 5309", "your house is 4 Elm Street", "my number is 202 555 0143",
    "you'll find it under the tree", "you will get it", "Yes, I will", "Yes, you can",
]
AFFIRM = ["Yes!", "Yes, Juniper!", "Of course!", "Yes yes!", "Okay!"]
OPENERS = ["Ho ho ho!", "Ho, ho!", "Ooooh!", "Well, wow!", "Ho ho ho, Juniper!"]
HO_INLINE = ["ho ho", "Ho ho", "ho, ho, ho", "ho-ho"]
NEG_WORDS = ["not", "never", "no", "don't", "can't", "isn't", "won't", "nobody", "nothing", "Not", "Never"]
STAGE = ["*waves*", "(giggles)", "*nibbles a cookie*", "(adjusts glasses)"]
EMOJI = ["⭐", "🎄", "❄️"]
ENDS = [".", "!", "?", "!!", "...", "?!"]
CHILD_TURNS = [None, "", "Can I have a puppy?", "I want a tractor!", "A pony!", "Will you bring me a bike?",
               "I like snow", "Can we sing a song?", "Tell me a joke", "yes", "My cat is called Mittens"]


@st.composite
def risky_phrase(draw):
    kind = draw(st.integers(0, 2))
    if kind == 0:
        parts = [draw(st.sampled_from(COMMIT)), draw(st.sampled_from(RECIPIENT)), draw(st.sampled_from(GIFT))]
        return " ".join(p for p in parts if p)
    if kind == 1:
        return draw(st.sampled_from(RISKY))
    return draw(st.sampled_from(COMMIT)) + " " + draw(st.sampled_from(GIFT)) + " for " + \
        draw(st.sampled_from(["you", "Juniper"]))


@st.composite
def sentence(draw):
    """(raw sentence, the same sentence without markup)."""
    if draw(st.integers(0, 7)) == 0:
        a = draw(st.sampled_from(AFFIRM))
        return a, a
    if draw(st.integers(0, 5)) == 0:
        # "Ho ho" next to a negation: removing the laugh must leave every negation in place (S6 on the app path)
        words = draw(st.lists(st.sampled_from(PLAIN_WORDS), min_size=1, max_size=5))
        words.insert(draw(st.integers(0, len(words))), draw(st.sampled_from(NEG_WORDS)))
        words.insert(draw(st.sampled_from([0, len(words)])), draw(st.sampled_from(HO_INLINE)))
        return _finish(draw, words)
    words = draw(st.lists(st.sampled_from(PLAIN_WORDS), min_size=0, max_size=6))
    if draw(st.integers(0, 2)) == 0 or not words:
        words.insert(draw(st.integers(0, len(words))), draw(risky_phrase()))
    if draw(st.integers(0, 5)) == 0:
        words.insert(draw(st.sampled_from([0, len(words)])), draw(st.sampled_from(HO_INLINE)))
    return _finish(draw, words)


def _finish(draw, words):
    """Markup, an emoji, a capital and an ending: (raw sentence, plain sentence)."""
    plain = list(words)
    styled = list(words)
    if draw(st.booleans()):
        i = draw(st.integers(0, len(words) - 1))
        if " " not in words[i]:
            styled[i] = draw(st.sampled_from(["*{}*", "**{}**", "__{}__"])).format(words[i])
    if draw(st.integers(0, 6)) == 0:
        styled.insert(draw(st.integers(0, len(styled))), draw(st.sampled_from(EMOJI)))
    if styled[0][:1].isalpha():
        styled[0] = styled[0][:1].upper() + styled[0][1:]
    plain[0] = plain[0][:1].upper() + plain[0][1:]
    end = draw(st.sampled_from(ENDS))
    return " ".join(styled) + end, " ".join(plain) + end


@st.composite
def case(draw):
    """(raw, plain sentences in order, allow_ho, child_turn, chunks)."""
    parts, plain = [], []
    if draw(st.booleans()):
        o = draw(st.sampled_from(OPENERS))
        parts.append(o)
        plain.append(o)
    for _ in range(draw(st.integers(1, 5))):
        if draw(st.integers(0, 6)) == 0:
            parts.append(draw(st.sampled_from(STAGE)))
        s, p = draw(sentence())
        parts.append(s)
        plain.append(p)
    raw = " ".join(parts)
    allow_ho = draw(st.booleans())
    child_turn = draw(st.sampled_from(CHILD_TURNS))
    cuts = sorted(set(draw(st.lists(st.integers(1, max(1, len(raw) - 1)), max_size=30)))) if len(raw) > 1 else []
    chunks = [raw[i:j] for i, j in zip([0] + cuts, cuts + [len(raw)])]
    return raw, plain, allow_ho, child_turn, chunks


# ======================================================================== the strategy reaches the rules
def test_the_strategy_reaches_every_safety_rule_and_the_fallback():
    """If the vocabulary stops reaching the rules, the property tests below become vacuous: fail instead."""
    stats = Counter()

    @HYP
    @given(case())
    def run(c):
        raw, _, allow_ho, child_turn, _ = c
        g = app_gate([raw], allow_ho, child_turn)
        stats["n"] += 1
        if g.reason in SAFETY_REASONS:
            stats["safety_stop"] += 1
            stats[g.reason] += 1
        if g.text == FB:
            stats["fallback"] += 1
        if g.reason in SAFETY_REASONS or g.text == FB:
            stats["stop_or_fallback"] += 1
        if not allow_ho and spec.HO_RE.search(raw):
            stats["ho_removed"] += 1
            # a spoken sentence that lost its "Ho ho" and holds a negation (what S6 checks on the app path)
            if any(spec.HO_RE.search(s) and neg(s) and spec.strip_ho(s) in g.spoken for s in spec.split_clean(raw)):
                stats["ho_negation_spoken"] += 1
        # stops that only the app's arguments cause: the child's name, and the gift-turn pronoun rules, each on its own
        if g.reason == "promise":
            if speech.filter_reply(raw, allow_ho, [], child_turn).reason != "promise":
                stats["needs_name"] += 1
            if speech.filter_reply(raw, allow_ho, list(NAMES), None).reason != "promise":
                stats["needs_gift_turn"] += 1
        if speech.is_gift_turn(child_turn):
            stats["gift_turn"] += 1

    run()
    n = stats["n"]
    assert n >= 300, stats
    assert stats["stop_or_fallback"] / n >= 0.25, stats
    assert stats["fallback"] / n >= 0.05, stats
    for reason in SAFETY_REASONS:
        assert stats[reason] / n >= 0.01, (reason, stats)
    assert stats["needs_name"] / n >= 0.01, stats
    assert stats["needs_gift_turn"] / n >= 0.01, stats
    assert stats["ho_removed"] / n >= 0.1, stats
    assert stats["ho_negation_spoken"] / n >= 0.03, stats
    assert 0.2 <= stats["gift_turn"] / n <= 0.8, stats


# ======================================================================== S1-S6 with the app's arguments
@HYP
@given(case())
def test_s1_app_args_heard_is_a_sentence_prefix_of_what_the_gate_sees(c):
    raw, _, allow_ho, child_turn, _ = c
    h = heard(raw, allow_ho, child_turn)
    kept = [t for _, t in kept_sentences(raw, allow_ho)]
    assert h == FB or h in {" ".join(kept[:k]) for k in range(1, len(kept) + 1)}, (raw, allow_ho, child_turn, h)


@HYP
@given(case())
def test_s2_app_args_never_adds_punctuation(c):
    raw, _, allow_ho, child_turn, _ = c
    h = heard(raw, allow_ho, child_turn)
    if h == FB:
        return
    rc, hc = punct_counts(raw), punct_counts(h)
    assert all(hc[k] <= rc[k] for k in ".!?"), (raw, h)
    assert spec.questions(h) <= spec.questions(raw)
    for seq in (".!", ".?", "?."):
        assert seq not in h or seq in raw, (raw, h)


@HYP
@given(case())
def test_s3_app_args_heard_words_are_an_in_order_subsequence_of_the_input(c):
    raw, _, allow_ho, child_turn, _ = c
    h = heard(raw, allow_ho, child_turn)
    if h == FB:
        return
    assert is_subsequence(spec.words_of(h), spec.words_of(raw)), (raw, h)
    # case-sensitive; the one allowed rewrite is the capital after a removed "Ho ho"
    assert words_in_order_with_ho_capital(h, raw, allow_ho), (raw, allow_ho, h)


@HYP
@given(case())
def test_s3_app_args_never_longer_than_the_input_unless_fallback(c):
    raw, _, allow_ho, child_turn, _ = c
    h = heard(raw, allow_ho, child_turn)
    assert h == FB or len(h) <= len(raw), (raw, h)
    assert h == FB or len(h.split()) <= len(raw.split()), (raw, h)


@HYP
@given(case())
def test_s4_app_args_idempotent(c):
    raw, _, allow_ho, child_turn, _ = c
    h = heard(raw, allow_ho, child_turn)
    assert heard(h, allow_ho, child_turn) == h, (raw, allow_ho, child_turn, h)


@HYP
@given(case())
def test_s5_app_args_caps(c):
    raw, _, allow_ho, child_turn, _ = c
    h = heard(raw, allow_ho, child_turn)
    assert len(h.split()) <= spec.MAX_WORDS
    assert spec.content_sentences(spec.split_sentences(h)) <= spec.MAX_CONTENT_SENTENCES


@HYP
@given(case())
def test_s6_app_args_negations_in_kept_sentences_survive(c):
    raw, plain, allow_ho, child_turn, _ = c
    h = heard(raw, allow_ho, child_turn)
    if h == FB:
        return
    assert len(spec.split_clean(raw)) == len(plain), (raw, plain)      # the generator's sentences line up
    kept = kept_sentences(raw, allow_ho)
    k = next(k for k in range(1, len(kept) + 1) if " ".join(t for _, t in kept[:k]) == h)
    assert neg(h) == sum(neg(plain[i]) for i, _ in kept[:k]), (raw, h)


# ======================================================================== S11 with the app's arguments
@HYP
@given(case())
def test_s11_app_args_any_chunking_gives_the_same_output(c):
    raw, _, allow_ho, child_turn, chunks = c
    whole = app_gate([raw], allow_ho, child_turn)
    streamed = app_gate(chunks, allow_ho, child_turn)
    assert (streamed.text, streamed.reason) == (whole.text, whole.reason), (raw, chunks)
    ref = speech.filter_reply(raw, allow_ho, list(NAMES), child_turn)
    assert (whole.text, whole.reason) == (ref.text, ref.reason)
    one_char = app_gate(list(raw), allow_ho, child_turn)
    assert one_char.text == whole.text, raw


# ======================================================================== app_gate is what brain.py really does
BRAIN_TURNS = [t for t in CHILD_TURNS if t and not songs.asks_for_song(t)]   # a song request takes the song path


@settings(database=None, derandomize=True, max_examples=120, deadline=None,
          suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large])
@given(case(), st.sampled_from(BRAIN_TURNS))
def test_app_gate_matches_the_real_brain_reply(c, child_turn):
    """The properties above test app_gate; this pins app_gate to brain.reply_stream, so a change to the arguments
    brain.py passes (a dropped child_turn or names, a different allow_ho) fails here. The brain's own allow_ho is
    "Ho ho" removed unless the child sang or told a joke (ho_once on), and P1-2 adds FALLBACK after a safety stop
    that follows spoken sentences."""
    raw, _, _, _, _ = c
    santa = make_santa([raw], profiles={"Juniper": {"age": 4, "facts": []}}, chunk=7)
    got = santa.reply("Juniper", child_turn)
    g = app_gate([raw], cues.sings_or_jokes(child_turn), child_turn)
    want = (" ".join(g.spoken + [FB]) if g.spoken and g.reason in SAFETY_REASONS else g.text)
    assert got == want, (raw, child_turn)


# ======================================================================== the corpus gates with the app's arguments
def _app_heard(r):
    """A corpus row heard the way the app would hear it: "Ho ho" removed unless the child sang or told a joke
    (ho_once on, the default), the speaker's name passed, the child's line as the child turn."""
    names = [r["speaker"]] if r.get("speaker") else []
    g = speech.filter_reply(r["raw"], cues.sings_or_jokes(r["child"]), names, r["child"])
    return g


APP = [(r, _app_heard(r)) for r in GOLDEN]
APP_BY_RAW = {id(r): g for r, g in APP}


def test_corpus_app_args_differ_from_the_test_defaults():
    """The point of running the gates again: the app hears most corpus replies differently."""
    differ = sum(1 for r, g in APP if g.text != speech.filter_reply(r["raw"]).text)
    assert differ >= len(APP) // 4, differ


def test_s9_app_args_answer_lost_at_most_1_percent_on_the_golden_corpus():
    lost = [r["raw"] for r, g in APP if "answer_lost" in Q.classify(r["raw"], r["child"], g.text)]
    assert len(lost) / len(APP) <= 0.01, (len(lost), lost[:5])


def test_s10_app_args_no_fallback_on_the_e4b_v1_replies():
    fbs = [(r["raw"], APP_BY_RAW[id(r)].fallback_reason) for r in E4B_V1 if APP_BY_RAW[id(r)].text == FB]
    assert len(E4B_V1) == 132 and not fbs, fbs


def test_artifact_or_lost_answer_app_args_at_most_1_percent_on_the_924_stored_replies():
    hit = [(r["raw"], APP_BY_RAW[id(r)].text) for r in STORED
           if Q.classify(r["raw"], r["child"], APP_BY_RAW[id(r)].text) & (Q.ARTIFACT | Q.LOST)]
    assert len(STORED) == 924 and len(hit) / 924 <= 0.01, (len(hit), hit[:5])
