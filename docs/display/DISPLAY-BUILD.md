# Sound-reactive display — OLED + LED bar (schematic & BOM)

The second soldering build: a **live visual** of what the analyzer hears. Two displays, two
buses, driven straight off the Jetson's 40-pin header — nothing new upstream, it just reads the
DSP facts you already compute.

- **SSD1306 OLED (128×64, I²C)** — a 6-bar **spectrum** + dominant-Hz / dB **text**.
- **APA102 "DotStar" LED bar (SPI)** — an ambient **VU meter**: brightness tracks loudness,
  colour walks green → amber → red as it gets louder.

> **Why this one is "a bit harder" than the mic front-end:** two different serial buses (I²C
> *and* SPI), a **3.3 V → 5 V level shifter** (a real logic-level lesson), and an actual
> **current budget** — 16 RGB LEDs can pull ~1 A, more than the header wants to give. That
> current-and-grounding reasoning is the whole point.

Signal chain (this build starts where the mic build ends — at the analyzed audio):

```
mic → MAX9814 → USB adapter → Jetson → features.analyze() ─┬─► OLED  (I²C: spectrum bars + text)
                                                            └─► LED bar (SPI: VU glow)
```

📐 **Visual schematic:** [`display-wiring.svg`](display-wiring.svg) — pin-level map + solder
checklist, print-friendly. ASCII version below.

---

## 1 · The data it reacts to (no new DSP)

`features.analyze()` in [src/features.py](../../src/features.py) already returns everything both
displays need. You render its output — you don't add signal processing.

| Display element | Field from `analyze()` | Notes |
|---|---|---|
| **6 spectrum bars** (OLED) | `band_energy` — 6 keys `sub_20_60`…`high_6k_20k` | one bar per band; normalise per-frame to 0–63 px height |
| **Level / VU** (LED bar) | `rms_db` (≈ −60…0 dB) | map to how many LEDs light + overall brightness |
| **Header text** (OLED) | `dominant_hz`, `rms_db`, `label` | e.g. `60 Hz · −12 dB · hum` |
| **Colour of the VU** | `rms_db` (or `dominant_hz`) | green (quiet) → amber → red (loud) |

The six `band_energy` bins line up one-to-one with six OLED bars **and** can colour six zones of
the LED bar — that clean 6-way split is why the OLED is 6 bars wide.

---

## 2 · Schematic (ASCII)

```
        JETSON ORIN NANO — 40-pin header                     ┌──────────────────────────┐
   ┌───────────────────────────────────────┐                │  SSD1306 OLED  128×64     │
   │ pin 1  3.3V ───────────────────────────┼──ORANGE────────┤ VCC                       │
   │ pin 3  I2C1_SDA ───────────────────────┼──TEAL──────────┤ SDA   (addr 0x3C)         │
   │ pin 5  I2C1_SCL ───────────────────────┼──TEAL──────────┤ SCL                       │
   │ pin 6  GND ──┐                          │        ┌───────┤ GND                       │
   │              │                          │        │       └──────────────────────────┘
   │ pin 2  5V ───┼──RED──┬───────────────────────────┼──────────────┐
   │              │       │                  │        │               │  (5V rail)
   │ pin19 SPI1_MOSI ─────┼──MAGENTA──┐      │        │               │
   │ pin23 SPI1_SCK ──────┼──BLUE──┐  │      │        │               │
   │ pin20 GND ───┤       │        │  │      │        │               │
   └──────────────┘       │        │  │      │        │               │
                          │        │  │      │        │      ┌────────┴──────────────────┐
                     5V ──┘        │  │      │        │      │ 74AHCT125  (DIP-14)        │
                                   │  │      │        │      │ 3.3V-in → 5V-out buffer    │
                                   │  └──────┼────────┼──────┤ 1A (pin2)                  │
                                   │         │        │      │ 1Y (pin3) ──MAGENTA──┐     │
                                   └─────────┼────────┼──────┤ 2A (pin5)            │     │
                                             │        │      │ 2Y (pin6) ──BLUE──┐  │     │
                          VCC(14)=5V ────────┘        │      │ VCC(14)=5V         │  │     │
                          OE1,OE2(1,4)→GND            └──────┤ GND(7)             │  │     │
                          0.1µF VCC→GND (decouple)           └────────────────────┼──┼─────┘
                                                                                  │  │
                                                     ┌────────────────────────────┼──┼──────────┐
                                                     │ APA102 / DotStar LED bar    │  │          │
                                       5V rail ──────┤ 5V                          │  │          │
                                     GND rail ───────┤ GND                         │  │          │
                                                     │ DI (data in) ◄──────────────┘  │          │
                                                     │ CI (clock in) ◄────────────────┘          │
                                                     │  ●●●●●●●● (8–16 RGB, VU meter)             │
                                                     └────────────────────────────────────────────┘

        ── GND: one common rail. Jetson GND ─ OLED GND ─ 125 pin7 ─ LED GND all tie together ──
```

