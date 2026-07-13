"""
Stage 2 - see the sound. Live scrolling spectrogram.

  python spectrogram.py
  python spectrogram.py --device 2   # pick input from capture_test.py --list

Whistle a rising note and watch the bright line climb. Hum near a power
brick and watch the 60 Hz band light up. This is the visual the chat will
later hand back as an image.
"""

import argparse
import queue

import numpy as np
import sounddevice as sd
import matplotlib.pyplot as plt

SAMPLE_RATE = 44100
BLOCK = 2048          # samples per FFT frame
HISTORY = 200         # number of frames shown across the screen
MAX_FREQ = 8000       # top of the display (Hz) - most action is here

audio_q = queue.Queue()


def callback(indata, frames, time_info, status):
    audio_q.put(indata[:, 0].copy())


def main(device=None):
    freqs = np.fft.rfftfreq(BLOCK, 1 / SAMPLE_RATE)
    fbins = freqs <= MAX_FREQ
    spec = np.full((fbins.sum(), HISTORY), -80.0)  # dB, oldest->newest

    fig, ax = plt.subplots(figsize=(10, 5))
    img = ax.imshow(spec, origin="lower", aspect="auto", cmap="magma",
                    vmin=-80, vmax=0,
                    extent=[0, HISTORY, 0, MAX_FREQ / 1000])
    ax.set_xlabel("time (frames) ->")
    ax.set_ylabel("frequency (kHz)")
    ax.set_title("Live spectrogram - Ctrl-C in terminal or close window to stop")
    fig.colorbar(img, ax=ax, label="dB")

    window = np.hanning(BLOCK)

    with sd.InputStream(channels=1, samplerate=SAMPLE_RATE,
                        blocksize=BLOCK, device=device, callback=callback):
        plt.show(block=False)
        try:
            while plt.fignum_exists(fig.number):
                try:
                    block = audio_q.get(timeout=1)
                except queue.Empty:
                    continue
                mag = np.abs(np.fft.rfft(block * window))
                col = 20 * np.log10(mag[fbins] + 1e-6)
                spec = np.roll(spec, -1, axis=1)
                spec[:, -1] = col
                img.set_data(spec)
                fig.canvas.draw_idle()
                fig.canvas.flush_events()
        except KeyboardInterrupt:
            pass
    print("Stopped.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", type=int, default=None)
    main(ap.parse_args().device)
