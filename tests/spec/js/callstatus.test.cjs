// P5-1 slow state: the call page's status text (santa/web/static/callstatus.js). No browser, no DOM.
// Run: node --test tests/spec/js/callstatus.test.cjs   (tests/spec/test_p5_slow.py runs it when node is installed)
const { test } = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const S = require(path.join(__dirname, "..", "..", "..", "santa", "web", "static", "callstatus.js"));
const { statusText, slowAfter, noteText, SLOW_STATUS, SLOW_NOTE } = S;

test("the texts are the agreed wording", () => {
  assert.equal(SLOW_STATUS, "Santa is thinking… (this is taking a while)");
  assert.equal(SLOW_NOTE, "Santa's brain is slow to answer. If this keeps happening, restart the model runner.");
});

test("status text per state, as before when nothing is slow", () => {
  assert.equal(statusText("LISTENING", false, null), "Santa is listening");
  assert.equal(statusText("THINKING", false, null), "Santa is thinking…");
  assert.equal(statusText("SPEAKING", false, null), "");
  assert.equal(statusText("GREETING", false, null), "");
  assert.equal(statusText("RINGING", false, null), "");
  assert.equal(statusText("IDLE", false, null), "");
  assert.equal(statusText("IDLE", false, "Lost connection to Santa"), "Lost connection to Santa");
  assert.equal(statusText("LISTENING", false, "Lost connection to Santa"), "Santa is listening");
});

test("slow changes the THINKING text only", () => {
  assert.equal(statusText("THINKING", true, null), SLOW_STATUS);
  for (const st of ["LISTENING", "SPEAKING", "GREETING", "RINGING", "HANGUP"]) {
    assert.equal(statusText(st, true, null), statusText(st, false, null), st);
  }
  assert.equal(statusText("IDLE", true, "Lost connection to Santa"), "Lost connection to Santa");
});

test("the grown-ups' note shows only while slow in THINKING", () => {
  assert.equal(noteText("THINKING", true), SLOW_NOTE);
  assert.equal(noteText("THINKING", false), "");
  assert.equal(noteText("SPEAKING", true), "");
});

test("a slow message sets the flag only during THINKING", () => {
  assert.equal(slowAfter(false, "THINKING", { type: "slow" }), true);
  assert.equal(slowAfter(false, "GREETING", { type: "slow", where: "ring" }), false);
  assert.equal(slowAfter(false, "LISTENING", { type: "slow" }), false);
});

test("any state message that is not THINKING clears the flag; THINKING keeps it", () => {
  for (const st of ["SPEAKING", "LISTENING", "IDLE", "HANGUP", "RINGING", "GREETING"]) {
    assert.equal(slowAfter(true, "THINKING", { type: "state", state: st }), false, st);
  }
  assert.equal(slowAfter(true, "THINKING", { type: "state", state: "THINKING" }), true);
});

test("Santa speaking clears the flag; ticks and other messages leave it", () => {
  assert.equal(slowAfter(true, "THINKING", { type: "audio_start", id: 3 }), false);
  assert.equal(slowAfter(true, "THINKING", { type: "tick" }), true);
  assert.equal(slowAfter(true, "THINKING", { type: "metrics" }), true);
});

test("a whole slow turn: thinking, slow, answer, listening", () => {
  let slow = false, state = "LISTENING";
  const seen = [];
  for (const m of [{ type: "state", state: "THINKING" }, { type: "tick" }, { type: "slow" }, { type: "tick" },
                   { type: "state", state: "SPEAKING" }, { type: "audio_start", id: 9 },
                   { type: "state", state: "LISTENING" }]) {
    slow = slowAfter(slow, state, m);
    if (m.type === "state") state = m.state;
    seen.push(statusText(state, slow, null));
  }
  assert.deepEqual(seen, ["Santa is thinking…", "Santa is thinking…", SLOW_STATUS, SLOW_STATUS, "", "",
                          "Santa is listening"]);
});
