// The line under the picture (#status) and the grown-ups' slow note (#note). The server sends {"type": "slow"} once in
// a turn whose answer has not started after settings.slow_s (P5-1); the page then says it is taking a while. The flag
// clears on any state that is not THINKING and when Santa speaks. Nothing is sticky: the next fast turn looks normal.
// No DOM and no page state here, so it is tested on its own: tests/spec/js/callstatus.test.cjs.
(function (root) {
  const LABEL = Object.freeze({ LISTENING: "Santa is listening", THINKING: "Santa is thinking…" });
  const SLOW_STATUS = "Santa is thinking… (this is taking a while)";
  const SLOW_NOTE = "Santa's brain is slow to answer. If this keeps happening, restart the model runner.";

  function statusText(state, slow, lostNote) {
    if (state === "THINKING" && slow) return SLOW_STATUS;
    return LABEL[state] || (state === "IDLE" && lostNote) || "";
  }

  function noteText(state, slow) {
    return state === "THINKING" && slow ? SLOW_NOTE : "";
  }

  // The slow flag after message m, given the state the page was in when m arrived.
  function slowAfter(slow, state, m) {
    if (m.type === "slow") return state === "THINKING";      // {"where": "ring"} arrives outside THINKING: ignored
    if (m.type === "state") return slow && m.state === "THINKING";
    if (m.type === "audio_start") return false;              // Santa speaks
    return slow;
  }

  root.SantaStatus = { LABEL, SLOW_STATUS, SLOW_NOTE, statusText, noteText, slowAfter };
  if (typeof module !== "undefined" && module.exports) module.exports = root.SantaStatus;
})(typeof window !== "undefined" ? window : globalThis);
