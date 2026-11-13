// Santa call page. Mic -> AudioWorklet (16 kHz int16) -> WebSocket; Santa's voice <- WebSocket (24 kHz int16).
(() => {
  const $ = (id) => document.getElementById(id);
  const big = $("big"), statusEl = $("status"), pic = $("picture"), kidsEl = $("kids"), note = $("note");
  const overlay = $("overlay"), subEl = $("sub");
  // Top line under "Santa Claus" (FaceTime style): what the call is doing, or the call timer once Santa answers.
  const SUB = { IDLE: "Call Santa", RINGING: "Calling…", HANGUP: "Call ended" };
  // Line under the picture, during a call only.
  const LABEL = { LISTENING: "Santa is listening", THINKING: "Santa is thinking…" };
  let callStart = null;              // when Santa answered (ms), for the timer

  let ws = null, ctx = null, micStream = null, micNode = null, srcNode = null;
  let state = "IDLE", active = null, children = [];
  let deadBelow = 0;                 // audio for utterance ids < deadBelow is ignored (after stop_audio)
  let maxSeen = 0;
  const utt = new Map();             // id -> {next, sources:Set, ended, startedSent}
  let ring = null;

  // Liveness (liveness.js): during a call the server ticks every 2.5 s. No message at all for LOST_MS means the
  // connection is dead: end the call here, tell the grown-up, connect again. The note stays until the next Call.
  const LOST_TEXT = "Lost connection to Santa";
  const RECONNECT_MS = 1000;
  let lostNote = null;
  const watchdog = SantaLiveness.makeWatchdog({
    inCall: () => ws !== null && ws.readyState === 1 && state !== "IDLE",   // a closed socket reconnects on its own
    onLost: connectionLost,
  });

  // ---------------------------------------------------------------- WebSocket
  function connect() {
    ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
    ws.binaryType = "arraybuffer";
    ws.onopen = () => send({ type: "hello" });
    ws.onclose = (ev) => {
      if (ev.code === 4401) { location.reload(); return; }   // PIN needed (e.g. the server restarted)
      stopAll(); stopRing(true);
      if (ev.code === 1013) {                                  // too many Santa pages open
        setStatus("Too many Santa pages are open. Close one."); setTimeout(connect, 5000); return;
      }
      setStatus(lostNote || "Reconnecting…"); setTimeout(connect, RECONNECT_MS);
    };
    ws.onmessage = (ev) => {
      watchdog.seen();                                         // any message, text or audio, is a sign of life
      typeof ev.data === "string" ? onJson(JSON.parse(ev.data)) : onAudio(ev.data);
    };
  }
  function connectionLost() {
    const dead = ws;
    ws = null;                                                 // send() and the mic stop using it at once
    if (dead) { dead.onopen = dead.onclose = dead.onmessage = null; try { dead.close(); } catch (e) {} }
    stopAll(); stopRing(true); stopMic();
    state = "IDLE"; lostNote = LOST_TEXT;
    render();
    setTimeout(connect, RECONNECT_MS);
  }
  function send(o) { if (ws && ws.readyState === 1) ws.send(JSON.stringify(o)); }
  function setStatus(t) { statusEl.textContent = t; }

  function onJson(m) {
    switch (m.type) {
      case "state":
        state = m.state; active = m.active; children = m.children || [];
        if (state !== "IDLE") lostNote = null;
        render();
        if (state === "IDLE") stopMic();
        break;
      case "ring_start": startRing(); break;
      case "ring_stop": stopRing(); break;
      case "stop_audio": stopAll(); break;
      case "busy": stopMic(); setStatus("Santa is on another call. Try again in a minute."); break;
      case "audio_start": newUtt(m.id); break;
      case "audio_end": { const u = utt.get(m.id); if (u) { u.ended = true; maybeEnded(m.id); } break; }
      case "metrics": showMetrics(m); break;
      case "forgot":
        note.textContent = !m.child ? "Pick a child first"
          : m.this_turn ? `Santa won't remember what ${m.child} just said`
          : `Forgot ${m.count} fact${m.count === 1 ? "" : "s"} about ${m.child}`;
        setTimeout(() => (note.textContent = ""), 4000);
        break;
    }
  }

  // ---------------------------------------------------------------- Santa's voice
  function newUtt(id) {
    maxSeen = Math.max(maxSeen, id);
    if (id < deadBelow) return;
    utt.set(id, { next: 0, sources: new Set(), ended: false, startedSent: false });
  }
  function onAudio(buf) {
    const id = new DataView(buf).getUint32(0, true);
    if (id < deadBelow || !ctx) return;
    if (!utt.has(id)) newUtt(id);
    const u = utt.get(id);
    const pcm = new Int16Array(buf, 4);
    const ab = ctx.createBuffer(1, pcm.length, 24000);
    const ch = ab.getChannelData(0);
    for (let i = 0; i < pcm.length; i++) ch[i] = pcm[i] / 32768;
    const src = ctx.createBufferSource();
    src.buffer = ab;
    src.connect(ctx.destination);               // Santa's voice goes straight to the speakers, as before
    try { src.connect(voiceMeter()); } catch (e) {}   // the aura only listens in; it can never block the sound
    const t = Math.max(ctx.currentTime + 0.03, u.next);
    src.start(t);
    u.next = t + ab.duration;
    u.sources.add(src);
    if (!u.startedSent) {
      u.startedSent = true;
      setTimeout(() => { if (id >= deadBelow) send({ type: "playback_started", id }); },
        Math.max(0, (t - ctx.currentTime) * 1000));
    }
    pic.classList.add("speaking");
    src.onended = () => { u.sources.delete(src); maybeEnded(id); };
  }
  function maybeEnded(id) {
    const u = utt.get(id);
    if (!u || !u.ended || u.sources.size) return;
    utt.delete(id);
    if (!utt.size) pic.classList.remove("speaking");
    if (id >= deadBelow) send({ type: "playback_ended", id });
  }
  function stopAll() {
    deadBelow = Math.max(deadBelow, maxSeen + 1);
    for (const [id, u] of utt) {
      deadBelow = Math.max(deadBelow, id + 1);
      for (const s of u.sources) { try { s.onended = null; s.stop(); } catch (e) {} }
    }
    utt.clear();
    pic.classList.remove("speaking");
  }

  // ---------------------------------------------------------------- aura: glow around the picture follows Santa's voice
  // Santa's voice (only) is also fed to an analyser that is NOT on the way to the speakers (a side tap). Each animation
  // frame turns its loudness into --lv (0..1) on the picture, and the CSS glow grows with it. Quick to rise, slower to
  // fade; silence fades it out.
  let analyser = null, level = 0;
  function voiceMeter() {
    if (!analyser) {
      analyser = ctx.createAnalyser();
      analyser.fftSize = 1024;
      const buf = new Float32Array(analyser.fftSize);
      const tick = () => {
        analyser.getFloatTimeDomainData(buf);
        let sum = 0;
        for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
        const target = Math.min(1, Math.sqrt(Math.sqrt(sum / buf.length) * 4));   // sqrt lifts quiet syllables
        level += (target - level) * (target > level ? 0.5 : 0.12);
        if (level < 0.005) level = 0;
        pic.style.setProperty("--lv", level.toFixed(3));
        requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    }
    return analyser;
  }

  // ---------------------------------------------------------------- ring tone (generated, no recorded audio)
  // The ring is the first line of the Jingle Bells chorus (public domain), as bell tones with a sleigh-bell shimmer
  // on each beat: about 2 s, played once. The server keeps ringing at least 2 s, so with the model warm it fills the
  // ring. The server's ring_stop lets the last note fade out; Hang up and a lost connection cut it at once.
  const TUNE = [[659.25, 1], [659.25, 1], [659.25, 2], [659.25, 1], [659.25, 1], [659.25, 2],   // jin-gle bells x2
                [659.25, 1], [783.99, 1], [523.25, 1.5], [587.33, 0.5], [659.25, 2]];          // jin-gle all the way
  const BEAT = 0.15;                              // seconds per beat: the last note starts at 1.8 s
  let noiseBuf = null;
  function bell(f, t, out, nodes) {
    for (const [mult, peak] of [[1, 0.13], [2, 0.05], [3.01, 0.02]]) {   // a bright bell: base note + overtones
      const o = ctx.createOscillator(), g = ctx.createGain();
      o.frequency.value = f * mult;
      g.gain.setValueAtTime(0, t);
      g.gain.linearRampToValueAtTime(peak, t + 0.005);
      g.gain.exponentialRampToValueAtTime(0.0008, t + 0.45);
      o.connect(g); g.connect(out); o.start(t); o.stop(t + 0.5);
      nodes.push(o);
    }
  }
  function shimmer(t, out, nodes) {               // a tiny burst of filtered noise: sleigh bells
    if (!noiseBuf) {
      noiseBuf = ctx.createBuffer(1, Math.floor(ctx.sampleRate * 0.1), ctx.sampleRate);
      const d = noiseBuf.getChannelData(0);
      for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
    }
    const src = ctx.createBufferSource(), hp = ctx.createBiquadFilter(), g = ctx.createGain();
    src.buffer = noiseBuf; hp.type = "highpass"; hp.frequency.value = 7000;
    g.gain.setValueAtTime(0.035, t); g.gain.exponentialRampToValueAtTime(0.0005, t + 0.08);
    src.connect(hp); hp.connect(g); g.connect(out); src.start(t); src.stop(t + 0.1);
    nodes.push(src);
  }
  function startRing() {
    if (!ctx || ring) return;
    const out = ctx.createGain(); out.connect(ctx.destination);
    const nodes = [], t0 = ctx.currentTime + 0.05;
    let t = t0;
    for (const [f, beats] of TUNE) { bell(f, t, out, nodes); t += beats * BEAT; }
    for (let x = t0; x < t - BEAT; x += BEAT) shimmer(x, out, nodes);
    ring = { out, nodes };
  }
  function stopRing(now = false) {
    if (!ring) return;
    if (now) {
      try { ring.out.gain.cancelScheduledValues(0); ring.out.gain.value = 0; } catch (e) {}
      for (const n of ring.nodes) { try { n.stop(); } catch (e) {} }
    }
    ring = null;                                  // otherwise the jingle (already scheduled) just finishes
  }

  // ---------------------------------------------------------------- microphone
  async function startMic() {
    if (micStream) return;
    micStream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    await ctx.audioWorklet.addModule("/static/worklet.js");
    srcNode = ctx.createMediaStreamSource(micStream);
    micNode = new AudioWorkletNode(ctx, "mic16k");
    micNode.port.onmessage = (ev) => { if (ws && ws.readyState === 1 && state !== "IDLE") ws.send(ev.data); };
    srcNode.connect(micNode);   // not connected to the speakers
  }
  // Say why the mic failed, so a grown-up knows what to fix.
  function micError(e) {
    if (!window.isSecureContext || !navigator.mediaDevices) {
      return "Microphone needs a secure page: open the https:// address and trust the certificate";
    }
    const n = (e && e.name) || "";
    if (n === "NotAllowedError" || n === "SecurityError") return "Microphone blocked: allow it for this site in the browser settings";
    if (n === "NotFoundError" || n === "OverconstrainedError") return "No microphone found on this device";
    if (n === "NotReadableError") return "Microphone is busy: close other apps using it, then try again";
    return `Microphone error: ${n || "unknown"}${e && e.message ? ` (${e.message})` : ""}`;
  }
  function stopMic() {
    if (micStream) micStream.getTracks().forEach((t) => t.stop());
    try { srcNode && srcNode.disconnect(); micNode && micNode.disconnect(); } catch (e) {}
    micStream = srcNode = micNode = null;
  }

  // ---------------------------------------------------------------- buttons
  big.onclick = async () => {
    if (state === "IDLE") {
      lostNote = null;
      if (!ctx) ctx = new (window.AudioContext || window.webkitAudioContext)();
      await ctx.resume();
      try { await startMic(); } catch (e) { stopMic(); setStatus(micError(e)); return; }
      send({ type: "call" });
    } else {
      stopAll(); stopRing(true);  // silence at once, before the server even answers
      send({ type: "hangup" });
    }
  };
  $("guest").onclick = () => send({ type: "set_child", name: null });
  $("forget").onclick = () => send({ type: "forget_last" });
  $("dev").onclick = () => { overlay.style.display = overlay.style.display === "block" ? "none" : "block"; };
  $("adultBtn").onclick = () => {             // grown-ups bar, hidden until the corner button is pressed
    const open = $("adult").classList.toggle("open");
    $("adultBtn").classList.toggle("open", open);
    $("adultBtn").setAttribute("aria-expanded", String(open));
  };

  function clock() {
    if (callStart === null) return;
    const s = Math.floor((Date.now() - callStart) / 1000);
    subEl.textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  }
  setInterval(clock, 1000);

  function render() {
    document.body.dataset.state = state;        // CSS: ripple rings while RINGING
    const answered = !(state in SUB);           // GREETING, LISTENING, THINKING, SPEAKING
    if (answered && callStart === null) callStart = Date.now();
    if (!answered) { callStart = null; subEl.textContent = SUB[state]; } else clock();
    setStatus(LABEL[state] || (state === "IDLE" && lostNote) || "");
    const inCall = state !== "IDLE";
    big.className = inCall ? "hang" : "call";   // CSS swaps the icon: handset on green, X on red
    big.setAttribute("aria-label", inCall ? "Hang up" : "Call Santa");
    kidsEl.replaceChildren(...children.map((n) => {
      const b = document.createElement("button");
      b.textContent = n;
      b.className = active === n ? "on" : "";
      b.onclick = () => send({ type: "set_child", name: n });
      return b;
    }));
    $("guest").className = active ? "" : "on";
  }

  const lastMetrics = [];
  function showMetrics(m) {
    lastMetrics.unshift(m); lastMetrics.length = Math.min(lastMetrics.length, 6);
    const f = (x) => (x === undefined ? "  –  " : x.toFixed(2).padStart(5));
    overlay.textContent = "seconds from end of speech (T_end)\n  stt   tok  sent   tts  play | wait total\n" +
      lastMetrics.map((x) => `${f(x.stt_done_from_end)} ${f(x.first_token_from_end)} ${f(x.first_sentence_from_end)} ` +
        `${f(x.first_tts_from_end)} ${f(x.first_played_from_end)} | ${f(x.endpoint_wait)} ${f(x.total_from_last)}` +
        `${x.extended ? " ext" : ""}${x.say_again ? " again" : ""}${x.fallback ? " fb" : ""}`).join("\n");
  }

  connect();
  watchdog.start();
})();
