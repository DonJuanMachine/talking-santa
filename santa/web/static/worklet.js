// AudioWorklet: microphone -> 16 kHz mono int16, posted in 512-sample frames (32 ms).
// The AudioContext rate is whatever the browser gives (often 48 kHz); we never rely on sampleRate being honoured.
class Mic16k extends AudioWorkletProcessor {
  constructor() {
    super();
    this.step = sampleRate / 16000;    // input samples per output sample
    this.pos = 0;                      // read position; -1 means "the last sample of the previous block"
    this.prev = 0;
    this.lp = 0;                       // one-pole low-pass (anti-aliasing before decimation)
    this.alpha = Math.min(1, (2 * Math.PI * 7000) / sampleRate);
    this.out = new Int16Array(512);
    this.n = 0;
  }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch || ch.length === 0) return true;
    const x = new Float32Array(ch.length);
    for (let i = 0; i < ch.length; i++) { this.lp += this.alpha * (ch[i] - this.lp); x[i] = this.lp; }
    const at = (i) => (i < 0 ? this.prev : x[i]);
    while (this.pos <= x.length - 1) {
      const i = Math.floor(this.pos), f = this.pos - i;
      const v = Math.max(-1, Math.min(1, at(i) + (at(i + 1 > x.length - 1 ? x.length - 1 : i + 1) - at(i)) * f));
      this.out[this.n++] = v < 0 ? v * 0x8000 : v * 0x7fff;
      if (this.n === 512) { this.port.postMessage(this.out.buffer.slice(0)); this.n = 0; }
      this.pos += this.step;
    }
    this.pos -= x.length;              // now in [-1, step - 1): continues in the next block
    this.prev = x[x.length - 1];
    return true;
  }
}
registerProcessor("mic16k", Mic16k);
