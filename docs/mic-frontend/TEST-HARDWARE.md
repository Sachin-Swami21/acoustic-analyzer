# Testing the soldered front-end — on a Mac or Windows PC (no Jetson)

You do **not** need the Jetson to test your soldering. The front-end
(**mic → MAX9814 → filter → 3.5 mm jack → USB audio adapter**) shows up as an ordinary
**USB microphone** on any computer. Plug it into a Mac or Windows PC, run the same Python
scripts, and confirm the board works end-to-end.

> **Which OS path?**
> - **macOS** → easy. Follow **Path A**.
> - **Windows** → use **native Windows Python** (Path B). It sees the USB audio device directly.
> - **Windows + WSL2** → possible but **not recommended** for this: WSL can't see a USB audio
>   device without extra passthrough tooling. Only use **Path C** if you specifically need Linux.

---

## What "working" looks like (success criteria)

After plugging in the board and running the tests, you should see:

1. The USB adapter **listed** as an input device.
2. The **level meter moves** when you tap the mic or talk → mic + amp + wiring + jack all good.
3. The **spectrogram** shows a rising line when you whistle a rising note.
4. `src/features.py` prints JSON with a sensible **dominant frequency** and, near a power brick, a
   high **60 Hz hum score**.

If all four pass, the soldering is correct. If not, jump to **Troubleshooting**.

---

## Before you start (both OSes)

- Solder the board and **power the MAX9814** (3–5 V). It needs power even for a PC test.
- Plug the **3.5 mm plug into the USB audio adapter's MIC input** (pink).
- Plug the **USB adapter** into the computer.
  - Adapter is **USB-A**; most modern Macs are **USB-C** → use a USB-C→USB-A adapter.
- Get the project files on the computer (clone the repo or copy the folder).

---

## Path A · macOS

```bash
cd acoustic-analyzer

# 1. Create the environment and install deps
python3 -m venv .venv
./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install -r requirements.txt

# 2. Find your USB adapter in the device list
./.venv/bin/python src/capture_test.py --list
#    → note the index number next to your USB audio adapter (e.g. 2)

# 3. Live level meter — TAP THE MIC / TALK, the bar should move
./.venv/bin/python src/capture_test.py --device 2

# 4. Live spectrogram — whistle a rising note, watch the line climb
./.venv/bin/python src/spectrogram.py --device 2

# 5. Structured facts — make a sound, read the JSON (dominant Hz, hum score...)
./.venv/bin/python src/features.py --device 2 --seconds 2
```

- **First run:** macOS asks for **microphone permission** for your terminal — click **Allow**,
  then re-run. (If you miss it: System Settings → Privacy & Security → Microphone → enable your terminal.)
- `sounddevice` installs a bundled PortAudio on macOS — no extra system install needed.

---

## Path B · Windows (native — recommended)

Use **PowerShell** (not WSL). Windows sees the USB audio adapter automatically.

```powershell
# 0. Install Python 3 from https://python.org  (CHECK "Add python.exe to PATH" during install)

cd acoustic-analyzer

# 1. Create the environment and install deps
py -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r requirements.txt

# 2. Find your USB adapter in the device list
.\.venv\Scripts\python src/capture_test.py --list
#    → note the index number next to your USB audio adapter

# 3. Live level meter — TAP THE MIC / TALK, the bar should move
.\.venv\Scripts\python src/capture_test.py --device 2

# 4. Live spectrogram — whistle a rising note
.\.venv\Scripts\python src/spectrogram.py --device 2

# 5. Structured facts
.\.venv\Scripts\python src/features.py --device 2 --seconds 2
```

**Windows specifics:**
- **Microphone privacy:** Settings → Privacy & security → **Microphone** → turn on
  *"Let desktop apps access your microphone."* Otherwise recording is silent.
- **Input level:** Settings → System → Sound → your USB adapter → set input volume ~75%. If the
  signal clips (meter pinned at 0 dB), lower it, or set the MAX9814 **GAIN pin to VDD (40 dB)**.
- `sounddevice`'s pip wheel bundles PortAudio on Windows — no extra install.
- No `py` launcher? Use `python` instead of `py`.

---

## Path C · Windows + WSL2 (advanced, only if you need Linux)

WSL2 has **no access to USB audio by default**. You must forward the USB device from Windows
into WSL with **usbipd-win**, then set up audio inside WSL. This is fiddly — **prefer Path B**
unless you specifically need to test under Linux.

```powershell
# --- in Windows PowerShell (Admin) ---
winget install usbipd                     # install usbipd-win
usbipd list                               # find the BUSID of the USB audio adapter
usbipd bind   --busid <BUSID>             # one-time
usbipd attach --wsl --busid <BUSID>       # forward it into WSL (re-run after each replug)
```

```bash
# --- inside WSL2 (Ubuntu) ---
lsusb                                      # confirm the audio device now appears
sudo apt update
sudo apt install -y python3-venv portaudio19-dev libsndfile1 alsa-utils
arecord -l                                 # should list the USB capture device

cd acoustic-analyzer
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
./.venv/bin/python src/capture_test.py --list
./.venv/bin/python src/capture_test.py --device <N>
```

> If `arecord -l` shows nothing or capture is silent, the audio bridge isn't cooperating —
> **fall back to native Windows (Path B).** It's not worth fighting WSL audio just to test a board.

---

## What each test proves about your soldering

| Test | If it works | If it fails, suspect |
|------|-------------|----------------------|
| `--list` shows the adapter | USB adapter + cable OK | adapter not seated / wrong USB port |
| Level meter moves on sound | mic → MAX9814 → filter → jack → adapter all wired right | power to MAX9814, solder joints, jack tip/sleeve |
| Spectrogram line tracks a whistle | frequency response intact | anti-alias filter values, cold joints |
| `src/features.py` hum score high near a power brick | full analysis chain OK | grounding, shielding |

---

## Troubleshooting (solder-focused)

- **Adapter not in `--list`** → reseat it; try another USB port; confirm it's a mic-**input**
  adapter, not headphone-only.
- **Meter dead flat / silence** → (1) is the **MAX9814 powered**? measure 3–5 V at its VDD/GND.
  (2) Check the **3.5 mm jack**: tip = signal, sleeve = GND — a swapped or cold joint here is the
  usual culprit. (3) Reflow suspicious joints; look for bridges.
- **Meter pinned / distorted** → too much gain: set MAX9814 **GAIN → VDD (40 dB)**, and lower the
  OS input level.
- **Faint but present** → increase OS input level / mic boost; check the DC-block cap orientation
  if electrolytic (**+ toward MAX9814 OUT**).
- **Works on the meter but weird spectrum** → revisit the **RC filter** (1 kΩ + 10 nF) placement.
- **Permission errors** → grant microphone access (macOS Privacy; Windows Microphone privacy).

---

Once the board passes here, it will behave identically on the Jetson — the code is the same, you
just pass `--device N` for the USB adapter. See [JETSON-SETUP.md](../platform/JETSON-SETUP.md).
