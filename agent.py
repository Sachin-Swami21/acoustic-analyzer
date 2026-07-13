"""
Stage 4 - the Acoustic Analyzer agent.

A terminal chat where a LOCAL LLM (via Ollama) reasons over live sound by
calling the DSP tools in acoustic_tools.py. The model never touches raw
audio; it calls capture_and_analyze() and interprets the JSON facts.

  python agent.py                     # chat - ask "what's that noise?"
  python agent.py --model qwen2.5:3b  # pick the model (default)

Runs the same on the Jetson later; only the mic device changes.
"""

import argparse
import json

import ollama

import acoustic_tools as T

SYSTEM = """You are Acoustic Analyzer, an assistant that listens through a microphone and explains sound.
You cannot hear directly - you MUST call the capture_and_analyze tool to get structured acoustic facts, then interpret them in plain language.
If the user wants to SEE the sound (its spectrum / spectrogram / frequencies over time), call get_spectrum_image and tell them the saved file path.

How to read the facts:
- rms_db at or below about -55 means very quiet / silence.
- hum_60hz_score above ~0.25 means strong 60 Hz mains hum (ground loop, transformer, power supply); mention the 120/180 Hz harmonics.
- dominant_hz is the single strongest frequency; peaks_hz are the strongest tones.
- high spectral_centroid_hz (>3000) with high zero_crossing_rate suggests hiss / broadband noise; low centroid with few peaks suggests a pure tone.

Always call the tool before answering a question about the current sound. Be concise and concrete: cite the numbers (Hz, dB), give the most likely cause, and stop."""


def run(model):
    client = ollama.Client()
    messages = [{"role": "system", "content": SYSTEM}]
    print("Acoustic Analyzer agent (model: %s). Ask about a sound, or 'quit'.\n" % model)

    while True:
        try:
            user = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not user:
            continue
        if user.lower() in ("quit", "exit"):
            return

        messages.append({"role": "user", "content": user})

        # tool loop: keep going until the model answers without a tool call
        while True:
            resp = client.chat(model=model, messages=messages, tools=T.TOOLS)
            msg = resp.message
            messages.append(msg)

            if not msg.tool_calls:
                print("agent> %s\n" % (msg.content or "").strip())
                break

            for tc in msg.tool_calls:
                name = tc.function.name
                args = tc.function.arguments or {}
                shown = ", ".join("%s=%s" % (k, v) for k, v in dict(args).items())
                print("  [tool] %s(%s)" % (name, shown))
                result = T.call(name, args)
                messages.append({"role": "tool", "tool_name": name,
                                 "content": json.dumps(result)})


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="qwen2.5:3b")
    run(ap.parse_args().model)
