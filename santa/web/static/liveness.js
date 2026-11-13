// Liveness during a call. The server sends {"type": "tick"} every settings.tick_s (2.5 s) while a call is active, and
// any message (tick, state, Santa's audio) counts as a sign of life. If nothing arrives for LOST_MS during a call,
// the connection is dead even though the browser has not noticed (Wi-Fi dropping packets, the Mac asleep).
// No DOM and no page state here, so it is tested on its own: tests/spec/js/liveness.test.cjs.
(function (root) {
  const LIVENESS = Object.freeze({
    LOST_MS: 6000,    // no message for this long during a call = connection lost (more than two missed ticks)
    CHECK_MS: 1000,   // how often to look; the alarm comes at most this long after LOST_MS
  });

  // seen() on every message. onLost() runs once when inCall() is true and nothing was seen for lostMs; it is
  // expected to end the call on the page, so inCall() turns false and the alarm does not repeat.
  function makeWatchdog({ inCall, onLost, lostMs = LIVENESS.LOST_MS, checkMs = LIVENESS.CHECK_MS,
                          now = () => performance.now() }) {
    let last = now(), timer = null;
    function check() {
      if (inCall() && now() - last >= lostMs) {
        last = now();
        onLost();
      }
    }
    return {
      seen() { last = now(); },
      start() { if (timer === null) timer = setInterval(check, checkMs); },
      stop() { if (timer !== null) { clearInterval(timer); timer = null; } },
      check,
    };
  }

  root.SantaLiveness = { LIVENESS, makeWatchdog };
  if (typeof module !== "undefined" && module.exports) module.exports = root.SantaLiveness;
})(typeof window !== "undefined" ? window : globalThis);
