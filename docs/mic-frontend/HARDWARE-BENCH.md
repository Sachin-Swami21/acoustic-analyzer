# Hardware bench guide — wiring, soldering & troubleshooting

The page to keep open while you build and bring up the analog front-end. Design rationale and the
full BOM live in **[PROJECT.md](../PROJECT.md)**; how to *test* a finished board on a Mac/PC is in
**[TEST-HARDWARE.md](TEST-HARDWARE.md)**. This doc is the in-between: how to wire it, how to solder
it, and what to do when it doesn't work.

Signal chain, for reference:

```
mic → MAX9814 (amp) → 1µF DC-block → RC low-pass → 3.5mm TRS → USB audio adapter → host
```

---

## 1 · Pinout reference

### MAX9814 (5 pins) — only three actually go anywhere

| Pin | Connect to | Notes |
|---|---|---|
| **VDD** | +3.3–5 V | Jetson 5 V header pin or any USB 5 V. A 0.1 µF cap VDD→GND close to the module tames supply noise. |
| **GND** | ground rail → jack **sleeve** | the common for signal *and* power |
| **OUT** | → 1 µF DC-block → RC filter → jack **tip** | the audio |
| **GAIN** | **jumper to VDD** = 40 dB | 40 dB keeps a sensitive mic-input from clipping. (GND = 50 dB, floating = 60 dB.) |
| **A/R** | leave open | default attack/release |

`GAIN` is a ~10 mm jumper to the neighbouring VDD pad — no wire run. `A/R` gets nothing.

### 3.5 mm TRS plug — Tip / Ring / Sleeve

Reading from the pointy end toward the cable:

```
   Tip ───── Left channel   → YOUR SIGNAL
   Ring ──── Right channel  → leave unconnected (mono source)
   Sleeve ── Ground/common  → the long contact by the cable
```

| Contact | Function | Your build | Usual wire (VERIFY!) |
|---|---|---|---|
| **Tip** | Left channel | **signal** (RC filter output) | white |
| **Ring** | Right channel | **leave floating** | red |
| **Sleeve** | Ground | **GND**, common with MAX9814 GND | bare shield / black |

