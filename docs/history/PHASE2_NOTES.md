# Phase 2 notes (voice + handset)

Written in Stage F (2026-11-07). Docs only: nothing here is implemented yet.

Labels:
- **DECISION**: Don and Claude agreed on it.
- **STARTING GUESS**: a first value to try. It has not been tested.
- **UNMEASURED**: still open. Nobody has measured it yet.

## 1. Who is talking at pickup (DECISION)
- Every time the handset is picked up, set the active child to unknown (guest).
- A child becomes active only when Santa hears a registered name, or when an adult presses a button.
- Never carry the previous child over to the next pickup.
- Why: a voice cannot tell the toddlers apart. So identity comes from the name the child says, or from the button.

## 2. End-of-speech wait for toddlers (STARTING GUESS)
- Make it one constant that can be tuned.
- Start at about 1.2 to 1.5 seconds. Tune it on real toddler speech, with an adult in the room.
- Do not copy another product's figure.
- Time until Santa starts talking = this wait + TTFT (about 0.6 s, measured) + time until TTS plays its first audio
  (not measured yet). So every extra half-second of wait is felt.

## 3. A grown-up stays in the room (DECISION)
- The supervising adult stays in the room for the whole session.
- Add a way for the adult to end a session or step in (a button, or hanging up the handset).

## 4. Goodbye and hang-up (DECISION)
- Santa gives a brief, warm goodbye.
- No new question after a goodbye. No guilt, no pleading ("don't go", "stay", "I'll miss you so much").
- This is what scenario F12 measures (see `STAGE_F.md`).

## 5. Keeping the model warm (DECISION, from Stage E3)
- Ping `warm_up()` every 90 to 120 seconds, and only while idle.
- At handset pickup: start the warm-up in the background while a canned greeting plays.
- If the child's first turn arrives before the warm-up has finished, wait for it to finish.

## 6. Still open (UNMEASURED)
- How long TTS takes until its first audio.
- TTFT while Whisper and TTS are also running.
- Whether the keep-alive pings hurt prompt-cache reuse in long conversations.
- Whether the "Expiring" runner message seen earlier happens again.
- End-of-speech detection on real toddler speech.

## 7. What young children are reported to say to Santa (CONTEXT)
This is anecdote with a small n (Reddit snippets and one forum post). These are not statistics. They were used only
as seeds for the Stage F test scenarios.
- They ask for what is in front of them (food, objects).
- They name a franchise instead of a toy.
- Their wishes change within days.
- They ask for things for their pets and family.
- They bargain after a "no".
- They sometimes ask for a person ("mummy").
- Some go silent or freeze.
- Many end the visit suddenly after one request.

Real mall Santas sometimes promise ("he would bring her one"). This system must not.

Another large commercial "Santa mode" was reported to have no memory and a notice saying it is for ages 13 and up. So
there is no precedent to lean on for per-child memory for children under 5. Therefore:
- keep the memory local,
- keep an adult present,
- keep `/forget`.
