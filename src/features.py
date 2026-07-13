"""
Stage 3 - turn a chunk of audio into STRUCTURED FACTS.

This is the bridge to the LLM. The language model never sees raw audio;
it sees the JSON that analyze() produces and reasons over it.

  python features.py            # record 2s from the mic and print the JSON
  python features.py file.wav   # analyze an existing wav

analyze(samples, sr) is the function the chat tools will call.
"""

import argparse
import json
import sys

import numpy as np
from scipy.io import wavfile
from scipy.signal import find_peaks

SAMPLE_RATE = 44100

# Frequency bands (Hz) used for the energy summary.
BANDS = {
    "sub_20_60": (20, 60),
    "bass_60_250": (60, 250),
    "low_mid_250_500": (250, 500),
    "mid_500_2k": (500, 2000),
    "high_mid_2k_6k": (2000, 6000),
    "high_6k_20k": (6000, 20000),
}


def _band_energy(freqs, power, lo, hi):
    mask = (freqs >= lo) & (freqs < hi)
    return float(power[mask].sum())


def _hum_score(freqs, power):
    """How strong is 60 Hz mains hum (and its 120/180 Hz harmonics)?"""
    def energy_near(f0, width=4):
        mask = (freqs >= f0 - width) & (freqs <= f0 + width)
        return power[mask].sum()

    hum = energy_near(60) + energy_near(120) + energy_near(180)
    total = power.sum() + 1e-12
    return float(hum / total)


def analyze(samples, sr=SAMPLE_RATE):
    """Return a JSON-serializable dict of acoustic features."""
    samples = np.asarray(samples, dtype=np.float64).flatten()
    if samples.size == 0:
        return {"error": "empty audio"}

    # --- time domain ---
    rms = np.sqrt(np.mean(samples ** 2))
    rms_db = float(20 * np.log10(rms + 1e-9))
    zcr = float(np.mean(np.abs(np.diff(np.sign(samples))) > 0))

    # --- frequency domain ---
    windowed = samples * np.hanning(samples.size)
    spectrum = np.abs(np.fft.rfft(windowed))
    freqs = np.fft.rfftfreq(samples.size, 1 / sr)
    power = spectrum ** 2

    # dominant frequency (ignore DC / sub-20 Hz)
    valid = freqs >= 20
    dominant_hz = float(freqs[valid][np.argmax(power[valid])])

    # spectral centroid ("brightness")
    centroid = float((freqs * spectrum).sum() / (spectrum.sum() + 1e-12))

    # strongest tonal peaks
    peak_idx, _ = find_peaks(spectrum, height=spectrum.max() * 0.25, distance=20)
    peak_idx = peak_idx[np.argsort(spectrum[peak_idx])[::-1][:5]]
    peaks_hz = sorted(round(float(freqs[i]), 1) for i in peak_idx)

    bands = {name: round(_band_energy(freqs, power, lo, hi), 3)
             for name, (lo, hi) in BANDS.items()}

    hum = _hum_score(freqs, power)

    # --- crude, honest heuristic label ---
    if rms_db < -55:
        label = "silence / very quiet"
    elif hum > 0.25:
        label = "electrical hum (mains-related)"
    elif len(peaks_hz) <= 2 and centroid < 1500:
        label = "tonal (single/few tones)"
    elif zcr > 0.15 and centroid > 3000:
        label = "broadband noise / hiss"
    else:
        label = "complex sound (speech/music/mixed)"

    return {
        "label": label,
        "rms_db": round(rms_db, 1),
        "dominant_hz": round(dominant_hz, 1),
        "peaks_hz": peaks_hz,
        "spectral_centroid_hz": round(centroid, 1),
        "zero_crossing_rate": round(zcr, 3),
        "hum_60hz_score": round(hum, 3),
        "band_energy": bands,
    }


def _record(seconds=2.0, device=None):
    import sounddevice as sd
    print(f"Recording {seconds}s...", file=sys.stderr)
    audio = sd.rec(int(seconds * SAMPLE_RATE), samplerate=SAMPLE_RATE,
                   channels=1, device=device)
    sd.wait()
    return audio.flatten(), SAMPLE_RATE


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("wav", nargs="?", help="wav file to analyze (else record live)")
    ap.add_argument("--seconds", type=float, default=2.0)
    ap.add_argument("--device", type=int, default=None)
    args = ap.parse_args()

    if args.wav:
        sr, data = wavfile.read(args.wav)
        if data.dtype.kind in "iu":  # int PCM -> float
            data = data.astype(np.float64) / np.iinfo(data.dtype).max
        samples = data[:, 0] if data.ndim > 1 else data
    else:
        samples, sr = _record(args.seconds, args.device)

    print(json.dumps(analyze(samples, sr), indent=2))