**Why the Ring floats:** your source is mono, so there's nothing for the right channel. A PC
**mic jack supplies bias voltage** (plug-in power); tying Ring→Sleeve could short that bias to
ground, and Ring→Tip would let it fight your signal. Left-channel-only is exactly what the code
wants — `_read_wav()` takes `data[:,0]` and `_record()` uses `channels=1`.
*(True line-in and want both channels? Ring→Tip is fine there. On a mic jack, don't.)*

> ⚠️ **Combo (headset) jack trap.** If your adapter has **one 4-pole jack** instead of separate
> **pink mic + green headphone** jacks, the pinout changes completely — CTIA order is
> **Tip = L-out, Ring1 = R-out, Ring2 = GND, Sleeve = MIC**. The mic is on the **sleeve**, not the
> tip. A 3-pole TRS plug in a combo jack shorts the mic to ground → **records silence**. Your BOM
> calls for a separate **pink 3-pole mic input**; if yours is a combo jack you need a **4-pole
> TRRS** plug with the signal on the sleeve.

> **Field note (combo jack — confirmed the hard way).** A **MOSWAG "USB-to-microphone" adapter**
> turned out to be a 4-pole **combo jack** despite the name. Symptom: the board was verified good
> (AC signal measured all the way to the plug tip) but `arecord` still captured only the ±20 noise
> floor. **Backing the 3-pole plug out one notch** (partial insertion) aligned the tip with the
> mic contact and the samples jumped to ±5000 — that's the proof it's a combo jack. **Permanent
> fix:** use an adapter with a **separate pink 3-pole mic jack** — the **Sabrent AU-MMSA** (two
> jacks, pink + green) is the reliable Linux/Jetson pick — or re-terminate your cable to a **4-pole
> TRRS** plug with signal on the sleeve. When buying, insist on **two** 3.5 mm ports in the photos;
> avoid any single-port "headset" adapter. Verify with `arecord -l` after plugging in.

---

## 2 · Soldering the module to the perfboard

Your BOM uses **trace-less perfboard** — you make every connection by hand underneath.

### Socket it — don't solder the module straight down

| | Female header socket ✅ | Solder module through |
|---|---|---|
| Removable / reworkable | **yes, unplug it** | no — desolder 5 pins |
| Protects the $8 module | **yes** | it takes every reflow |
| Cost | one 5-pin socket (~$0.20) | none |

The MAX9814 is the pricey part *with the mic on it* and it's heat-sensitive. Socket it so you can
do all the messy board soldering with the module **unplugged and safe**, then drop it in last.

**Steps**
1. **Male header onto the module** — pins down. *Jig:* stand the header in a breadboard so pins are
   vertical, drop the module on top, solder.
2. **Female socket into the perfboard** — *jig:* plug the module into the socket, set the assembly on
   the board, solder the **socket's** pins from underneath. The module keeps the socket square.
3. **Unplug the module**, then wire the rest of the board freely.

### The one technique that makes headers easy
**Tack one end pin first.** Solder a single pin → check from the side → tilted? Re-melt that *one*
joint and nudge square → *then* solder the rest. Fixing one joint is trivial; five crooked ones is
misery.

**A good joint:** heat the pad **and** pin together (~2–3 s), feed solder **into the joint** (not
onto the tip), remove solder, then iron. You want a shiny **cone** — not a ball (didn't wet), not
dull/grainy (cold joint).

### Point-to-point wiring
- Build a **ground rail** along one row first, drop every GND into it — short ground = quiet analog.
- Use **bare solid-core wire** (or the legs you clipped off R/C) laid along the underside, tacked at
  each pad.
- Keep the **OUT → cap → RC → tip** run short and away from the VDD/power wire.

---

## 3 · Before you power it — 30-second multimeter check

Set the meter to **continuity/beep**. This catches the mistakes that kill parts:

| Probe A | Probe B | Should it beep? |
|---|---|---|
| MAX9814 **OUT** side of cap | jack **tip** | ✅ yes (through R) |
| MAX9814 **GND** | jack **sleeve** | ✅ yes |
| **VDD** | **GND** | ❌ **NO** — a beep = short, do not power! |
| jack **tip** | jack **sleeve** | ❌ no (a faint reading through the shunt C is ok) |
| jack **ring** | anything | ❌ no (it's floating) |

If VDD↔GND beeps, you have a solder bridge — find and clear it **before** connecting power.

---

## 4 · Troubleshooting — symptom → cause → fix

Work top-down: confirm the OS sees the device first, then chase the signal.

### The device isn't detected at all
`src/capture_test.py --list` shows nothing / `arecord -l` says "no soundcards found" /
`/healthz` reports `microphone_available: false`, `input_devices: []`.

| Likely cause | Fix |
|---|---|
| USB adapter not enumerated | Re-seat it; try another port; `lsusb` (Linux) / System Info (Mac) should list a USB audio device. It's the ADC — no adapter, no input. |
| On the **Jetson**: no capture node | `ls /dev/snd` — you need a `pcmC?D?**c**` (`c` = capture). Onboard nodes are all `…p` (playback). The USB adapter adds the `c` node. |
| Pod started before the adapter was plugged in | `make restart` — ALSA/PortAudio only enumerates at startup (see [DEPLOY-K3S.md](../platform/DEPLOY-K3S.md)). |
| Wrong device selected | `src/capture_test.py --list`, then pass `--device N`. |

### Device detected, but records **silence** (flat level meter)
This is the most common one — the OS sees the adapter, but no audio arrives.

| Likely cause | Fix |
|---|---|
| **Combo jack** (mic on sleeve, not tip) | See §1's warning — the #1 cause of silence. Separate pink mic jack, or a TRRS plug. |
| No power to the MAX9814 | Meter VDD↔GND = ~3.3–5 V. Remember: the USB cable carries **signal only**, not power. |
| Tip/Ring/Sleeve miswired | Recheck §3 continuity. Signal must be on **tip**, ground on **sleeve**. |
| Gain too low / mic dead | Confirm `GAIN`→VDD is 40 dB (not accidentally to GND); tap the mic capsule hard. |
| Cold joint on OUT/tip path | Reflow the OUT, cap, R, and tip joints — dull/grainy = cold. |
| macOS mic permission | Grant the terminal mic access when prompted (or System Settings → Privacy → Microphone). |

### Is the mic module even producing signal? (isolate board vs adapter)
Before blaming the adapter or the solder, **prove the module outputs audio.** Two meter checks at
the MAX9814 **OUT** pin (probe **OUT → GND**):

| Meter mode | Condition | Healthy reading | Bad reading → meaning |
|---|---|---|---|
| **DC volts** | powered, silent | **~1.2 V** (internal bias) | **0 V** = unpowered · **≈ VDD (rail)** = dead chip |
| **AC volts** | powered, shout at mic | number **rises** from ~0 | **stays flat** = capsule/module not hearing sound |

If OUT idles at ~1.2 V **and** the AC reading rises when you shout, the module is good. Now **trace
the signal forward**: measure AC volts at the **plug-tip (signal) wire** while shouting. If it
rises there too, the whole board is proven end-to-end and the fault is the **adapter/plug** — go to
the combo-jack note in §1. This "follow the AC signal one node at a time" method beats guessing.

> **Dead-module tell.** OUT stuck at the supply rail (**≈ VDD**) instead of ~1.2 V means the
> MAX9814 is fried — almost always a **reverse-polarity moment** (VDD/GND swapped) while wiring
> power. These chips die instantly and silently. Swap the module; **before powering the new one,
> meter red→VDD and black→GND** to confirm polarity so you don't kill a second one.

### Sound comes through but it's **wrong**

| Symptom | Cause | Fix |
|---|---|---|
| **Very quiet**, meter barely moves | Gain too low, or feeding line-in with a weak signal | GAIN floating (60 dB) or →GND (50 dB) for more gain — but watch for clipping |
| **Clipping / harsh distortion** | Gain too high into a sensitive **mic** input | GAIN→**VDD (40 dB)**; use **line-in** if the adapter has it |
| **Constant loud hum** (ironic, given the project) | Ground loop / long unshielded leads / noisy supply | Shorten leads, solid single ground rail, 0.1 µF VDD→GND decoupling, power from a clean 5 V |
| **Low-freq thump / DC offset / pop** | DC-block cap missing or backwards | 1 µF in series on OUT; if electrolytic, **+** toward MAX9814 OUT |
| **Crackle / cuts in and out** | Cold joint or loose header/socket | Wiggle-test while watching the meter; reflow the offender |
| **Muffled / no highs** | RC cutoff too low | You want `fc ≈ 16 kHz` (R = 1 kΩ, C = 10 nF). A far bigger C rolls off treble |
| Signal only on one side / missing | Signal on **ring** not **tip**, or T/R swapped | Move signal to **tip**; leave ring floating |

### Sanity check with the software
Once audio flows, confirm the pipeline agrees with your ears:

```bash
# level meter — tap the mic, the bar must move
./.venv/bin/python src/capture_test.py

# structured facts — whistle ~1 kHz, dominant_hz should track it
./.venv/bin/python src/agent.py      # then: "what's that noise?"
```

If the level meter moves but `dominant_hz` is stuck at ~60 Hz regardless of what you make, you're
picking up **mains hum louder than your test tone** — improve grounding/shielding (rows above).

---

## See also
- **[PROJECT.md](../PROJECT.md)** — wiring diagram, BOM, why each component
- **[TEST-HARDWARE.md](TEST-HARDWARE.md)** — full test procedure on a Mac or Windows PC
- **[DEPLOY-K3S.md](../platform/DEPLOY-K3S.md)** — bring-up on the Jetson (the `make restart` / `/dev/snd` bits)
