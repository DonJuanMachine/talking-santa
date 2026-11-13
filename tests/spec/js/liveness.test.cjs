// P5-2: the call page's liveness watchdog (santa/web/static/liveness.js) with fake timers. No browser, no DOM.
// Run: node --test tests/spec/js/liveness.test.cjs   (tests/spec/test_p5_liveness.py runs it when node is installed)
const { test, afterEach, mock } = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const { LIVENESS, makeWatchdog } = require(path.join(__dirname, "..", "..", "..", "santa", "web", "static", "liveness.js"));

// A page: `inCall` is what app.js derives from the socket and the call state; onLost resets the page to IDLE.
function page({ inCall = true } = {}) {
  mock.timers.enable({ apis: ["setInterval"] });
  const p = { t: 0, inCall, lost: 0 };
  p.wd = makeWatchdog({ inCall: () => p.inCall, onLost: () => { p.lost += 1; p.inCall = false; }, now: () => p.t });
  p.wd.start();
  p.advance = (ms, tickEvery = 0) => {            // move the clock in 100 ms steps; a server tick every tickEvery ms
    for (let i = 100; i <= ms; i += 100) {
      p.t += 100;
      if (tickEvery && i % tickEvery === 0) p.wd.seen();
      mock.timers.tick(100);
    }
  };
  return p;
}

afterEach(() => mock.timers.reset());

test("defaults: lost after 6 s without a message, checked every second", () => {
  assert.equal(LIVENESS.LOST_MS, 6000);
  assert.equal(LIVENESS.CHECK_MS, 1000);
});

test("a server tick every 2.5 s keeps a long call alive", () => {
  const p = page();
  p.advance(120000, 2500);
  assert.equal(p.lost, 0);
});

test("any message counts: audio or state messages every few seconds are enough", () => {
  const p = page();
  p.advance(60000, 5000);
  assert.equal(p.lost, 0);
});

test("nothing for 6 s during a call: lost, once", () => {
  const p = page();
  p.advance(5900);
  assert.equal(p.lost, 0);
  p.advance(1100);                                // 7 s: the 6 s check has fired
  assert.equal(p.lost, 1);
  p.advance(30000);                               // the page is IDLE now: no second alarm
  assert.equal(p.lost, 1);
});

test("the alarm comes at most one check after the timeout", () => {
  const p = page();
  p.advance(2000, 2000);                          // last message at 2 s
  p.advance(5000);
  assert.equal(p.lost, 0);                        // 7 s: only 5 s of silence
  p.advance(1000);
  assert.equal(p.lost, 1);                        // 8 s: 6 s of silence
});

test("an idle page never raises the alarm, however long it is quiet", () => {
  const p = page({ inCall: false });
  p.advance(600000);
  assert.equal(p.lost, 0);
});

test("after a reconnect, the next call is watched again from its first message", () => {
  const p = page();
  p.advance(7000);
  assert.equal(p.lost, 1);
  p.advance(60000);                               // reconnecting, idle
  p.inCall = true;                                // the new socket's state message: RINGING
  p.wd.seen();
  p.advance(5000, 2500);
  assert.equal(p.lost, 1);
  p.advance(7000);                                // this connection dies too
  assert.equal(p.lost, 2);
});

test("stop() ends the checks", () => {
  const p = page();
  p.wd.stop();
  p.advance(60000);
  assert.equal(p.lost, 0);
});