**Colour key:** ORANGE = 3.3 V · RED = 5 V · TEAL = I²C · MAGENTA = SPI data (MOSI) ·
BLUE = SPI clock (SCK) · dark = GND.

### The three critical rules baked into that drawing

1. **OLED runs at 3.3 V, LEDs run at 5 V.** Power the OLED from **pin 1 (3.3 V)** so its I²C
   pull-ups sit at 3.3 V — matching the Jetson's logic and needing **no** shifter. The SSD1306
   is happy at 3.3 V.
2. **The LED bar's data/clock need 5 V logic**, and the Jetson only swings 3.3 V. An APA102
   input treats "high" as ≈0.7 × 5 V ≈ **3.5 V**, so a bare 3.3 V line is marginal/flaky. The
   **74AHCT125** buffers MOSI+SCK up to a clean 5 V. (AHCT specifically because it reads a 3.3 V
   input as a valid HIGH — a plain HC part won't.)
3. **One common ground.** Every GND — Jetson, OLED, level-shifter pin 7, LED bar — meets on a
   single rail. Data is meaningless without a shared reference; this is the #1 "it flickers /
   does nothing" cause.

---

## 3 · Pin tables

### Jetson Orin Nano 40-pin header (the pins we use)

| Header pin | Signal | Goes to |
|---|---|---|
| **1** | 3.3 V | OLED `VCC` |
| **2** | 5 V | 74AHCT125 `VCC` + LED `5V`* |
| **3** | `I2C1_SDA` | OLED `SDA` |
| **5** | `I2C1_SCL` | OLED `SCL` |
| **6, 20** | GND | common ground rail |
| **19** | `SPI1_MOSI` | 74AHCT125 `1A` → LED `DI` (data) |
| **23** | `SPI1_SCK` | 74AHCT125 `2A` → LED `CI` (clock) |

\* Power a **16-LED** bar from a **separate 5 V supply** (common ground) — see §5.

> **Enable the buses first (one-time, on the Jetson):** SPI isn't on by default.
> `sudo /opt/nvidia/jetson-io/jetson-io.py` → *Configure 40-pin header* → enable **spi1**, save,
> reboot. I²C is already on — verify the OLED with `sudo i2cdetect -y 7` (or `-y 1`); it should
> show **0x3C**.

### 74AHCT125 (DIP-14) — quad buffer, we use 2 of the 4 channels

| Pin | Name | Wire to |
|---|---|---|
| 1 | 1OE (enable, active-low) | **GND** |
| 2 | 1A (in) | Jetson **MOSI** (pin 19) |
| 3 | 1Y (out) | LED **DI** |
| 4 | 2OE | **GND** |
| 5 | 2A (in) | Jetson **SCK** (pin 23) |
| 6 | 2Y (out) | LED **CI** |
| 7 | GND | ground rail |
| 14 | VCC | **5 V** (+ 0.1 µF to GND, right at the chip) |
| 9,10,12,13 | unused 3A/3OE/4OE/4A | tie **3A,4A → GND** and **3OE,4OE → VCC** (park them) |

### APA102 / DotStar bar — use the **input** end (DI/CI, not DO/CO)

| Pad | Wire to |
|---|---|
| 5V | 5 V rail |
| GND | common ground |
| **DI** (data in) | 74AHCT125 pin 3 (1Y) |
| **CI** (clock in) | 74AHCT125 pin 6 (2Y) |

> DotStar strips are directional — arrows print on the strip. Feed the end whose pads say
> **DI/CI**; the far end's **DO/CO** is for chaining. Wire the wrong end → nothing lights.

---

## 4 · Bill of materials (~$18)

Amazon **search** links (they don't go stale — pick the current best Prime listing). You already
have the passives assortment and perfboard from the mic build.

**Modules**

| # | Component | Exact spec (incl. connector) | Qty | ~$ | Buy |
|---|---|---|---|---|---|
| 1 | **SSD1306 OLED** | 0.96″ **128×64**, **I²C**, 4-pin header **VCC·GND·SCL·SDA**, addr 0x3C | 1 | 5 | [search](https://www.amazon.com/s?k=0.96+inch+ssd1306+oled+i2c+128x64) |
| 2 | **APA102 / DotStar** LED bar | **APA102** (a.k.a. DotStar/SK9822) — **clocked SPI**, 4 pads **5V·GND·DI·CI**; 8-LED stick or a short strip. *Not WS2812/NeoPixel* | 1 | 8 | [search](https://www.amazon.com/s?k=apa102+dotstar+led+strip) |
| 3 | **74AHCT125** level shifter | DIP-14 through-hole, **AHCT** family (not HC/HCT-less) | 1 | 1 | [search](https://www.amazon.com/s?k=74AHCT125+DIP) |

**Support parts** (mostly from your kit)

| # | Component | Value / spec | Qty | ~$ | Buy |
|---|---|---|---|---|---|
| 4 | DIP-14 IC socket | 14-pin, 2.54 mm — socket the chip, don't cook it | 1 | 0.3 | [search](https://www.amazon.com/s?k=14+pin+dip+ic+socket) |
| 5 | Ceramic cap (decouple) | **0.1 µF** ("104") VCC→GND at the 74AHCT125 | 1 | — | kit |
| 6 | Electrolytic cap (inrush) | **470–1000 µF**, ≥6.3 V, across LED **5V/GND** near the strip | 1 | — | kit |
| 7 | Resistor, ¼ W | **330 Ω** in series on the **DI** line (tames ringing into pixel 1) | 1 | — | kit |
| 8 | Female header socket | 4-pin (OLED) + **1×14 or 2×** for the module — mount, don't solder-through | 1–2 | 1 | [search](https://www.amazon.com/s?k=2.54mm+female+pin+header+socket) |
| 9 | Dupont jumpers | **F–F**, to reach the 40-pin header | 1 pk | 2 | [search](https://www.amazon.com/s?k=dupont+female+to+female+jumper+wires) |
| 10 | Perfboard, headers, 22 AWG wire | — | — | — | *(have — mic build)* |

**Power — only if you drive a bright / 16-LED bar** (an 8-LED VU off pin 2 is fine)

| # | Option | Spec | ~$ | Buy |
|---|---|---|---|---|
| 11 | 5 V USB supply + breakout | **USB-A → 5 V + GND pads**, ≥2 A; **tie its GND to the Jetson GND** | 3 | [search](https://www.amazon.com/s?k=usb+a+male+breakout+board) |

> **Minimum to start:** items 1, 2, 3, 4, 8, 9 + your kit passives. That's the whole build.

---

## 5 · The current budget (the EE lesson)

Each APA102 LED at **full white** ≈ 3 × 20 mA = **60 mA**.

| Bar | Full-white worst case | Off the Jetson 5 V pin? |
|---|---|---|
| **8 LEDs** | ~480 mA | ✅ OK — a VU meter rarely lights all-white; keep software brightness ≤ ~50 % |
| **16 LEDs** | ~960 mA | ⚠️ **Separate 5 V supply.** The header pin shouldn't source ~1 A. Common the grounds. |

Two habits that keep it clean and un-fried:
- **470–1000 µF across the strip's 5V/GND**, close to the bar — soaks the switch-on inrush so
  the rail doesn't sag and reset the first pixel.
- **330 Ω in series on DI** — damps reflections on the data line into pixel 1.
- Cap brightness in software anyway; a VU meter looks better dim, and it slashes current.

---

## 6 · Before you power it — multimeter check

Meter on **continuity/beep**:

| Probe A | Probe B | Beep? |
|---|---|---|
| Jetson GND · OLED GND · 125 pin7 · LED GND | each other | ✅ all one rail |
| 5 V rail | GND | ❌ **NO** — beep = short, don't power |
| 3.3 V (OLED VCC) | 5 V rail | ❌ no — keep the two supplies separate |
| 125 pin 1 (1OE) & pin 4 (2OE) | GND | ✅ yes — buffers must be enabled |

Then meter **voltage**, powered, before plugging modules in: pin 1 ≈ **3.3 V**, pin 2 ≈ **5 V**,
74AHCT125 pin 14 ≈ **5 V**. Only then seat the OLED and the LED bar.

---

## 7 · Assembly & bring-up order

1. **Socket the 74AHCT125** (DIP-14 socket into perfboard); wire VCC/GND + the 0.1 µF; tie the
   two OE pins low and park the unused channel. *Chip stays out* until §6 passes.
2. **OLED** — 4 wires to pins 1/3/5/6. On the Jetson: `sudo i2cdetect -y 7` → **0x3C** confirms it.
3. **Level shifter → LED bar** — MOSI→1A, SCK→2A, 1Y→DI, 2Y→CI; add the 330 Ω on DI and the bulk
   cap across the bar's 5V/GND.
4. **Run the multimeter check (§6)**, drop the chip into its socket, power up.
5. **Software smoke test** (below) — light one pixel, print one line to the OLED, *then* wire in
   `analyze()`.

---

## 8 · Software hooks

Python, same venv as the rest of the project.

- **OLED:** `luma.oled` (SSD1306 driver) + Pillow to draw the 6 bars and the text line.
  `pip install luma.oled`.
- **LED bar:** talk to `/dev/spidev0.0` with `spidev` and hand-frame APA102 (start frame
  `0x00000000`, per-LED `0xE0|bright, B, G, R`, end frame) — the most reliable path on the
  Jetson. `pip install spidev`.

Both read one dict — `features.analyze(samples)` — so the display is a thin renderer:

```python
facts = analyze(samples)                     # already in the project
bars  = normalize(facts["band_energy"])      # 6 values → 6 OLED bars / LED zones
level = facts["rms_db"]                       # → how many LEDs + brightness + colour
oled_show(bars, f'{facts["dominant_hz"]:.0f} Hz · {facts["rms_db"]:.0f} dB')
led_vu(level)
```

Wire it into the existing capture loop (or the `/analyze` service) so the display updates every
frame — no changes to the DSP or the LLM path.

---

## See also
- **[PROJECT.md](../PROJECT.md)** — the analyzer, the mic front-end BOM, why each part
- **[HARDWARE-BENCH.md](../mic-frontend/HARDWARE-BENCH.md)** — soldering technique, socket-don't-cook, symptom→fix
- **[DEPLOY-K3S.md](../platform/DEPLOY-K3S.md)** — the `/dev/*` passthrough & `make restart` bits for the Jetson
