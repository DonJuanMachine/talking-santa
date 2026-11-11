#!/usr/bin/env python3
"""Stage J1: voice audition kit. Renders WAVs for Don to judge by ear, checks determinism, builds the audition page.
Nothing here judges how a voice sounds.

    j1_audition.py kokoro        Kokoro v1.0 (kokoro-onnx), run with the Stage H venv  ~/.venvs/talking-santa-h
    j1_audition.py pocket-fetch  one-time download of Kyutai Pocket TTS files (network), venv ~/.venvs/talking-santa-j
    j1_audition.py pocket        Kyutai Pocket TTS, offline (HF_HUB_OFFLINE=1), venv ~/.venvs/talking-santa-j
    j1_audition.py page          builds tools/probes/out/voice_audition_J/index.html from the two manifests (any python)

Output: tools/probes/out/voice_audition_J/ (gitignored): <engine>/<folder>/<file>.wav, manifest_<engine>.json,
index.html. Determinism results: tools/probes/out/j1_determinism_<engine>.json.
Run with PYTHONDONTWRITEBYTECODE=1. After pocket-fetch, every mode runs with no network.
"""
import hashlib
import html
import json
import os
import sys
import time
import wave
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
AUD = OUT / "voice_audition_J"
MODELS = Path.home() / ".cache" / "talking-santa" / "models"

LINES = {
    "L1": "Ho ho ho! Hello, little friend!",
    "L2": "Oh, a kitty named Mittens! I love kitties. What color is she?",
    "L3": "That sounds wonderful. I'll tell my elves!",
    "L4": "The reindeer love carrots and snowy nights at the North Pole.",
    "L5": "It's time for me to go back to the workshop. Are you ready to say goodbye?",
}
KOKORO_LINES = ["L1", "L2", "L5"]
KOKORO_SPEEDS = [0.95, 1.0]
BLENDS = [("am_michael", "bm_george", 70, 30), ("am_santa", "bm_fable", 70, 30), ("am_onyx", "bm_george", 70, 30),
          ("am_michael", "am_santa", 70, 30)]
PUNCT_VOICES = ["am_michael", "bm_fable"]
PUNCT_L2 = {
    "L2a": "Oh, a kitty named Mittens! I love kitties. What color is she?",
    "L2b": "Oh... a kitty named Mittens! I love kitties. What color is she?",
    "L2c": "Oh, a kitty named Mittens! Ooh, I love kitties. And what color is she?",
}
HOHO_VOICES = ["am_michael", "bm_fable"]
HOHO_SPEEDS = [0.90, 0.93, 0.96, 1.00, 1.03]
HOHO_TEXTS = {"hoho": "Ho ho ho!", "hoho-commas": "Ho, ho, ho!", "hoho-hello": "Ho ho ho! Hello!"}
POCKET_TAKES = 3          # unseeded repeat takes of L1, to hear the built-in variation


