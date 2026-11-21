"""Stage H settings for the voice web app. Every value can be overridden with an environment variable.

Nothing here changes the brain's shipped config (santa/config.py): temperature, max_tokens, model and prompts stay as
they are.
"""
import ipaddress
import os
from dataclasses import dataclass, field
from pathlib import Path

from santa import local

ROOT = Path(__file__).resolve().parent.parent
PKG = Path(__file__).resolve().parent


def _f(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


def _b(name: str, default: bool) -> bool:
    return os.getenv(name, "1" if default else "0").strip().lower() not in ("0", "false", "no", "off", "")


def is_loopback(host: str | None) -> bool:
    """True for 127.0.0.1, ::1 and "localhost". Anything else (a LAN address, a test client name) is not."""
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host or "").is_loopback
    except ValueError:
        return False


@dataclass
class Settings:
    host: str = "127.0.0.1"                      # this Mac only; `--network` binds 0.0.0.0 (HTTPS + PIN required)
    port: int = int(os.getenv("SANTA_PORT", "8765"))

    # home network mode (--network)
    pin: str = os.getenv("SANTA_PIN", "")        # other devices must enter it; this Mac never has to
    cert_file: Path | None = None                 # HTTPS certificate (mkcert), required with --network
    key_file: Path | None = None
    pin_max_tries: int = 5                        # wrong PINs from one device before a lockout
    pin_lockouts: tuple[float, ...] = (60, 300, 1800)   # each lockout is longer: 1 min, 5 min, then 30 min
    gate_limit_per_min: int = int(os.getenv("SANTA_GATE_LIMIT", "10"))  # PIN tries/min from devices without the
                                                                      # PIN, all devices together
    gate_limit_per_device: int = 5                # ...and from any one device, so one cannot use up everyone's tries

    alerts: bool = False                          # macOS security alert (on for `python -m santa.web`; SANTA_ALERTS=0)

    # names this server answers to (Host header). --network adds this Mac's .local name and Wi-Fi address.
    allowed_hosts: tuple[str, ...] = ("127.0.0.1", "localhost", "::1")
    extra_hosts: tuple[str, ...] = field(default_factory=lambda: tuple(
        h.strip().lower() for h in os.getenv("SANTA_ALLOWED_HOSTS", "").split(",") if h.strip()))

    # end of speech (section 4.3)
    eos_ms: float = _f("SANTA_EOS_MS", 1200)     # fixed wait after the last voiced frame
    eos_extend: bool = _b("SANTA_EOS_EXTEND", True)
    eos_extend_ms: float = _f("SANTA_EOS_EXTEND_MS", 1800)
    eos_short_speech_ms: float = _f("SANTA_EOS_SHORT_MS", 1500)   # extend once when the turn has less speech than this
    min_speech_ms: float = _f("SANTA_MIN_SPEECH_MS", 250)          # shorter clips are dropped, never transcribed
    max_utterance_s: float = _f("SANTA_MAX_UTTERANCE_S", 20)
    preroll_ms: float = 300
    tail_ms: float = 200                          # silence kept after the last voiced frame (helps Whisper)
    echo_guard_ms: float = 300                    # mic stays closed this long after playback_ended
    vad_on: float = 0.5                           # Silero probability that starts speech
    vad_off: float = 0.35                         # ...and that keeps it going (hysteresis)

    # STT (section 4.4)
    stt_repo: str = os.getenv("SANTA_STT_MODEL", "mlx-community/whisper-small.en-mlx")
    stt_min_logprob: float = _f("SANTA_STT_MIN_LOGPROB", -1.0)    # below: "say that again"
    stt_max_no_speech: float = _f("SANTA_STT_MAX_NO_SPEECH", 0.8)
    stt_max_compression: float = 2.4                               # repeated-text hallucination

    # TTS
    models_dir: Path = Path(os.getenv("SANTA_MODELS_DIR", str(Path.home() / ".cache" / "talking-santa" / "models")))
    tts_engine: str = os.getenv("SANTA_TTS", "kokoro")            # "kokoro" or "pocket" (Kyutai Pocket TTS)
    voice: str = os.getenv("SANTA_VOICE", "peter_yearsley" if os.getenv("SANTA_TTS") == "pocket" else "am_michael")
    speed: float = _f("SANTA_SPEED", 0.9)                          # Kokoro only

    # call flow (sections 2, 4.9, 4.10)
    ring_min_s: float = 2.0
    ring_max_s: float = 8.0
    silence_prompt_s: float = _f("SANTA_SILENCE_S", 45)
    keepalive_s: float = _f("SANTA_KEEPALIVE_S", 100)              # 90 to 120 s, only while no call is active
    playback_grace_s: float = 3.0                 # if the browser never reports playback_ended
    # liveness: during a call the page gets {"type": "tick"} this often (0 = off). The page treats LOST_MS
    # (static/liveness.js, 6 s) without any message as a dead connection, so keep this well under half of that.
    tick_s: float = _f("SANTA_TICK_S", 2.5)
    # slow brain (P5-1): no first sentence this long into a reply -> the page gets {"type": "slow"} (once per turn)
    # and Santa says the canned "hold" line, at most once per hold_every_s in one call. No timeout changes.
    slow_s: float = _f("SANTA_SLOW_S", 10)
    hold_every_s: float = _f("SANTA_HOLD_EVERY_S", 60)

    # personal (local/, gitignored): Santa's picture
    santa_image: Path | None = field(default_factory=local.santa_image)

    # privacy
    debug_audio: bool = False                     # --debug-audio only
    debug_audio_dir: Path = PKG / "debug_audio"   # gitignored
    canned_dir: Path = PKG / ".cache"             # gitignored: Santa's canned lines only, never the child's audio
    metrics_file: Path | None = None              # numbers only (sims); never text
    extra: dict = field(default_factory=dict)

    @property
    def network(self) -> bool:
        """True when other devices can reach the server (not bound to a loopback address)."""
        return not is_loopback(self.host)

    @property
    def kokoro_model(self) -> Path:
        return self.models_dir / "kokoro-v1.0.onnx"

    @property
    def kokoro_voices(self) -> Path:
        return self.models_dir / "voices-v1.0.bin"

    @property
    def vad_model(self) -> Path:
        return self.models_dir / "silero_vad.onnx"
