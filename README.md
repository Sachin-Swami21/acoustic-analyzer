# 🔊 Acoustic Analyzer

**A local edge-AI that listens through a soldered microphone and explains what it hears** —
running entirely on an NVIDIA Jetson. No cloud, and no raw audio ever leaves the box: the
language model reasons only over the numbers the DSP distills.

> A father–son project: hands-on **soldering** (an analog mic front-end) + **edge computing**
> (Jetson) + **local AI** (Ollama + a small LLM with tool-calling).

![Acoustic Analyzer architecture](acoustic-analyzer.svg)

---

## The idea

A 3-billion-parameter model can't (and shouldn't) listen to a raw waveform. A Python DSP layer
turns each recording into **structured facts** — dominant frequency, tonal peaks, band energy, a
60 Hz hum score — and the LLM reasons over those:

```
you> what's that noise?
  [tool] capture_and_analyze(seconds=2)
  → { "label":"electrical hum (mains-related)", "dominant_hz":60.0,
      "peaks_hz":[60,120,180], "hum_60hz_score":1.00 }
agent> That's 60 Hz mains hum with 120/180 Hz harmonics — likely a ground loop.
```

---

## Quick start

Runs on your Mac today (built-in mic); identical on the Jetson later. Full guide → **[SETUP.md](SETUP.md)**.

```bash
# 1. local LLM
brew install ollama            # or https://ollama.com  (Linux/Jetson: curl -fsSL https://ollama.com/install.sh | sh)
ollama pull qwen2.5:3b

# 2. python env
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt

# 3. run it
./.venv/bin/python agent.py    # then: "what's that noise?" / "show me the spectrum"
```

---

## What's in here

| File | What |
|------|------|
| [capture_test.py](capture_test.py) | Prove the mic works — level meter, record, device list |
| [spectrogram.py](spectrogram.py) | Live scrolling FFT spectrogram |
| [features.py](features.py) | `analyze()` — audio → structured JSON facts |
| [acoustic_tools.py](acoustic_tools.py) | The LLM tools: `capture_and_analyze`, `get_spectrum_image`, `list_input_devices` |
| [agent.py](agent.py) | Terminal chat — local LLM (Ollama) that calls the tools |

**Docs:** [SETUP.md](SETUP.md) (install & run) · [JETSON-SETUP.md](JETSON-SETUP.md) (Jetson bootstrap,
Apple-Silicon path) · [PROJECT.md](PROJECT.md) (design, BOM, roadmap, future ideas) ·
[acoustic-wiring.svg](acoustic-wiring.svg) (what to solder).

---

## Status

- 🟢 **Built & verified** — DSP pipeline (capture → spectrogram → features) + the local
  tool-calling agent (`qwen2.5:3b` on Ollama).
- 🔜 **Next** — an HTTP tool service (FastAPI) → then Open WebUI + a Dockerized Jetson deploy.
- ⚪ **Stretch** — a log-mel CNN sound classifier; NFC "tap-to-analyze" from an iPhone.

## Hardware

A ~$25 analog front-end you solder: **electret mic → MAX9814 preamp → anti-alias RC filter →
3.5 mm jack → USB audio adapter → Jetson**. Wiring map + BOM in [PROJECT.md](PROJECT.md).

---

*Built on a Mac, deploys to the Jetson unchanged — the DSP distills, the local LLM explains.*
