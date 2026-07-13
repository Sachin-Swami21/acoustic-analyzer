"""
Stage 4 - expose the DSP to an LLM as callable TOOLS.

The language model never sees raw audio. It calls these functions, which
wrap features.analyze(), and reasons over the JSON facts they return.

These same functions plug into a standalone agent (agent.py) now, or into
Open WebUI later - the tool contract is identical.
"""

import json

import numpy as np

from features import analyze, SAMPLE_RATE


def _record(seconds, device=None):
    import sounddevice as sd  # imported lazily so wav-only use needs no PortAudio
    audio = sd.rec(int(seconds * SAMPLE_RATE), samplerate=SAMPLE_RATE,
                   channels=1, device=device)
    sd.wait()
    return audio.flatten()


def _read_wav(path):
    from scipy.io import wavfile
    sr, data = wavfile.read(path)
    if data.dtype.kind in "iu":  # int PCM -> float
        data = data.astype(np.float64) / np.iinfo(data.dtype).max
    samples = data[:, 0] if data.ndim > 1 else data
    return samples, sr


def _get_samples(seconds, wav_path, device):
    """Shared source: read a wav if given, else record from the mic."""
    if wav_path:
        samples, sr = _read_wav(wav_path)
        return samples, sr, wav_path
    return _record(seconds, device), SAMPLE_RATE, "microphone (%.1fs)" % seconds


# ---- the tools the LLM can call --------------------------------------------

def capture_and_analyze(seconds=2.0, wav_path=None, device=None):
    """Record `seconds` of mic audio (or read wav_path) and return acoustic facts."""
    try:
        seconds = float(seconds or 2.0)
        samples, sr, source = _get_samples(seconds, wav_path, device)
        facts = analyze(samples, sr)
        facts["source"] = source
        return facts
    except Exception as e:  # never crash the agent loop - report to the model
        return {"error": "%s: %s" % (type(e).__name__, e),
                "hint": "If there is no microphone/PortAudio, pass wav_path to analyze a .wav file."}


def get_spectrum_image(seconds=2.0, wav_path=None, out_path="spectrum.png", device=None):
    """Record (or read) audio and save a spectrogram PNG; return its path.

    Use when the user wants to SEE the sound (its spectrum / spectrogram / frequencies
    over time). The image spans 0-8 kHz on a dB scale.
    """
    try:
        import os
        import matplotlib
        matplotlib.use("Agg")  # headless: no window, just write the file
        import matplotlib.pyplot as plt
        from scipy.signal import spectrogram as _spec

        seconds = float(seconds or 2.0)
        samples, sr, source = _get_samples(seconds, wav_path, device)
        samples = np.asarray(samples, dtype=np.float64).flatten()

        f, t, sxx = _spec(samples, fs=sr, nperseg=1024, noverlap=512)
        keep = f <= 8000                      # most of the action is below 8 kHz
        sxx_db = 10 * np.log10(sxx[keep] + 1e-12)

        fig, ax = plt.subplots(figsize=(8, 4))
        m = ax.pcolormesh(t, f[keep] / 1000.0, sxx_db, shading="auto",
                          cmap="magma", vmin=-100, vmax=sxx_db.max())
        ax.set_xlabel("time (s)")
        ax.set_ylabel("frequency (kHz)")
        ax.set_title("Spectrogram - %s" % source)
        fig.colorbar(m, ax=ax, label="dB")
        fig.tight_layout()
        fig.savefig(out_path, dpi=110)
        plt.close(fig)

        return {"image_path": os.path.abspath(out_path), "source": source,
                "range": "0-8 kHz, dB scale",
                "note": "Spectrogram saved. Tell the user the file path so they can open it."}
    except Exception as e:
        return {"error": "%s: %s" % (type(e).__name__, e),
                "hint": "If there is no microphone/PortAudio, pass wav_path to render a .wav file."}


def list_input_devices():
    """List available audio input devices and their indices."""
    try:
        import sounddevice as sd
        devs = [{"index": i, "name": d["name"], "channels": d["max_input_channels"]}
                for i, d in enumerate(sd.query_devices()) if d["max_input_channels"] > 0]
        return {"input_devices": devs}
    except Exception as e:
        return {"error": "%s: %s" % (type(e).__name__, e)}


# ---- schemas + dispatch (Ollama / OpenAI function-calling format) ----------

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "capture_and_analyze",
            "description": (
                "Record a few seconds of audio from the microphone (or read a WAV file) "
                "and return structured acoustic facts: loudness (rms_db), dominant "
                "frequency (dominant_hz), strongest tones (peaks_hz), spectral centroid, "
                "60 Hz mains-hum score (hum_60hz_score), per-band energy, and a heuristic "
                "label. Call this whenever the user asks what a sound is, how loud it is, "
                "whether there is hum, what frequency something is, etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "seconds": {"type": "number",
                                "description": "How many seconds to record (default 2)."},
                    "wav_path": {"type": "string",
                                 "description": "Optional path to a .wav file to analyze instead of recording."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_spectrum_image",
            "description": (
                "Record a few seconds of audio (or read a WAV file) and save a spectrogram "
                "PNG showing frequency content over time (0-8 kHz). Call this when the user "
                "wants to SEE the sound / its spectrum / spectrogram / frequencies. Returns "
                "the saved image path - relay that path to the user."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "seconds": {"type": "number",
                                "description": "How many seconds to record (default 2)."},
                    "wav_path": {"type": "string",
                                 "description": "Optional path to a .wav file to render instead of recording."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_input_devices",
            "description": "List available audio input devices and their indices.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

DISPATCH = {
    "capture_and_analyze": capture_and_analyze,
    "get_spectrum_image": get_spectrum_image,
    "list_input_devices": list_input_devices,
}


def call(name, arguments):
    """Dispatch a tool call by name with a dict (or JSON string) of arguments."""
    if isinstance(arguments, str):
        arguments = json.loads(arguments or "{}")
    fn = DISPATCH.get(name)
    if fn is None:
        return {"error": "unknown tool: %s" % name}
    return fn(**(arguments or {}))


if __name__ == "__main__":  # quick smoke test without the LLM
    print(json.dumps(capture_and_analyze(seconds=2.0), indent=2))
