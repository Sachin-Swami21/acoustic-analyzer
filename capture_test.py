"""
Stage 1 - prove the mic works.

Two modes:
  python capture_test.py            # live RMS level meter (Ctrl-C to stop)
  python capture_test.py --list     # list audio input devices
  python capture_test.py --record 3 # record 3 seconds to recording.wav

On the Mac this uses the built-in mic so you can test today.
On the Jetson, plug in the USB audio adapter (fed by the soldered
MAX9814 board) and pick it with --device N (see --list).
"""

import argparse
import sys

import numpy as np
import sounddevice as sd
from scipy.io import wavfile

SAMPLE_RATE = 44100


def list_devices():
    print(sd.query_devices())


def level_meter(device=None):
    """Print a live text VU meter so you can confirm the mic responds."""
    print("Listening... make some noise. Ctrl-C to stop.\n")

    def callback(indata, frames, time_info, status):
        if status:
            print(status, file=sys.stderr)
        rms = np.sqrt(np.mean(indata[:, 0] ** 2))
        db = 20 * np.log10(rms + 1e-9)
        bars = int(np.clip((db + 60) / 60 * 40, 0, 40))  # map -60..0 dB to 0..40
        print(f"\r{db:6.1f} dB |{'#' * bars}{' ' * (40 - bars)}|", end="")

    with sd.InputStream(channels=1, samplerate=SAMPLE_RATE,
                        device=device, callback=callback):
        try:
            while True:
                sd.sleep(100)
        except KeyboardInterrupt:
            print("\nStopped.")


def record(seconds, device=None, path="recording.wav"):
    print(f"Recording {seconds}s...")
    audio = sd.rec(int(seconds * SAMPLE_RATE), samplerate=SAMPLE_RATE,
                   channels=1, device=device)
    sd.wait()
    wavfile.write(path, SAMPLE_RATE, audio)
    print(f"Saved {path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="list audio devices")
    ap.add_argument("--record", type=float, metavar="SEC", help="record N seconds to wav")
    ap.add_argument("--device", type=int, default=None, help="input device index")
    args = ap.parse_args()

    if args.list:
        list_devices()
    elif args.record:
        record(args.record, device=args.device)
    else:
        level_meter(device=args.device)
