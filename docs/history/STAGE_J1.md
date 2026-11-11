# Stage J1 report (2026-11-09): voice audition kit

**Outcome: done.** The audition page is built: 279 WAVs from two engines, all rendered with the network blocked.
Speed and memory are measured, and provenance is recorded. Nothing in the app changed. No voice is ranked by sound:
everything about sound is **FOR DON (by ear)**.

- **Snapshot:** `.snapshots/pre-implJ1-20261109-210309.tar.gz`
- **Audition page:** `tools/probes/out/voice_audition_J/index.html` (gitignored). Open it by double-clicking or with
  `open tools/probes/out/voice_audition_J/index.html`. It needs no server and no network.
- **Kokoro** (installed today): 138 WAVs, covering all 13 American and British male voices, 4 blends, punctuation
  variants and "Ho ho ho" variants. The output is **byte-identical every time** for the same text, voice and speed.
- **Kyutai Pocket TTS** (new candidate): 141 WAVs, covering all 27 built-in voices plus repeat takes.
  - **Provenance:** Kyutai (France). Code MIT, weights CC-BY-4.0. PyPI upload attested from `kyutai-labs/pocket-tts`.
    No Chinese-developed model or dependency was found.
  - **Determinism:** output is random each run unless seeded.
  - **Speed:** on this Mac it was faster than Kokoro in every cell. L2 whole-sentence median was 0.95–1.08 s against
    Kokoro's 2.71 s baseline, and its first streamed audio arrives in about 0.06 s.
- **Caveat on speed:** Kokoro measured about 2.5× slower today than in Stage H (0.51 s → 1.3–1.5 s for the same
  5-word line), with the same venv and packages. The Mac had background load (Safari/WebKit, Microsoft Defender,
  Spotlight). Kokoro uses every core, so it suffers more from this than Pocket (1 thread). Both passes and both
  orders gave the same ordering, but treat the size of the gap as indicative only (§3).

## 1. What was installed, and provenance

New scratch venv **`~/.venvs/talking-santa-j`** (outside the repo):
- Python 3.12.13, the same Homebrew python@3.12 that was already installed; no new Homebrew packages;
- a `.pth` that sets `sys.dont_write_bytecode`;
- the Stage H venv was not touched: its `pip freeze` still matches `out/h_versions.txt`.

