# Setup — running the Acoustic Analyzer

How to get the software running: **Ollama + a local model**, the **Python environment**, and
the **agent**. Works the same on your Mac (dev) and on the Jetson (deploy).

- Hardware / Jetson bootstrapping → [JETSON-SETUP.md](JETSON-SETUP.md)
- What the project is / the design → [PROJECT.md](PROJECT.md)

You'll end up able to run `python agent.py` and ask *"what's that noise?"* — a local LLM that
calls the DSP tools and explains the sound.

---

## Prerequisites

- **Python 3.9+**
- **Ollama** (installed below) — the local LLM runtime
- A **microphone** (built-in on the Mac; the USB audio adapter on the Jetson)
- ~2 GB free disk for the model

---

## 1 · Install Ollama + pull the model

**macOS:**
```bash
brew install ollama            # or download the app from https://ollama.com
ollama serve &                 # start the local server (the app does this automatically)
```

**Linux / Jetson:**
```bash
curl -fsSL https://ollama.com/install.sh | sh   # installs + starts the service
```

**Then pull the model (both platforms):**
```bash
ollama pull qwen2.5:3b         # ~1.9 GB; chosen for strong tool-calling
```

**Verify Ollama is up:**
```bash
curl -s http://localhost:11434/api/tags         # should list qwen2.5:3b
ollama run qwen2.5:3b "hello"                    # should reply
```

> Low on RAM (e.g. 4 GB Jetson)? Use a smaller model — `ollama pull qwen2.5:1.5b` or
> `llama3.2:1b` — and pass it with `--model` (see §3).

---

## 2 · Python environment

From the project folder:

```bash
cd ~/acoustic-analyzer                 # or /Users/chamiv/acoustic-analyzer on the Mac

python3 -m venv .venv                  # create an isolated environment
./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install -r requirements.txt
```

`requirements.txt` pulls: `sounddevice`, `numpy`, `scipy`, `matplotlib`, `ollama`.

**Linux / Jetson only** — `sounddevice` needs PortAudio system libraries first:
```bash
sudo apt install -y portaudio19-dev libsndfile1
```

---

## 3 · Run it

```bash
# 1. Prove the mic works — live level meter (Ctrl-C to stop)
./.venv/bin/python capture_test.py

# 2. List audio devices (find the USB adapter's index on the Jetson)
./.venv/bin/python capture_test.py --list

# 3. See the sound — live spectrogram
./.venv/bin/python spectrogram.py

# 4. Structured facts from 2 s of audio
./.venv/bin/python features.py --seconds 2

# 5. The agent — chat with a local LLM that hears
./.venv/bin/python agent.py
#   you> what's that noise?
#   you> is there any 60 Hz hum?
#   you> show me the spectrum     (saves spectrum.png, tells you the path)
```

**Pick a different model or mic:**
```bash
./.venv/bin/python agent.py --model qwen2.5:1.5b
./.venv/bin/python capture_test.py --device 2      # use input device index 2
```

On the Jetson, the commands are identical — only add `--device N` for the USB audio adapter
(find N with `--list`).

---

## 4 · Configuration

| What | How |
|------|-----|
| **Model** | `--model <name>` on `agent.py` (default `qwen2.5:3b`) |
| **Mic / input device** | `--device N` (find N via `capture_test.py --list`) |
| **Ollama location** | defaults to `http://localhost:11434`. For a remote/containerized Ollama, set the host in the environment (see below) |

**Pointing the agent at a non-local Ollama** (e.g. when it runs in another container):
```bash
export OLLAMA_HOST=http://ollama:11434     # then run agent.py
```
> Note: `agent.py` currently uses the default `ollama.Client()` (localhost). If you deploy with
> Ollama in a separate container, we'll wire it to read `OLLAMA_HOST` — small change, on the
> roadmap. For local runs on one machine, no config is needed.

---

## 5 · Quick health check

```bash
# Ollama reachable + model present
curl -s http://localhost:11434/api/tags | grep qwen2.5

# tools work without a mic (synthetic 60 Hz hum → should label "electrical hum")
./.venv/bin/python -c "import numpy as np, json; from scipy.io import wavfile; \
import acoustic_tools as T; sr=44100; t=np.linspace(0,2,2*sr,endpoint=False); \
x=0.3*np.sin(2*np.pi*60*t)+0.15*np.sin(2*np.pi*120*t); \
wavfile.write('/tmp/h.wav',sr,(x*32767).astype(np.int16)); \
print(json.dumps(T.capture_and_analyze(wav_path='/tmp/h.wav'), indent=2))"
```

---

## Troubleshooting

- **`connection refused` / agent hangs** → Ollama isn't running. Start it (`ollama serve` on Mac,
  or `sudo systemctl status ollama` on Linux) and confirm `curl localhost:11434/api/tags`.
- **`model not found`** → run `ollama pull qwen2.5:3b` (or match the `--model` you passed).
- **`sounddevice`/PortAudio import error** → macOS: `pip install sounddevice` again; Linux/Jetson:
  install `portaudio19-dev` (above), then reinstall.
- **No sound / flat level meter** → wrong input device; run `capture_test.py --list` and pass
  `--device N`. On macOS grant mic permission when prompted.
- **Model calls no tool / rambles** → smaller models are weaker at tool-calling; try `qwen2.5:3b`
  (not the 1.5b) and keep prompts direct ("what's that noise?").
- **Slow on Jetson** → ensure `nvidia-jetpack` is installed and `jtop` shows GPU use; set
  `sudo nvpmodel -m 0 && sudo jetson_clocks`.

---

## What's next (not yet built)

- **HTTP tool service** (FastAPI over the tools) — the linchpin for Open WebUI, the NFC trigger,
  and containers. See [PROJECT.md](PROJECT.md) → "Next up".
- **Open WebUI** browser front-end.
- **Docker Compose** deploy on the Jetson (GPU runtime + `/dev/snd` mic passthrough).
