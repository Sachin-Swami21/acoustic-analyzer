# Acoustic Analyzer

A local, edge-AI project that **"hears" sound and explains it** — a hands-on
soldering + signal-processing + local-LLM build, with a Jetson doing the compute.

> **Why this exists:** a capstone-style project combining three real EE/CE skills —
> **hardware (soldering the analog front-end)**, **edge computing (Jetson)**, and
> **AI (a local LLM + chat UI)**.

📐 **Diagram:** [`acoustic-analyzer.drawio`](acoustic-analyzer.drawio) — open in
[draw.io](https://app.diagrams.net) or the VS Code *Draw.io Integration* extension.
Page 1 = system architecture; Page 2 = options considered.

---

## The idea in one picture

```
①  ANALOG FRONT-END              ②  JETSON · k3s (on NVMe)           ③  TERMINAL UI
   (solder / hardware)              Ollama + DSP tool service           ttyd web terminal

  Electret mic                     capture · spectrogram · features    ┌─[you] what's that noise?
      │                            features.analyze() → JSON facts        ⚡ analyze_sound()
  MAX9814 preamp                   qwen2.5:3b calls the tools ────────► └─[analyzer] 60 Hz hum…
      │
  Anti-alias RC filter             the agent (agent_shell.py) runs      open a browser to
      │                            the Ollama tool-calling loop         http://<jetson>:30088
  3.5 mm jack
      │
  USB audio adapter ──USB ~44.1kHz──►
```

**The clever bit:** the LLM never touches raw audio. The DSP layer distills each
recording into **structured JSON facts**, and the model reasons over those.

```
"What's that noise?"
  → LLM calls capture_and_analyze()
  → DSP returns { dominant_hz: 60, harmonics: [120,180], rms_db: -22,
                  centroid: 210, label: "electrical hum" }
  → LLM: "That's 60 Hz mains hum with 120/180 Hz harmonics — likely a ground
          loop or nearby transformer. Here's the spectrum:" 📈
```

---

## Hardware — the analog front-end (Path A, ~$16)

The soldering project. Path A was chosen for the most analog EE learning with the least
software friction (USB audio "just works").

| Part | Notes |
|------|-------|
| Electret mic capsule | The transducer |
| **MAX9814** AGC preamp module | Gain / bias / automatic gain control (~$8) |
| Anti-alias RC filter | Resistors + a capacitor — *the* sampling lesson |
| 3.5 mm jack | Output to the sound card |
| **USB audio adapter** (mic/line in) | Into the Jetson (~$8) |
| Perfboard, headers | Mount it all |

**Compute:** Jetson **Orin Nano** (~8 GB), booting from a **256 GB NVMe** (room for the OS,
Ollama models ~2–5 GB each, ML containers, audio datasets).

**Alternative front-ends** (not chosen — see diagram page 2): **Path B** INMP441 I2S MEMS
mic (needs device-tree work); **Path C** INMP441 + ESP32 wireless stream (planned Stage-2
upgrade).

---

## Soldering work (the hardware build)

This is the hardware part of the project. It is **hand-soldered, through-hole assembly on
perfboard** — the classic entry-level-but-real analog electronics soldering. No
surface-mount (SMD), no reflow, no fine-pitch. Forgiving enough to learn on, but a genuine
analog front-end, not just practice joints. Beginner-to-moderate difficulty and low-stakes:
the whole front-end is ~$16, so a fried part is no big deal — **the Jetson never gets
soldered**, it just receives clean USB audio.

### The three soldering tasks (rising skill)

1. **Header soldering (warm-up)** — solder pin headers onto the breakout modules (MAX9814,
   and the USB adapter if it has bare pads). Muscle-memory stage: heat pad + pin together,
   feed solder, get a shiny cone. Easy to spot and redo a bad joint.
2. **Component soldering — the anti-alias RC filter (the real lesson)** — solder a resistor
   and a capacitor onto perfboard to form the low-pass filter. This *is* the anti-aliasing
   filter, the physical embodiment of the Nyquist/sampling lesson — soldering a concept, not just parts.
3. **Point-to-point perfboard wiring (the assembly)** — perfboard has no traces, so the
   connections are made with soldered jumper wires / pad bridges on the underside. Route:
   mic → MAX9814 → filter → 3.5 mm jack, plus VCC/GND rails. The closest thing to building
   a real device.

**Skills it builds:** clean through-hole joints, gain staging & biasing (wiring the
MAX9814's power + gain-select pins), analog signal integrity (short leads, clean ground),
filtering in the flesh (the RC values set the cutoff), and hardware debugging (cold joints,
shorts, continuity-checking with a multimeter).

### Circuit / wiring diagram

📐 **Visual solder map:** [`acoustic-wiring.svg`](acoustic-wiring.svg) — pin-level connections
plus an 8-step solder checklist, print-friendly. ASCII version below.


```
 ELECTRET MIC        MAX9814 module            ANTI-ALIAS RC LOW-PASS        3.5 mm JACK      USB AUDIO
   capsule       (AGC preamp, gain select)      + DC-block cap                 (TRS)          adapter
                                                                                             (LINE-IN)
   (+)──────────►[MIC+]                 [OUT]──┤├──────[ R = 1 kΩ ]──┬───────► TIP ──────────► L / R
   (–)──────────►[MIC-]            1 µF DC-block                     │
                                                                 [ C = 10 nF ]
   +3.3–5V ─────►[VDD]                                               │
   GND ─────────►[GND]───────────────────────────────────────────┴───────► SLEEVE ────────► GND
                 [GAIN] → GND = 50 dB · open = 60 dB · VDD = 40 dB
                 [A/R]  → leave open = default attack/release
```

- **Power:** 3.3–5 V (Jetson 5 V header pin, or any USB 5 V supply) → `VDD`; common `GND`.
  The USB audio adapter carries **only the analog signal**, not power.
- **DC block (1 µF):** the MAX9814 output sits on a ~1.25 V DC bias; the series cap strips
  the DC so only the AC audio reaches the jack. Use **line-in** on the adapter (not mic-in)
  to avoid its bias voltage fighting the signal.
- **Anti-alias RC:** series **R = 1 kΩ**, shunt **C = 10 nF** to ground →
  cutoff `fc = 1/(2πRC) ≈ 16 kHz`, safely under the 22.05 kHz Nyquist limit at 44.1 kSPS.
  Want it nearer 20 kHz? Use R = 820 Ω or C = 8.2 nF.
- **Jack:** **Tip = signal**, **Sleeve = ground** (mono). Many MAX9814 breakouts (e.g.
  Adafruit) already have the electret mic soldered on — if so, skip task-1's mic capsule
  and just do headers + filter + jack.

### Why each component?

Follow the signal — **sound → mic → amplify → filter → connect → digitize → analyze.**
Each part is one stage in that chain.

**Signal path**

- **Electret microphone** — *the transducer.* Turns sound-pressure waves into a tiny
  (millivolt) voltage. It has a built-in transistor, so it needs a little power to run. The
  output is far too weak to use directly — which is exactly why it's amplified next.
- **MAX9814 preamp** — *the amplifier, with Automatic Gain Control (AGC).* Boosts the mic
  signal to a usable level and automatically turns gain *down* on loud sounds / *up* on quiet
  ones, so it doesn't clip — no knob to ride. Pins:
  - **VDD / GND** — power (2.7–5.5 V); also biases the onboard mic.
  - **OUT** — the amplified audio, sitting on a **~1.25 V DC bias** (→ the DC-block cap).
  - **GAIN** — sets *max* gain: VDD = 40 dB, GND = 50 dB, open = 60 dB. We tie it to **VDD
    (40 dB)** so a loud sound doesn't overdrive the sensitive sound-card input.
  - **A/R (Attack/Release)** — how *fast* the AGC clamps down and recovers; leave open for the default.
- **1 µF capacitor** — *DC block / coupling.* A capacitor passes AC but blocks DC, so in
  series it lets the audio through while stripping the MAX9814's ~1.25 V offset. Without it,
  that DC would shove the sound-card input off-center.
- **1 kΩ resistor + 10 nF capacitor** — *anti-aliasing low-pass filter.* Sampling at 44.1 kHz
  can only faithfully capture up to 22 kHz (Nyquist); any higher frequency "folds back" as a
  false lower tone (**aliasing**). The cap shunts highs to ground while the resistor feeds the
  signal, rolling off above `fc = 1/(2πRC) ≈ 16 kHz` — *before* the ADC sees it. Only the
  product R×C sets the cutoff; lower either for more treble.
- **3.5 mm TRS jack** — *the connector.* Carries the analog audio into the sound card.
  **Tip = signal, Sleeve = ground** (mono).
- **USB audio adapter** — *the ADC (digitizer).* The quietly critical part: it **samples** the
  analog audio 44,100×/sec and turns it into the numbers the computer reads. External + USB so
  it presents as a standard **microphone** on any computer *and* the Jetson (which lacks a good
  analog input). Everything upstream exists to hand *this* a clean signal.

**Build materials**

- **Perfboard** — a trace-less grid board you solder onto for a **permanent, sturdy** circuit
  (vs. a temporary breadboard); *you* make every connection.
- **Pin headers** — 0.1″ pins soldered to module edges so they mount and accept wires (also the
  easiest first solder task).
- **Hookup wire (22 AWG solid)** — makes the point-to-point connections on the trace-less board.

**Power**

- **3×AA (4.5 V) or USB 5 V** — supplies the 2.7–5.5 V the MAX9814 needs to run and bias the
  mic. It's separate because the USB adapter carries only the *signal*, not power. On the
  Jetson, use its **5 V header pin**.

> In one line: **mic hears → MAX9814 amplifies → R/C cleans → jack carries → USB adapter
> digitizes → computer analyzes.**

### Shopping list / bill of materials (~$25–30)

Connectors are called out explicitly (USB-A, 3.5 mm TRS, etc.). Links are **Amazon search
URLs** — they always resolve; pick the current best-rated / Prime listing yourself (specific
product links go stale, so we don't hard-code ASINs).

**Modules**

| # | Component | Exact spec (incl. connector) | Qty | ~$ | Buy |
|---|-----------|------------------------------|-----|----|-----|
| 1 | MAX9814 mic-amp | Adafruit **#1713**; mic on board; solder a 0.1″ header (VDD·GND·OUT·GAIN·A/R) | 1 | 8 | [search](https://www.amazon.com/s?k=MAX9814+microphone+amplifier+module) |
| 2 | USB audio adapter | **USB-A male** plug → Jetson; **3.5 mm mic input** (pink, 3-pole TRS) | 1 | 8 | [search](https://www.amazon.com/s?k=usb+external+sound+card+adapter+microphone+input) |
| 2b | *(Mac USB-C only)* USB-C→USB-A adapter | to use the USB-A dongle on a USB-C Mac | 1 | 5 | [search](https://www.amazon.com/s?k=usb+c+to+usb+a+adapter) |

**Passive components — you have the ceramic + electrolytic assortment boxes; links are for refills**

| # | Component | Value / how to find it | Qty | ~$ | Buy |
|---|-----------|------------------------|-----|----|-----|
| 3 | Resistor, ¼ W | **1 kΩ** — bands brown-black-red | 2–3 | — | [search](https://www.amazon.com/s?k=resistor+assortment+kit) |
| 4 | Ceramic capacitor | **10 nF** — ceramic box, marked **"103"** | 2–3 | — | [search](https://www.amazon.com/s?k=ceramic+capacitor+assortment+kit) |
| 5 | Capacitor (DC block) | **1 µF** — ceramic **"105"** *or* electrolytic (polarized: **+ → MAX9814 OUT**) | 2–3 | — | [search](https://www.amazon.com/s?k=electrolytic+capacitor+assortment+kit) |

**Connectors, board, wire**

| # | Component | Exact spec | Qty | ~$ | Buy |
|---|-----------|-----------|-----|----|-----|
| 6 | 3.5 mm plug pigtail | **3.5 mm male, 3-pole TRS** — tip = signal, sleeve = GND | 1 | 3 | [search](https://www.amazon.com/s?k=3.5mm+male+plug+pigtail+cable) |
| 7 | Perfboard | single-sided, **2.54 mm** pitch | 1 | 3 | [search](https://www.amazon.com/s?k=perfboard+prototype+board+2.54mm) |
| 8 | Male pin headers | **0.1″ (2.54 mm)** strip | 1 | 1 | [search](https://www.amazon.com/s?k=2.54mm+male+pin+header+strip) |
| 9 | Hookup wire | **22 AWG** solid core | — | 3 | [search](https://www.amazon.com/s?k=22+awg+solid+core+hookup+wire) |

**Power for the MAX9814 (2.7–5.5 V — the USB adapter carries only signal, not power)**

| # | Option (pick one) | Spec (connector) | ~$ | Buy |
|---|-------------------|------------------|----|-----|
| 10a | **3×AA holder** (4.5 V) | holder with bare wire leads | 2 | [search](https://www.amazon.com/s?k=3+aa+battery+holder+with+leads) |
| 10b | USB-A power breakout | **USB-A male** → 5 V + GND pads | 3 | [search](https://www.amazon.com/s?k=usb+a+male+breakout+board) |

On the **Jetson later**, skip #10 — power from the Jetson's **5 V pin** on the 40-pin header.

**Nice-to-have:** digital multimeter for debugging (~$15) — [search](https://www.amazon.com/s?k=digital+multimeter).
**Already have:** soldering iron, solder, kit.

> **Minimum to start soldering:** items 1, 3, 4, 5, 7, 8, 9 + a power source. Items 2 and 6
> are only needed when you're ready to plug into the computer.

**Three gotchas:**
1. The Adafruit **MAX9814 already has the mic on board** — no separate electret capsule needed.
2. Cheap USB adapters have a **mic input**, not a true line-in — fine: tie the MAX9814
   **Gain pin to VDD (40 dB)** so its output doesn't clip the sensitive mic input.
3. Get the audio adapter in **USB-A** (plugs into the Jetson); on a **USB-C-only Mac** add a
   USB-C→USB-A adapter (#2b) for testing.

### Suggested assembly & test order

1. Solder headers on the MAX9814 → power it (3.3–5 V) → confirm `OUT` swings with sound
   (probe with a multimeter or scope).
2. Solder the **1 µF DC-block**, then the **R + C** filter onto perfboard.
3. Wire the **3.5 mm jack** (tip = signal, sleeve = GND); plug into the USB adapter's line-in.
4. Run `src/capture_test.py --list` to find the adapter, then `src/capture_test.py --device N` and
   watch the level meter move — that's the soldered board proven end-to-end.

> Build this **in parallel** with the software: the code already runs on the Mac's built-in
> mic, so the soldering isn't a blocker — when the board's ready you just switch to
> `--device N`.

---

## Software stack (all local, all free)

- **DSP:** numpy · scipy · matplotlib · sounddevice (see [`requirements.txt`](requirements.txt))
- **LLM runtime:** [Ollama](https://ollama.com) (GPU-accelerated on the Jetson)
- **Model:** `qwen2.5:3b` — chosen for strong **tool/function-calling**
  (drop to `llama3.2:1b` / `qwen2.5:1.5b` on a 4 GB board)
- **HTTP tool service:** FastAPI ([`src/service.py`](../src/service.py)) — `/analyze`, `/spectrum`
- **Front-end:** a **reusable terminal-agent engine** ([`src/agent_shell.py`](../src/agent_shell.py))
  — config + OpenAPI tool auto-discovery — served over the LAN as a
  [ttyd](https://github.com/tsl0922/ttyd) web terminal (open a URL, get the agent; no web app).
  Acoustic is just the first *vertical* ([`deploy/agents/`](../deploy/agents/))
- **Orchestration:** [k3s](https://k3s.io) on the Jetson — see [DEPLOY-K3S.md](DEPLOY-K3S.md)

---

## Staged roadmap

| Stage | Track | What | Status |
|-------|-------|------|--------|
| 1 | software | Capture + live FFT spectrogram | 🟢 done ([capture_test](../src/capture_test.py) · [spectrogram](../src/spectrogram.py)) |
| 2 | software | Feature extractor → structured JSON | 🟢 done ([src/features.py](../src/features.py)) |
| 3 | software | Local LLM agent (Ollama + `qwen2.5:3b`) tool-calling | 🟢 done ([src/agent.py](../src/agent.py)) |
| 4 | software | Wrap `features.analyze()` as LLM **tools** | 🟢 done ([src/acoustic_tools.py](../src/acoustic_tools.py)) |
| 5 | software | HTTP tool service (FastAPI `/analyze`, `/spectrum`) | 🟢 done ([src/service.py](../src/service.py)) |
| 6 | deploy | **k3s on the Jetson** — Ollama + tools + terminal UI, on NVMe | 🟢 done ([deploy/k8s/](../deploy/k8s/)) |
| 7 | deploy | **Reusable terminal-agent engine** (ttyd web terminal) | 🟢 done ([src/agent_shell.py](../src/agent_shell.py)) |
| 8 | hardware | Solder the MAX9814 front-end → **live** audio | 🔴 pending board (demo mode now) |
| 9 | software | `classify_sound()` — log-mel CNN | 🔴 stretch |

**Verified end-to-end:** `qwen2.5:3b` autonomously calls the tools and interprets the JSON facts,
running as pods on k3s. The only thing standing between demo mode and live sound is the soldered mic.

---

## Current status & running it

**Deployed on the Jetson (k3s):** the full stack runs as pods — Ollama (GPU), the DSP tool
service, and the agent as a **terminal UI** — all on the NVMe. Open a browser to
`http://<jetson>:30088` and chat. Full runbook → **[DEPLOY-K3S.md](DEPLOY-K3S.md)**. Currently in
**demo mode** (synthetic 60 Hz hum) until the mic is soldered.

**Local dev** (Mac/PC, built-in mic) — the same code, no cluster:
```bash
cd acoustic-analyzer
./.venv/bin/python src/capture_test.py            # talk — watch the level meter
./.venv/bin/python src/agent.py                   # chat: "what's that noise?" / "show me the spectrum"
```

**Next up:**
1. **Solder the MAX9814 front-end**, plug the USB adapter into the Jetson, then flip
   `ACOUSTIC_DEMO=0` + uncomment the `/dev/snd` passthrough → **live** audio (no other changes).
2. `classify_sound()` — a log-mel CNN naming sounds (speech / music / hum / clap).
3. The **NFC "tap-to-analyze"** idea below — it just calls the existing `/analyze` endpoint.

### What to ask it

In **demo mode** the input is always the same synthetic signal — a **60 Hz mains hum with
120/180 Hz harmonics** — so every answer describes *that*. The point is to exercise the
agent → tool loop and see the different facts each question pulls out. Two tools back all of
this: **`analyze`** (returns the numbers) and **`spectrum`** (hands back the `/scope` link).

| Ask it… | What the tool surfaces | Demo answer |
|---|---|---|
| *"What am I listening to?"* | the heuristic `label` | electrical hum (mains-related) |
| *"How loud is it?"* | `rms_db` (loudness) | ~ −10 to −14 dB |
| *"What's the dominant frequency?"* | `dominant_hz` | ≈ 60 Hz |
| *"Is there any mains hum? 50 or 60 Hz?"* | `hum_60hz_score` | high — it's 60 Hz |
| *"What tones or harmonics do you see?"* | `peaks_hz` | 60, 120, 180 Hz |
| *"Which frequency band has the most energy?"* | `band_energy` (6 bands) | the bass / sub band |
| *"Is this sound bright or dark?"* | `spectral_centroid_hz` | dark (low centroid) |
| *"Is it tonal or noisy?"* | `zero_crossing_rate` + peaks | tonal (steady hum) |
| *"Show me the spectrum"* / *"let me see it"* | `spectrum` → `/scope` URL | a browser link to the live waterfall |

Chain them naturally too — *"how loud is it and is that hum?"*, or *"describe this sound and
then show me the spectrum."* The last one is the fun one: it answers in the terminal **and**
gives you a link to the magma spectrogram that a terminal can't draw.

> Once the mic is soldered and `ACOUSTIC_DEMO=0`, the **same questions** work on **real
> sound** — whistle, clap, hum a note, hold up a phone speaker — and the answers change with
> what it actually hears.

---

## Future ideas

Fun extensions floated for the project (parked for later):

### NFC + iPhone
> **iPhone NFC constraint:** iPhones can *read* NDEF tags and *trigger Shortcuts*, but can't
> act as a freely programmable tag/card (Apple Pay/Wallet only). So design around
> **iPhone-as-reader** + **physical tags**, not "Jetson reads the phone."

- **① iPhone Shortcut → tap sticker → trigger the Jetson** ⭐ *(highest wow, ~$0.30, no app code)*
  Stick a cheap NFC tag on the enclosure. iOS **Shortcuts → Automation → NFC → Get Contents
  of URL** hits the Jetson's HTTP endpoint. Tap the iPhone on the device → Jetson records
  + analyzes → phone shows/speaks *"60 Hz mains hum detected."* Needs only the HTTP endpoint
  (see "Next up" #1) — no Xcode, no app.
- **② PN532 NFC reader on the Jetson** ⭐ *(the real EE/soldering extension)*
  Solder a **PN532 module** (~$5, I2C/SPI/UART) to the Jetson. Physical NFC tokens become
  commands: tap a "record" card → capture; "hum test" card → run a profile; "show spectrum"
  card → render the image. Teaches embedded buses (I2C); the same tags the iPhone can also read.
- **③ Tag → opens the live dashboard on the iPhone** *(simplest)*
  Write one NDEF tag with the URL of the Jetson's web UI. Tap phone → browser opens the live
  acoustic dashboard. Zero coding.

### Other cool directions (acoustic / EE)
- **Sound-reactive OLED / LED bar** to solder — live VU meter or spectrum on an SSD1306 OLED.
- **Direction finding** with two mics — TDOA/beamforming to point at a sound source (real DSP).
- **Local wake-word / voice** to talk to the agent hands-free.
- **"Shazam for household sounds"** — the Stage-6 classifier naming appliances, alarms, etc.