def write_wav(path: Path, samples, sr: int) -> float:
    import numpy as np
    path.parent.mkdir(parents=True, exist_ok=True)
    a = np.asarray(samples, dtype=np.float32).reshape(-1)
    pcm = (np.clip(a, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return round(len(a) / sr, 2)


def digest(samples) -> str:
    import numpy as np
    return hashlib.sha256(np.ascontiguousarray(np.asarray(samples, dtype=np.float32)).tobytes()).hexdigest()


def rel(p: Path) -> str:
    return p.relative_to(AUD).as_posix()


class Manifest:
    def __init__(self, engine: str):
        self.engine, self.rows, self.n = engine, [], 0

    def row(self, section: str, label: str, **meta) -> list:
        files: list = []
        self.rows.append({"section": section, "label": label, "files": files, **meta})
        return files

    def add(self, files: list, line_id: str, text: str, path: Path, seconds: float):
        files.append({"line": line_id, "text": text, "path": rel(path), "seconds": seconds})
        self.n += 1

    def save(self, extra: dict):
        AUD.mkdir(parents=True, exist_ok=True)
        (AUD / f"manifest_{self.engine}.json").write_text(json.dumps({"engine": self.engine, "wav_count": self.n,
                                                                      **extra, "rows": self.rows}, indent=1))


# ---------------------------------------------------------------------------------------------------- Kokoro
def cmd_kokoro(argv):
    import numpy as np
    import onnxruntime as ort
    import kokoro_onnx
    from kokoro_onnx import Kokoro
    sess = ort.InferenceSession(str(MODELS / "kokoro-v1.0.onnx"), ort.SessionOptions(),
                                providers=["CPUExecutionProvider"])
    k = Kokoro.from_session(sess, str(MODELS / "voices-v1.0.bin"))
    voices = [v for v in k.get_voices() if v.startswith(("am_", "bm_"))]
    print("Kokoro male voices (am_/bm_):", voices, flush=True)
    root = AUD / "kokoro"
    m = Manifest("kokoro")
    t0 = time.perf_counter()

    def say(text, voice, speed):
        s, sr = k.create(text, voice=voice, speed=speed, lang="en-us")
        assert sr == 24000
        return s

    for v in voices:
        for sp in KOKORO_SPEEDS:
            files = m.row("voices", f"Kokoro {v} @ {sp:.2f}", voice=v, speed=sp)
            for lid in KOKORO_LINES:
                p = root / v / f"{v}_{sp:.2f}_{lid}.wav"
                m.add(files, lid, LINES[lid], p, write_wav(p, say(LINES[lid], v, sp), 24000))
    for a, b, wa, wb in BLENDS:
        style = (wa / 100) * k.get_voice_style(a) + (wb / 100) * k.get_voice_style(b)
        name = f"blend_{a}{wa}_{b}{wb}"
        for sp in KOKORO_SPEEDS:
            files = m.row("blends", f"Kokoro blend {a}+{b} {wa}/{wb} @ {sp:.2f}", voice=f"{a}+{b}",
                          blend=f"{wa}/{wb}", speed=sp)
            for lid in KOKORO_LINES:
                p = root / name / f"{name}_{sp:.2f}_{lid}.wav"
                m.add(files, lid, LINES[lid], p, write_wav(p, say(LINES[lid], style.astype(np.float32), sp), 24000))
    for v in PUNCT_VOICES:
        files = m.row("punctuation", f"Kokoro {v} @ 0.95, L2 punctuation a/b/c", voice=v, speed=0.95)
        for vid, text in PUNCT_L2.items():
            p = root / "punctuation" / f"{v}_0.95_{vid}.wav"
            m.add(files, vid, text, p, write_wav(p, say(text, v, 0.95), 24000))
    for v in HOHO_VOICES:
        for tid, text in HOHO_TEXTS.items():
            files = m.row("hohoho", f"Kokoro {v} \"{text}\" at 5 speeds", voice=v, text_id=tid)
            for sp in HOHO_SPEEDS:
                p = root / "hohoho" / v / f"{v}_{tid}_{sp:.2f}.wav"
                m.add(files, f"{sp:.2f}", text, p, write_wav(p, say(text, v, sp), 24000))
    render_s = time.perf_counter() - t0

    # Determinism: same text, voice, speed twice in this process, and once more in a fresh session.
    det = []
    sess2 = ort.InferenceSession(str(MODELS / "kokoro-v1.0.onnx"), ort.SessionOptions(),
                                 providers=["CPUExecutionProvider"])
    k2 = Kokoro.from_session(sess2, str(MODELS / "voices-v1.0.bin"))
    for v, sp, lid in [("am_michael", 0.9, "L1"), ("am_michael", 1.0, "L2"), ("bm_fable", 0.95, "L5"),
                       ("am_santa", 1.0, "L1")]:
        a = say(LINES[lid], v, sp)
        b = say(LINES[lid], v, sp)
        c, _ = k2.create(LINES[lid], voice=v, speed=sp, lang="en-us")
        det.append({"voice": v, "speed": sp, "line": lid, "same_process_identical": digest(a) == digest(b),
                    "fresh_session_identical": digest(a) == digest(c), "sha256": digest(a)[:16],
                    "max_abs_diff_fresh": float(np.max(np.abs(np.asarray(a) - np.asarray(c))))
                    if len(a) == len(c) else "length differs"})
    # WAV files on disk: re-render one file and compare bytes.
    p1 = root / "am_michael" / "am_michael_1.00_L1.wav"
    p2 = OUT / "j1_tmp_det.wav"
    write_wav(p2, say(LINES["L1"], "am_michael", 1.0), 24000)
    wav_identical = p1.read_bytes() == p2.read_bytes()
    p2.unlink()
    res = {"engine": "kokoro", "kokoro_onnx": getattr(kokoro_onnx, "__version__", "0.6.1"),
           "onnxruntime": ort.__version__, "rows": det, "wav_file_byte_identical": wav_identical}
    (OUT / "j1_determinism_kokoro.json").write_text(json.dumps(res, indent=1))
    m.save({"voices_enumerated": voices, "render_s": round(render_s, 1),
            "provenance": "Kokoro-82M v1.0 by hexgrad (Apache-2.0), ONNX export by thewh1teagle/kokoro-onnx; "
                          "builds on StyleTTS 2 (Columbia University). Country of hexgrad unverified."})
    print(json.dumps(res, indent=1))
    print(f"Kokoro: {m.n} WAVs in {render_s:.0f} s")


# ----------------------------------------------------------------------------------------------- Pocket TTS
def pocket_voices():
    from pocket_tts.utils.utils import _ORIGINS_OF_PREDEFINED_VOICES
    return dict(_ORIGINS_OF_PREDEFINED_VOICES)


def cmd_pocket_fetch(argv):
    """Network allowed here only. Downloads the default English model (ungated without-voice-cloning weights when
    not logged in to Hugging Face) and every built-in English voice embedding."""
    from pocket_tts import TTSModel
    model = TTSModel.load_model()
    for name in pocket_voices():
        model.get_state_for_audio_prompt(name)
    print("fetched", len(pocket_voices()), "voices")


def cmd_pocket(argv):
    import numpy as np
    import torch
    import pocket_tts
    from pocket_tts import TTSModel
    assert os.environ.get("HF_HUB_OFFLINE") == "1", "run with HF_HUB_OFFLINE=1"
    t0 = time.perf_counter()
    model = TTSModel.load_model()
    load_s = time.perf_counter() - t0
    sr = model.sample_rate
    voices = pocket_voices()
    root = AUD / "pocket"
    m = Manifest("pocket")
    states = {}
    t0 = time.perf_counter()
    for name, origin in voices.items():
        states[name] = model.get_state_for_audio_prompt(name)
        files = m.row("voices", f"Pocket {name}", voice=name, origin=origin)
        for lid, text in LINES.items():
            p = root / name / f"{name}_{lid}.wav"
            m.add(files, lid, text, p, write_wav(p, model.generate_audio(states[name], text).numpy(), sr))
        print(name, "done", flush=True)
    for name in ("alba", "michael"):     # library default voice + one other; no sound judgement implied
        files = m.row("takes", f"Pocket {name}: {POCKET_TAKES} unseeded takes of L1", voice=name)
        for i in range(POCKET_TAKES):
            p = root / "takes" / f"{name}_L1_take{i + 1}.wav"
            m.add(files, f"take {i + 1}", LINES["L1"], p,
                  write_wav(p, model.generate_audio(states[name], LINES["L1"]).numpy(), sr))
    render_s = time.perf_counter() - t0

    det = []
    for name, lid in [("alba", "L1"), ("michael", "L2"), ("george", "L5")]:
        a = model.generate_audio(states[name], LINES[lid]).numpy()
        b = model.generate_audio(states[name], LINES[lid]).numpy()
        torch.manual_seed(1234)
        c = model.generate_audio(states[name], LINES[lid]).numpy()
        torch.manual_seed(1234)
        d = model.generate_audio(states[name], LINES[lid]).numpy()
        det.append({"voice": name, "line": lid, "unseeded_identical": digest(a) == digest(b),
                    "unseeded_lengths_s": [round(len(a) / sr, 2), round(len(b) / sr, 2)],
                    "seeded_identical": digest(c) == digest(d),
                    "seeded_max_abs_diff": float(np.max(np.abs(c - d))) if len(c) == len(d) else "length differs"})
    res = {"engine": "pocket", "pocket_tts": getattr(pocket_tts, "__version__", "4.0.1"), "torch": torch.__version__,
           "rows": det}
    (OUT / "j1_determinism_pocket.json").write_text(json.dumps(res, indent=1))
    m.save({"voices_enumerated": list(voices), "load_s": round(load_s, 2), "render_s": round(render_s, 1),
            "sample_rate": sr, "temperature": "library default (0.3)",
            "provenance": "Kyutai Pocket TTS 4.0.1 by Kyutai (France), code MIT, weights CC-BY-4.0 "
                          "(kyutai/pocket-tts-without-voice-cloning). Built-in voices are Kyutai's precomputed "
                          "embeddings of the recordings listed per voice."})
    print(json.dumps(res, indent=1))
    print(f"Pocket: {m.n} WAVs in {render_s:.0f} s (load {load_s:.1f} s)")


# --------------------------------------------------------------------------------------------------- page
SECTION_NOTES = {
    ("kokoro", "voices"): "Every American (am_) and British (bm_) male voice in voices-v1.0.bin, at speeds 0.95 and "
                          "1.0. Lines L1, L2, L5. The app today uses am_michael at 0.9 (not on this page; it is in "
                          "the Stage H folder voice_audition/).",
    ("kokoro", "blends"): "Two voices mixed by averaging their style vectors (weights in the label).",
    ("kokoro", "punctuation"): "Line L2 written three ways: a = as given, b = \"Oh...\", c = \"Ooh\" and \"And\" "
                               "added. Same voice and speed.",
    ("kokoro", "hohoho"): "Kokoro gives the same audio every time for the same text, voice and speed. These rows "
                          "show what rotating takes would sound like: the same \"Ho ho ho\" text at five speeds.",
    ("pocket", "voices"): "Every built-in voice the library names, with the English model. The library gives each "
                          "voice only a name and the recording it was made from (shown under the label); the README "
                          "adds a language tag. It gives no gender or accent, so all are included. Pocket TTS has "
                          "no speed setting.",
    ("pocket", "takes"): "Pocket TTS samples randomly, so the same line comes out a little different each time. "
                         "Three takes of L1 with no seed.",
}
SECTION_TITLES = {"voices": "Voices", "blends": "Blends", "punctuation": "Punctuation variants",
                  "hohoho": "\"Ho ho ho\" variants", "takes": "Repeat takes"}


def cmd_page(argv):
    mans = {}
    for eng in ("kokoro", "pocket"):
        p = AUD / f"manifest_{eng}.json"
        if p.exists():
            mans[eng] = json.loads(p.read_text())
    speed = {}
    sp = OUT / "j1_bench.json"
    if sp.exists():
        b = json.loads(sp.read_text())
        for cell in b.get("cells", []):
            speed.setdefault(cell["engine"], []).append(cell)
    esc = html.escape
    parts = []
    for eng, man in mans.items():
        title = "Kokoro v1.0 (installed today)" if eng == "kokoro" else "Kyutai Pocket TTS (candidate)"
        cells = speed.get(eng, [])
        sline = "; ".join(f"{c['label']}: L2 first audio median {c['ttfa']['L2']['p50']:.2f} s"
                          + (f" (first chunk {c['first_chunk']['L2']['p50']:.2f} s)" if c.get("first_chunk") else "")
                          + f", RTF {c['rtf_p50']:.2f}" for c in cells) or "see docs/history/STAGE_J1.md"
        parts.append(f'<section><h2>{esc(title)}</h2><p class="note"><b>Provenance:</b> {esc(man["provenance"])}'
                     f'<br><b>Speed (this Mac, Gemma loaded):</b> {esc(sline)}<br>{man["wav_count"]} files.</p>')
        sections = []
        for r in man["rows"]:
            if r["section"] not in sections:
                sections.append(r["section"])
        for sec in sections:
            parts.append(f'<h3>{esc(SECTION_TITLES[sec])}</h3><p class="note">{esc(SECTION_NOTES[(eng, sec)])}</p>')
            for r in [r for r in man["rows"] if r["section"] == sec]:
                sub = f'<div class="sub">{esc(r["origin"])}</div>' if r.get("origin") else ""
                cols = "".join(f'<button class="play" title="{esc(f["text"])}" data-src="{esc(f["path"])}">'
                               f'▶ {esc(f["line"])}</button>' for f in r["files"])
                parts.append(f'<div class="row"><label class="star"><input type="checkbox" '
                             f'data-label="{esc(r["label"])}"> ★</label><div class="lab">{esc(r["label"])}{sub}</div>'
                             f'<div class="clips">{cols}</div></div>')
        parts.append("</section>")
    legend = "".join(f"<li><b>{k}</b> {esc(v)}</li>" for k, v in LINES.items())
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Santa Voice Audition</title>
<style>
:root {{ --bg:#fbfaf7; --fg:#1d1d1f; --muted:#666; --line:#e3e0d8; --card:#fff; --accent:#b3261e; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#17171a; --fg:#eee; --muted:#aaa; --line:#333; --card:#202024;
  --accent:#ff8a80; }} }}
body {{ background:var(--bg); color:var(--fg); font:15px/1.45 -apple-system, system-ui, sans-serif; margin:0;
  padding:16px; }}
main {{ max-width:1200px; margin:0 auto; }}
h1 {{ margin:.2em 0; }} h2 {{ margin-top:2em; border-bottom:2px solid var(--accent); }} h3 {{ margin:1.4em 0 .3em; }}
.note {{ color:var(--muted); margin:.2em 0 .8em; }}
.row {{ display:flex; flex-wrap:wrap; gap:8px 14px; align-items:center; background:var(--card);
  border:1px solid var(--line); border-radius:8px; padding:8px 10px; margin:6px 0; }}
.lab {{ min-width:230px; flex:0 0 260px; font-weight:600; }} .sub {{ font-weight:400; font-size:12px;
  color:var(--muted); word-break:break-all; }}
.clips {{ display:flex; flex-wrap:wrap; gap:6px 10px; flex:1; }}
button.play {{ background:var(--card); color:var(--fg); border:1px solid var(--line); padding:5px 12px;
  min-width:4.5em; text-align:left; }}
button.play:hover {{ border-color:var(--accent); }}
button.play.on {{ background:var(--accent); color:#fff; border-color:var(--accent); }}
.star {{ font-size:20px; cursor:pointer; user-select:none; }} .star input {{ width:18px; height:18px; }}
.bar {{ position:sticky; top:0; background:var(--bg); padding:8px 0; border-bottom:1px solid var(--line); z-index:1;
  display:flex; gap:10px; align-items:center; flex-wrap:wrap; }}
button {{ font:inherit; padding:6px 14px; border-radius:6px; border:1px solid var(--accent); background:var(--accent);
  color:#fff; cursor:pointer; }}
textarea {{ width:100%; box-sizing:border-box; min-height:4em; font:13px ui-monospace, monospace; background:var(--card);
  color:var(--fg); border:1px solid var(--line); }}
@media (max-width:640px) {{ .lab {{ flex-basis:100%; }} audio {{ width:180px; }} }}
</style></head><body><main>
<h1>Santa voice audition (Stage J1)</h1>
<p class="note">Listen and star the rows you like. Nothing here was ranked by sound. Hover a line tag to see its text.
The voice that ships is chosen in Stage J2.</p>
<ul class="note">{legend}</ul>
<div class="bar"><button id="copy">Copy my favourites</button><span id="count" class="note">0 starred</span>
<span id="msg" class="note"></span></div>
<textarea id="out" readonly placeholder="Starred rows appear here too, so you can copy them by hand."></textarea>
{''.join(parts)}
</main>
<script>
const boxes = [...document.querySelectorAll('.star input')];
const out = document.getElementById('out');
function starred() {{ return boxes.filter(b => b.checked).map(b => b.dataset.label); }}
function refresh() {{ const s = starred(); out.value = s.join('\\n');
  document.getElementById('count').textContent = s.length + ' starred';
  try {{ localStorage.setItem('j1stars', JSON.stringify(s)); }} catch (e) {{}} }}
try {{ const saved = JSON.parse(localStorage.getItem('j1stars') || '[]');
  boxes.forEach(b => {{ if (saved.includes(b.dataset.label)) b.checked = true; }}); }} catch (e) {{}}
boxes.forEach(b => b.addEventListener('change', refresh)); refresh();
document.getElementById('copy').addEventListener('click', async () => {{
  const text = starred().join('\\n'); const msg = document.getElementById('msg');
  try {{ await navigator.clipboard.writeText(text); msg.textContent = 'Copied.'; }}
  catch (e) {{ out.focus(); out.select(); const ok = document.execCommand && document.execCommand('copy');
    msg.textContent = ok ? 'Copied.' : 'Select the box below and copy it.'; }} }});
// One shared player: click a button to play its clip, click again to stop.
const player = new Audio(); let current = null;
function stop() {{ player.pause(); if (current) current.classList.remove('on'); current = null; }}
player.addEventListener('ended', stop);
document.querySelectorAll('button.play').forEach(b => b.addEventListener('click', () => {{
  const same = current === b; stop(); if (same) return;
  current = b; b.classList.add('on'); player.src = b.dataset.src;
  player.play().catch(() => stop()); }}));
</script></body></html>
"""
    (AUD / "index.html").write_text(page)
    print("wrote", AUD / "index.html", {k: v["wav_count"] for k, v in mans.items()})


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    fn = globals().get("cmd_" + cmd.replace("-", "_"))
    if not fn:
        print(__doc__)
        sys.exit(1)
    fn(sys.argv[2:])
