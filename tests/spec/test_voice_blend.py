"""SANTA_VOICE blends for Kokoro ("am_santa:70,bm_fable:30"): parsing only, no model needed."""
import numpy as np
import pytest

from santa.web.tts import kokoro_voice

STYLES = {"am_santa": np.full((4, 256), 1.0, np.float32), "bm_fable": np.full((4, 256), 3.0, np.float32),
          "am_onyx": np.full((4, 256), 5.0, np.float32)}


def test_single_voice_name_passes_through():
    assert kokoro_voice("am_santa", STYLES) == "am_santa"


def test_blend_mixes_by_weight():
    v = kokoro_voice("am_santa:70,bm_fable:30", STYLES)
    assert v.dtype == np.float32 and v.shape == (4, 256)
    assert np.allclose(v, 0.7 * 1.0 + 0.3 * 3.0)


def test_weights_are_normalised_and_spaces_allowed():
    assert np.allclose(kokoro_voice("am_santa:7, bm_fable:3", STYLES), kokoro_voice("am_santa:70,bm_fable:30", STYLES))


def test_three_way_blend():
    assert np.allclose(kokoro_voice("am_santa:1,bm_fable:1,am_onyx:2", STYLES), (1 + 3 + 2 * 5) / 4)


@pytest.mark.parametrize("spec", ["am_nobody", "am_santa:70,bm_nobody:30", "am_santa:70,bm_fable", "am_santa:x,bm_fable:1",
                                  "am_santa:0,bm_fable:1", "am_santa:-1,bm_fable:2", "am_santa:100", "am_santa:70,"])
def test_bad_specs_raise(spec):
    with pytest.raises(ValueError):
        kokoro_voice(spec, STYLES)