Command: `pip install --only-binary=:all: pocket-tts==4.0.1 soundfile psutil` (soundfile and psutil are for this
stage's scripts).

**Pocket TTS checks before installing:**
- **PyPI** `pocket-tts` 4.0.1 (uploaded 2026-10-21). The metadata names no author. The PyPI provenance attestation
  shows a Trusted Publisher: GitHub, `kyutai-labs/pocket-tts`, workflow `publish-package.yml`.
  - Wheel sha256: `a6baf5fd9195399a632d7ef1cb75d4ee772b8d3534c85b90164b39c687a69961`.
- **GitHub** `kyutai-labs` is an organisation: "kyutai", kyutai.org, France. The repo license is MIT.
- **Project page:** https://kyutai-labs.github.io/pocket-tts. The model card cites Kyutai's own paper
  (arXiv 2509.06926) and Kyutai's Mimi codec.
- **Package source** was searched for CosyVoice, Qwen, F5, Fish, IndexTTS, MeloTTS, Chatterbox, S3Tokenizer,
  sherpa/k2-fsa and the major Chinese labs: no matches.
  - The README lists community ports, including sherpa-onnx (k2-fsa). They are **not** used and not installed.
  - The optional Rust binary (built on gradium-ai/xn-ptts) is not used either.
- **Weights:**
  - When not logged in to Hugging Face, the library loads **`kyutai/pocket-tts-without-voice-cloning`**. This repo
    is ungated, CC-BY-4.0, pinned revision `a7056f50…`.
  - `kyutai/pocket-tts` (with voice cloning) is gated and was not used.
  - English `model.safetensors`: 219,029,196 bytes, sha256 `4c56cbd171c63e8a26ea61f5d48b8a0cd8f3c51f4652c0ab9a19bfcced8c931d`.
- **Where files are stored:** `~/.cache/huggingface/hub/models--kyutai--pocket-tts-without-voice-cloning/`, holding
  the model, the tokenizer and 27 voice embeddings (`languages/english/embeddings/*.safetensors`).
  - These were downloaded once by `j1_audition.py pocket-fetch`. Everything after that ran offline.
  - `~/.cache/pocket_tts/` is created by the library but stayed empty.

**Dependencies pulled in** (all from `pip freeze` of the new venv):
- **Direct:** einops, fastapi, huggingface-hub, numpy, pydantic, python-multipart, requests, safetensors, scipy,
  sentencepiece, tokenizers, torch, typer, typing-extensions, uvicorn.
- **Transitive:** annotated-doc, annotated-types, anyio, certifi, cffi, charset-normalizer, click, filelock, fsspec,
  h11, hf-xet, httpcore2, httpx2, idna, Jinja2, markdown-it-py, MarkupSafe, mdurl, mpmath, networkx,
  opentelemetry-api, packaging, pycparser, pydantic-core, Pygments, PyYAML, rich, setuptools, shellingham, starlette,
  sympy, tqdm, truststore, typing-inspection, urllib3.
- Versions: pocket-tts 4.0.1, torch 2.15.0, numpy 2.5.4, scipy 1.18.1, tokenizers 0.23.3, sentencepiece 0.2.3,
  huggingface_hub 2.4.0, safetensors 0.8.0.
- These are mainstream open-source packages (PyTorch/Meta, Hugging Face, Google sentencepiece, NumPy/SciPy, FastAPI,
  Pydantic and others). **None is from a Chinese developer, and none is a model.** No STOP trigger fired.

**Provenance (style of Stage H §1)**

| Model / component | Developer | Country | License | Source |
|---|---|---|---|---|
| Kokoro-82M v1.0 (unchanged from Stage H) | hexgrad (a handle) | No sign of Chinese development; country unverified. Builds on StyleTTS 2 (Columbia University, USA) | Apache-2.0 | huggingface.co/hexgrad/Kokoro-82M; ONNX from thewh1teagle/kokoro-onnx |
| Kyutai Pocket TTS 4.0.1 (library) | Kyutai | France | MIT | github.com/kyutai-labs/pocket-tts, PyPI `pocket-tts` (attested) |
| Pocket TTS English weights (no voice cloning) | Kyutai | France | CC-BY-4.0 (attribution needed if shipped) | huggingface.co/kyutai/pocket-tts-without-voice-cloning @ a7056f50 |
| Pocket built-in voice embeddings | Kyutai, computed from the recordings below | France | as the recording | same repo, `languages/english/embeddings/` |
| PyTorch 2.15.0 (runtime) | Meta / PyTorch Foundation | USA | BSD-3 | PyPI `torch` |

The recordings behind the Pocket built-in voices, per the library's own table and kyutai/tts-voices:

| Source recording set | Voices | Recording license |
|---|---|---|
| VCTK (University of Edinburgh, UK) | anna, vera, fantine, charles, paul, eponine, azelma, george, mary, jane, michael, eve | CC-BY-4.0 |
| Voice-Zero (LibriVox selection) | bill_boerst, peter_yearsley, stuart_bell, caro_davy | CC0 |
| Unmute voice donations | javert, marius | CC0 |
| Alba MacKenna | alba | CC-BY-4.0 |
| Unmute website (Kyutai's own recording) | estelle | CC0 |
| Expresso (Meta) | cosette | **CC-BY-NC-4.0, non-commercial** |
| EARS (Universität Hamburg) | jean | **CC-BY-NC-4.0, non-commercial** |
| Files in kyutai/pocket-tts (Common Voice IT/ES, CML-TTS NL, and two others) | giovanni, lola, daan, juergen, rafael | not stated per file; not verified |

Family, non-commercial use fits all of these. If Santa were ever shared commercially, avoid cosette and jean.

## 2. Determinism (`out/j1_determinism_kokoro.json`, `out/j1_determinism_pocket.json`)

**Kokoro:**
- The same text, voice and speed gave **identical** samples:
  - twice in the same process: 4 of 4 checks;
  - again in a fresh session: 4 of 4, max difference 0.0;
  - re-written WAV file: byte-identical.
- So a cached "Ho ho ho!" and the canned lines are the exact same take every time.
- The only way to vary them with Kokoro is to vary the input: speed or punctuation (see the "Ho ho ho" variants).

**Pocket TTS:**
- **Unseeded:** never identical (0 of 3). Even the length changes, for example L1 was 3.12 s and then 2.56 s.
- **Seeded** with `torch.manual_seed`: 2 of 3 byte-identical. The third differed by at most 5e-7, which is float noise
  from its threads and inaudible.
- So, left unseeded, each "Ho ho ho" is a new take. That is natural variation, but also less predictable.
- **FOR DON (by ear):** compare the three takes in "Repeat takes".

## 3. Speed and memory (`out/j1_bench.md`, `.json`)

**Setup:**
- Each cell runs in a clean process with `HF_HUB_OFFLINE=1` and the network blocked (`sandbox-exec`, deny network).
- 3 warm-up rounds, then n = 10 per sentence, round-robin.
- **Two passes, the second in reverse order**, pooled to n = 20 per cell and sentence.
- Gemma `ai/gemma4:e4b` was loaded and warmed with a short request before every cell, and confirmed resident before
  and after every cell. It was idle while timing.
- The same sentences for both engines:
  - L1 (6 words);
  - "A puppy sounds wonderful, Emma!" (5 words);
  - L2 (12 words);
  - "My reindeer love carrots, and Rudolph's nose glows so bright on snowy nights!" (13 words).

Time to first audio, whole sentence, p50 / p90 / max in seconds:

| cell | L1 | 5 words | L2 | 13 words | RTF p50 (max) |
|---|---|---|---|---|---|
| **Kokoro am_michael 0.9 (baseline, current app)** | 1.578 / 1.861 / 2.137 | 1.460 / 1.658 / 1.847 | **2.706** / 3.012 / 3.585 | 3.276 / 3.810 / 4.769 | 0.627 (0.887) |
| Kokoro am_michael 1.0 | 1.436 / 1.643 / 1.909 | 1.405 / 1.568 / 2.291 | 2.461 / 2.734 / 3.119 | 2.917 / 3.412 / 3.757 | 0.617 (1.053) |
| Pocket peter_yearsley | 0.634 / 1.192 / 1.466 | 0.458 / 0.874 / 0.971 | 1.078 / 1.928 / 2.250 | 1.045 / 1.976 / 2.696 | 0.224 (0.654) |
| Pocket anna | 0.568 / 0.899 / 1.624 | 0.447 / 0.527 / 1.004 | 0.949 / 1.087 / 2.286 | 1.065 / 1.772 / 2.236 | 0.194 (0.521) |

**Pocket, time to the first streamed chunk** (p50 / p90): L1 0.05–0.06 / 0.10–0.11 s, L2 0.05–0.07 / 0.06–0.16 s.

**How the cells were chosen and what the times mean:**
- For Kokoro, time to first audio is one `create()` call per sentence, as `santa/web/tts.py` does now.
- The second Kokoro cell is speed 1.0, the cheapest setting auditioned: the voice does not change the compute (same
  model, a different style vector), and a higher speed makes fewer output frames.
- The Pocket voices were picked by stored prompt size, to bracket the speed range, **not by sound**:
  - peter_yearsley has the smallest state (3.6 MB);
  - anna has the largest (7.6 MB).

| cell | load s (model + voice + first call), pass 1 / 2 | RSS after load MB | peak RSS MB | threads |
|---|---|---|---|---|
| Kokoro am_michael 0.9 | 1.52 / 1.62 | 552 | 719 | onnxruntime default (all cores) |
| Kokoro am_michael 1.0 | 1.55 / 1.71 | 551 / 533 | 742 | onnxruntime default |
| Pocket peter_yearsley | 3.75 / 4.65 | 858 / 861 | 1034 | 1 (the library's choice) |
| Pocket anna | 3.90 / 3.46 | 876 / 873 | 1034 | 1 |

Pocket uses about 300 MB more RAM and takes about 2 s longer to load than Kokoro. Both are one-off costs at app
start.

**J2 pass bar (informational):** median L2 time to first audio no more than 0.25 s above the baseline measured here,
which means ≤ 2.956 s.
- **All four cells pass.**
- Pocket passes as a whole sentence (0.95–1.08 s) and, if streamed, by a wide margin (about 0.06 s to the first
  chunk).

**Comparison with Stage H (`out/h_tts.md`, am_michael 0.9):**

| sentence | Stage H p50 | today p50 |
|---|---|---|
| 5 words | 0.511 s | 1.460 s |
| 13 words | 1.108 s | 3.276 s |
| RTF | 0.23 | 0.63 |

Why the change, and why the ordering still holds:
- The venv and packages are identical, and the network sandbox is not the cause: there was no difference with or
  without it, in a diagnostic run.
- Kokoro was just as slow with Gemma unloaded, and at 1, 2, 4 and 6 threads. So this is the Mac's state today, not
  this harness.
- Background load was present throughout. The top CPU users before each cell are listed in `out/j1_bench.md`:
  - Safari/WebKit 15–50% across its processes;
  - Microsoft Defender 8–58%;
  - Spotlight indexing the new WAVs.
- Drift between passes:
  - Kokoro L2 2.40 → 2.85 s;
  - Pocket peter_yearsley 0.87 → 1.42 s;
  - Pocket anna 0.92 → 0.98 s.
- Pocket was faster in every pass and every order, and in the first single-pass run (kept as
  `out/j1_bench_firstrun.*`).
- **Re-measure on a quiet Mac in J2 before relying on the size of the gap.**

## 4. What was rendered (`tools/probes/out/voice_audition_J/`, 279 WAVs, 45 MB)

The lines, the same for every engine:
- **L1** "Ho ho ho! Hello, little friend!"
- **L2** "Oh, a kitty named Mittens! I love kitties. What color is she?"
- **L3** "That sounds wonderful. I'll tell my elves!"
- **L4** "The reindeer love carrots and snowy nights at the North Pole."
- **L5** "It's time for me to go back to the workshop. Are you ready to say goodbye?"

**Kokoro v1.0: 138 files** in `kokoro/`.

| Set | What | Files |
|---|---|---|
| Voices | every `am_`/`bm_` voice in `voices-v1.0.bin`: am_adam, am_echo, am_eric, am_fenrir, am_liam, am_michael, am_onyx, am_puck, am_santa, bm_daniel, bm_fable, bm_george, bm_lewis. Each at speeds 0.95 and 1.0, lines L1, L2, L5 | 13 × 2 × 3 = 78 |
| Blends | style vectors mixed 70/30: am_michael+bm_george, am_santa+bm_fable, am_onyx+bm_george, am_michael+am_santa. Each at 0.95 and 1.0, lines L1, L2, L5 | 4 × 2 × 3 = 24 |
| Punctuation | am_michael and bm_fable at 0.95. L2 written three ways: a = as given, b = "Oh...", c = "Ooh" and "And" added | 2 × 3 = 6 |
| "Ho ho ho" | am_michael and bm_fable. Texts "Ho ho ho!", "Ho, ho, ho!" and "Ho ho ho! Hello!", each at speeds 0.90, 0.93, 0.96, 1.00 and 1.03 | 2 × 3 × 5 = 30 |

**Pocket TTS: 141 files** in `pocket/`.

| Set | What | Files |
|---|---|---|
| Voices | all 27 built-in voices, named exactly as the library names them, with the English model, lines L1–L5: alba, anna, azelma, bill_boerst, caro_davy, charles, cosette, daan, eponine, estelle, eve, fantine, george, giovanni, jane, javert, jean, juergen, lola, marius, mary, michael, paul, peter_yearsley, rafael, stuart_bell, vera | 27 × 5 = 135 |
| Repeat takes | alba (the library default) and michael: 3 unseeded takes of L1 | 2 × 3 = 6 |

**Which Pocket voices are male:**
- The library's metadata for each voice is only its name and source recording. The page shows the recording under
  each label.
- The README adds a language tag: giovanni (it), lola (es), juergen (de), rafael (pt), estelle (fr), the rest (en).
  It does not list daan.
- **No voice is described as male or female.** So, as the prompt says, every voice "named without metadata" was
  rendered, and none is marked male.
- The five voices with a non-English tag (and daan) still have English embeddings, and they speak the English lines
  here.
- Pocket TTS has no speed setting, so its rows have no speed.

The existing 36 Stage H WAVs in `out/voice_audition/` are untouched.

**The page:**
- One row per voice, setting or blend, grouped by engine and section, with a player for each line.
- Each line is a ▶ button (hover it to see the text); click again to stop. One shared player, so the page opens fast.
- A star checkbox per row, and **Copy my favourites**, which copies the starred labels. If the browser blocks the
  clipboard on a `file://` page, the labels are also in a text box to copy by hand.
- Stars are remembered in that browser only.
- A note at the top of each section says what it is, its provenance and its measured speed.
- The page has no external fonts, scripts or links. Audio files are referenced by relative path.

## 5. Trying a voice in the app

**Kokoro** (works today, no code change):

```bash
SANTA_VOICE=bm_fable SANTA_SPEED=1.0 HF_HUB_OFFLINE=1 PYTHONDONTWRITEBYTECODE=1 \
  ~/.venvs/talking-santa-h/bin/python -m santa.web
```

- Any single voice id from the table in §4 works.
- The canned lines re-render on their own when the voice or speed changes: their cache key includes both. Delete
  `santa/web/.cache/` afterwards if wanted.
- **Blends cannot be tried in the app yet:** `SANTA_VOICE` takes one voice name. A blend needs a small J2 change,
  for example `SANTA_VOICE=am_michael:70,bm_george:30` parsed into a mixed style vector.

**Pocket TTS** would need, in J2 (not implemented):
1. **Install.** Either install `pocket-tts==4.0.1` into the app venv, or point the app at the J venv.
   - The Stage H venv already has torch 2.15.0, so the additions would be: einops, sentencepiece, tokenizers,
     safetensors, typer and python-multipart.
   - Re-check `pip freeze` afterwards.
2. **A `PocketTTS` class** with the same `synth(Spoken)` interface and `sr = 24000`. That is the same rate as Kokoro,
   so no resampling is needed.
   - It loads `TTSModel.load_model()` and `get_state_for_audio_prompt(<name>)` once at startup.
   - It is not thread-safe, so it stays on the existing single TTS worker.
3. **Settings:** `SANTA_TTS=pocket`, with `SANTA_VOICE` holding a Pocket voice name. There is no speed.
4. **Decide determinism:**
   - unseeded gives a fresh take each time;
   - the in-memory cache of short lines and the on-disk canned cache would freeze one take.
   - Options: keep a few takes per short line and rotate them, or seed for reproducible tests.
5. **Optional:** stream chunks to the browser (`generate_audio_stream`) to get about 0.06 s to first audio. Hang up
   would then also need to stop generation (`stop=` event).
6. **Run offline:**
   - `HF_HUB_OFFLINE=1` works once the cache above is present (verified with the network blocked);
   - stay logged out of Hugging Face, or pass the no-cloning config, so the gated cloning weights are never
     requested;
   - add CC-BY-4.0 attribution for the weights.
7. **Re-run** the Stage H latency, soak and safety checks with the new engine.

## 6. Offline check

All of these ran under `sandbox-exec` with `(deny network*)` and `HF_HUB_OFFLINE=1`:
- `j1_audition.py kokoro`;
- `j1_audition.py pocket` (load, 27 voices, 141 renders);
- every bench cell.

A `curl` under the same profile failed to resolve hosts, which confirms the block works. The only network use was
the install and `pocket-fetch`.

## 7. FOR DON (by ear)

1. Open the page, listen, star, then press **Copy my favourites** and paste the list to Claude for J2.
2. Do any Kokoro voices at 0.95 or 1.0 sound less fake than am_michael at 0.9? (am_michael at 0.9 is in the Stage H
   folder, `out/voice_audition/am_michael_0.90_*.wav`.)
3. Do the blends or the punctuation variants help?
4. "Ho ho ho" variants: would rotating these takes stop the repeat sounding fake?
5. Pocket TTS: is any built-in voice a good Santa? Do the three unseeded takes sound like natural variation, or
   like instability?

## 7a. Don's favourites (2026-11-10, by ear)

| Pick | Engine | How to run it |
|---|---|---|
| peter_yearsley | Pocket TTS (Voice-Zero recording, CC0) | `SANTA_TTS=pocket SANTA_VOICE=peter_yearsley` |
| stuart_bell | Pocket TTS (Voice-Zero recording, CC0) | `SANTA_TTS=pocket SANTA_VOICE=stuart_bell` |
| blend am_santa + bm_fable (70/30; the speed was not noted, 0.95 or 1.0) | Kokoro | `SANTA_VOICE=am_santa:70,bm_fable:30 SANTA_SPEED=0.95` (blend support added 2026-11-10) |
| am_santa @ 0.95 | Kokoro | `SANTA_VOICE=am_santa SANTA_SPEED=0.95` |

## 8. Not done

- No voice cloning, and no Pocket cloning weights. The gated `kyutai/pocket-tts` was never requested.
- No Chatterbox, CosyVoice, Qwen3-TTS, F5-TTS, Fish, IndexTTS or MeloTTS: none was installed or run.
- No app change: `santa/`, `santa/web/`, `chat.py`, `profiles.json`, `santa/legacy/`, the tests and the Stage H venv
  are untouched. The only edit outside new files is one `.gitignore` entry.
- No real-child test, and no test on the room speakers.
- No ranking of voices by sound.
- Speed was not re-measured on a quiet Mac (§3 caveat).
- No commit.

## 9. Files

- **New:**
  - `tools/probes/j1_audition.py`, `tools/probes/j1_bench.py`, `docs/history/STAGE_J1.md`;
  - `tools/probes/out/`:
    - `j1_bench.md`, `j1_bench.json`, `j1_bench_firstrun.md`, `j1_bench_firstrun.json`;
    - `j1_determinism_kokoro.json`, `j1_determinism_pocket.json`;
    - `voice_audition_J/` (gitignored): WAVs, `manifest_kokoro.json`, `manifest_pocket.json`, `index.html`.
- **Edited:** `.gitignore`, which gained `tools/probes/out/voice_audition_J/`. Verified with
  `git check-ignore -v` → `.gitignore:24`.
  - Unlike the Stage H report, `STAGE_J1.md` and `out/j1_*` are **not** gitignored, because the prompt allowed only
    the one `.gitignore` edit. Add them if they should stay local.
- **Outside the repo:**
  - `~/.venvs/talking-santa-j`;
  - `~/.cache/huggingface/hub/models--kyutai--pocket-tts-without-voice-cloning/`.
- **Gemma:** `docker model unload --all` was run at the end. It reported "No models are running", yet
  `docker model ps` still listed `gemma4:e4b`, and unloading it by name or by backend did the same. This looks like
  a Docker Model Runner quirk. Gemma will drop on its 5-minute idle timer; Claude did not kill the Docker-managed
  process.
  - At the final check, `docker model ps` also listed a second model, `2d64f3d511ba`. This stage did not load it, so
    something else on the Mac was using Docker Model Runner.
