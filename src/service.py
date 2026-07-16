"""
HTTP tool service (the "Option B" external tool server).

Exposes the DSP tools over HTTP so Open WebUI (as an OpenAPI tool server), an
iPhone NFC Shortcut, or any client can call them. Same functions as agent.py —
just reachable over the network.

Run (from the repo root):
    PYTHONPATH=src ./.venv/bin/uvicorn service:app --host 0.0.0.0 --port 8000

Then:
    http://<host>:8000/docs          interactive API (Swagger)
    http://<host>:8000/openapi.json  the schema Open WebUI imports

No microphone yet? Set ACOUSTIC_DEMO=1 and calls with no wav_path fall back to a
synthetic 60 Hz-hum signal — so you can exercise the whole chat+tool loop before
the board is soldered:
    PYTHONPATH=src ACOUSTIC_DEMO=1 ./.venv/bin/uvicorn service:app --host 0.0.0.0 --port 8000
"""

import collections
import os
import threading
import time
from typing import Optional

import numpy as np
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

import acoustic_tools as T

app = FastAPI(
    title="Acoustic Analyzer Tools",
    version="1.0.0",
    description="Listen to sound and return structured acoustic facts or a spectrogram image.",
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

DEMO = os.environ.get("ACOUSTIC_DEMO") == "1"
PUBLIC_URL = os.environ.get("PUBLIC_URL", "").rstrip("/")   # e.g. http://sachin-jetson.local:30800

# The most recent explicitly-captured clip, kept so follow-up questions and the "show me the
# spectrum" request all refer to the SAME audio instead of re-recording.
_LAST_CLIP = {"samples": None, "sr": None, "seconds": None, "label": ""}


def _synthetic_wav(path="/tmp/acoustic_demo.wav"):
    """A labelled 60 Hz mains-hum stand-in when no mic is wired. Kept hum-dominant so `analyze`
    still says "hum", but enriched with a drifting tone + faint hiss so the /scope waterfall has
    visible structure and *changes* between refreshes (each call re-randomizes the drift)."""
    from scipy.io import wavfile
    sr = 44100
    t = np.linspace(0, 2, 2 * sr, endpoint=False)
    # 60 Hz mains hum + harmonics — the dominant content (keeps the "hum" label)
    x = 0.30 * np.sin(2 * np.pi * 60 * t) + 0.15 * np.sin(2 * np.pi * 120 * t) + 0.08 * np.sin(2 * np.pi * 180 * t)
    # a slow drifting tone (~400-900 Hz) so a line visibly moves across the waterfall each refresh
    f0 = 400 + 400 * np.random.rand()
    inst = f0 + 150 * np.sin(2 * np.pi * 0.5 * t)              # wobbles up/down over the 2 s
    x += 0.08 * np.sin(2 * np.pi * np.cumsum(inst) / sr)       # integrate freq -> phase
    x += 0.02 * np.random.randn(t.size)                        # faint broadband hiss for texture
    x = x / np.max(np.abs(x)) * 0.9
    wavfile.write(path, sr, (x * 32767).astype(np.int16))
    return path


def _source(wav_path):
    """Pick the audio source: explicit wav > demo fallback > live mic."""
    if wav_path:
        return wav_path
    if DEMO:
        return _synthetic_wav()
    return None  # -> record from the microphone


class AudioReq(BaseModel):
    seconds: float = 2.0
    wav_path: Optional[str] = None


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/docs")


@app.get("/healthz", summary="Health check")
def healthz():
    """Service status, whether a microphone is available, and demo-mode state."""
    devs = T.list_input_devices().get("input_devices", [])
    return {"status": "ok", "microphone_available": len(devs) > 0,
            "input_devices": devs, "demo_mode": DEMO}


@app.post("/analyze", summary="Analyze the current sound")
def analyze(req: AudioReq):
    """Record a few seconds of audio (or read a WAV) and return structured acoustic facts:
    loudness (rms_db), dominant frequency, tonal peaks, spectral centroid, a 60 Hz mains-hum
    score, per-band energy, and a heuristic label. Call this to answer what a sound is, how
    loud it is, whether there is hum, or what frequency something is."""
    facts = T.capture_and_analyze(seconds=req.seconds, wav_path=_source(req.wav_path))
    # Never hand the model an internal filesystem path: it will happily serve it back to the user
    # as if it were a shareable link. Report the source in words instead.
    if "source" in facts:
        facts["source"] = "demo signal" if DEMO else "microphone"
    return facts


@app.post("/capture", summary="Capture a set number of seconds of sound, then analyze it")
def capture(req: AudioReq):
    """Record `seconds` of sound (e.g. 10), analyze it, and REMEMBER the clip. Returns the full
    acoustic facts (loudness rms_db, dominant frequency, tonal peaks/harmonics, 60 Hz mains-hum
    score, per-band energy, spectral centroid). Use this when the user wants to listen/record for a
    set time and then discuss what was heard. Afterwards, answer follow-up questions FROM THESE
    FACTS without capturing again, and call the spectrum tool to show this same clip."""
    seconds = float(req.seconds or 10.0)
    samples, sr = _capture_samples(seconds)
    samples = np.asarray(samples, dtype=np.float64).flatten()
    facts = T.analyze(samples, sr)
    _LAST_CLIP.update(samples=samples, sr=sr, seconds=seconds, label=facts.get("label", ""))
    facts["seconds_captured"] = seconds
    facts["spectrum_url"] = (PUBLIC_URL or "") + "/scope?clip=1"   # frozen view of THIS clip
    facts["note"] = ("Captured %.0f s and remembered it. Answer follow-ups from these facts. If the "
                     "user asks to see the spectrum, give them spectrum_url." % seconds)
    return facts


@app.post("/spectrum", summary="Show the spectrogram")
def spectrum(req: AudioReq):
    """Return a link to a spectrogram view. If a clip was just captured, this shows THAT clip
    (frozen, the whole capture at once); otherwise it shows the live scrolling spectrogram. Give
    the user the returned URL to open."""
    base = PUBLIC_URL or ""
    if _LAST_CLIP["samples"] is not None:
        url = base + "/scope?clip=1"
        return {"view_url": url,
                "note": "Open %s in a browser to see the spectrogram of the captured clip." % url}
    url = base + "/scope"
    return {"view_url": url, "note": "Open %s in a browser to watch the live spectrogram." % url}


def _capture_samples(seconds):
    """Record `seconds` of real audio (mic), or synthesize a continuous demo clip of that length."""
    sr = 44100
    if DEMO:
        return _DemoStream(sr).chunk(int(seconds * sr)), sr
    return T._record(seconds), sr


def _clip_grid(samples, sr, nfreq=72, ntime=200, fmax=4000.0):
    """Full spectrogram of a finite clip -> freq×time grid of 0-255 intensities (for /scope?clip)."""
    from scipy.signal import spectrogram as _spec
    x = np.asarray(samples, dtype=np.float64).flatten()
    if x.size < 2048:
        return None
    f, _t, sxx = _spec(x, fs=sr, nperseg=1024, noverlap=512)
    sxx = sxx[f <= fmax]
    if sxx.shape[1] < 2:
        return None
    db = 10 * np.log10(sxx + 1e-12)
    ri = np.linspace(0, db.shape[0] - 1, nfreq).astype(int)
    ci = np.linspace(0, db.shape[1] - 1, ntime).astype(int)
    d = db[np.ix_(ri, ci)]
    norm = np.clip((d - WF_VMIN) / (WF_VMAX - WF_VMIN), 0, 1)
    return {"nfreq": nfreq, "ntime": ntime, "fmax_khz": fmax / 1000.0,
            "grid": (norm * 255).astype(int).tolist()}   # grid[freq][time], freq 0 = low


@app.get("/spectrum-clip", include_in_schema=False)
def spectrum_clip():
    """Frozen spectrogram of the last captured clip (for /scope?clip; hidden from the schema)."""
    if _LAST_CLIP["samples"] is None:
        return JSONResponse({"error": "no clip captured yet"}, status_code=404)
    grid = _clip_grid(_LAST_CLIP["samples"], _LAST_CLIP["sr"])
    if grid is None:
        return JSONResponse({"error": "clip too short"}, status_code=500)
    grid["label"] = _LAST_CLIP["label"]
    grid["seconds"] = _LAST_CLIP["seconds"]
    return grid


# ---- the /scope visual: a TRUE scrolling waterfall ------------------------------------------
# A background thread captures audio continuously and appends one spectrum "column" every
# ~COL_DT seconds to a ring buffer, each stamped with a monotonic sequence number. The /scope
# page polls /spectrum-stream?since=<cursor>, gets only the NEW columns, scrolls its canvas left
# and paints them on the right edge -> the display FLOWS instead of repainting whole snapshots.
WF_NFREQ = 72
WF_FMAX = 4000.0            # view spans 0..FMAX Hz (linear)
WF_COL_DT = 0.10           # seconds of audio per column -> ~10 columns/sec
WF_KEEP = 240              # ring-buffer depth (~24 s of history)
WF_VMIN, WF_VMAX = -95.0, -25.0   # FIXED dB color scale, so brightness is comparable over time

_WF = {"cols": collections.deque(maxlen=WF_KEEP), "seq": 0, "label": ""}
_WF_LOCK = threading.Lock()
_WF_STARTED = False


def _column(x, sr):
    """One windowed magnitude spectrum -> nfreq bin-averaged 0-255 intensities (low freq first)."""
    x = np.asarray(x, dtype=np.float64).flatten()
    n = x.size
    if n < 8:
        return [0] * WF_NFREQ
    sp = np.abs(np.fft.rfft(x * np.hanning(n)))
    freqs = np.fft.rfftfreq(n, 1.0 / sr)
    sp = sp[freqs <= WF_FMAX]
    if sp.size < WF_NFREQ:
        return [0] * WF_NFREQ
    db = 20.0 * np.log10(sp / n + 1e-9)          # normalize by n; fixed reference
    edges = np.linspace(0, sp.size, WF_NFREQ + 1).astype(int)
    col = np.array([db[edges[i]:edges[i + 1]].mean() for i in range(WF_NFREQ)])
    norm = np.clip((col - WF_VMIN) / (WF_VMAX - WF_VMIN), 0, 1)
    return (norm * 255).astype(int).tolist()


class _DemoStream:
    """Phase-continuous synthetic hum + slowly wandering mid tone + hiss, yielded in chunks so the
    waterfall flows smoothly across columns (unlike re-generating an independent clip each time)."""
    def __init__(self, sr):
        self.sr = sr
        self.ph = np.zeros(3)          # running phase of 60/120/180 Hz
        self.phd = 0.0                 # running phase of the drift tone
        self.fd = 550.0                # drift instantaneous frequency

    def chunk(self, n):
        sr = self.sr
        idx = np.arange(n)
        x = np.zeros(n)
        for k, (f, a) in enumerate([(60, 0.30), (120, 0.15), (180, 0.08)]):
            x += a * np.sin(self.ph[k] + 2 * np.pi * f * idx / sr)
            self.ph[k] = (self.ph[k] + 2 * np.pi * f * n / sr) % (2 * np.pi)
        self.fd = float(np.clip(self.fd + np.random.randn() * 25, 320, 1300))   # slow random walk
        x += 0.08 * np.sin(self.phd + 2 * np.pi * self.fd * idx / sr)
        self.phd = (self.phd + 2 * np.pi * self.fd * n / sr) % (2 * np.pi)
        x += 0.02 * np.random.randn(n)
        return x


def _mic_chunk(state, n, sr):
    """Read ~n samples from a persistent input stream (mic path; used once ACOUSTIC_DEMO=0)."""
    import sounddevice as sd
    if state.get("stream") is None:
        state["stream"] = sd.InputStream(samplerate=sr, channels=1, dtype="float32")
        state["stream"].start()
    data, _ = state["stream"].read(n)
    return np.asarray(data).flatten()


def _producer():
    sr = 44100
    n = int(WF_COL_DT * sr)
    gen = _DemoStream(sr)
    mic = {}
    recent = collections.deque(maxlen=int(1.5 * sr))   # rolling audio for the heuristic label
    i = 0
    while True:
        try:
            if DEMO:
                x = gen.chunk(n)
                time.sleep(WF_COL_DT)                   # pace the synthetic feed to real time
            else:
                x = _mic_chunk(mic, n, sr)              # the read itself paces the loop
        except Exception:
            time.sleep(0.2)
            continue
        col = _column(x, sr)
        recent.extend(x)
        with _WF_LOCK:
            _WF["seq"] += 1
            _WF["cols"].append((_WF["seq"], col))
            if i % 12 == 0 and len(recent) > sr // 2:
                try:
                    _WF["label"] = T.analyze(np.array(recent), sr).get("label", "")
                except Exception:
                    pass
        i += 1


def _ensure_producer():
    global _WF_STARTED
    with _WF_LOCK:
        if _WF_STARTED:
            return
        _WF_STARTED = True
    threading.Thread(target=_producer, daemon=True).start()


@app.get("/spectrum-stream", include_in_schema=False)
def spectrum_stream(since: int = 0):
    """New spectrum columns since `since` for the scrolling /scope page (hidden from the schema)."""
    _ensure_producer()
    for _ in range(20):                       # on first hit, wait briefly for the first column
        with _WF_LOCK:
            have = _WF["seq"]
        if have > 0:
            break
        time.sleep(0.05)
    with _WF_LOCK:
        seq, label = _WF["seq"], _WF["label"]
        new = [c for (s, c) in _WF["cols"] if s > since]
    return {"cursor": seq, "reset": since == 0, "nfreq": WF_NFREQ,
            "fmax_khz": WF_FMAX / 1000.0, "label": label, "cols": new}


@app.get("/scope", include_in_schema=False)
def scope():
    """Live spectrogram web page (magma canvas). The terminal agent hands out this URL."""
    return HTMLResponse(SCOPE_HTML)


SCOPE_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Acoustic Scope</title>
<style>
 body{margin:0;background:#0c0d13;color:#e9eaf2;font-family:ui-monospace,"SF Mono",Menlo,monospace}
 .wrap{max-width:920px;margin:0 auto;padding:22px}
 h1{font-size:15px;letter-spacing:.14em;font-weight:700;margin:0 0 14px}
 .live{color:#35d07f}
 canvas{width:100%;height:340px;background:#05060a;border:1px solid #252938;border-radius:12px;display:block}
 .row{display:flex;justify-content:space-between;font-size:12px;color:#969abb;margin:10px 3px;letter-spacing:.05em}
</style></head>
<body><div class="wrap">
 <h1>&#9673; ACOUSTIC SCOPE &nbsp;<span class="live">&#9679; live</span></h1>
 <canvas id="c" width="900" height="340"></canvas>
 <div class="row"><span id="axis">&larr; older &nbsp;·&nbsp; newer &rarr;</span><span id="stat">connecting&hellip;</span><span id="band">0&ndash;4 kHz</span></div>
</div>
<script>
const MAG=[[0,0,4],[28,16,68],[79,18,123],[129,37,129],[181,54,122],[229,80,100],[251,135,97],[254,194,135],[252,253,191]];
function magma(t){t=t<0?0:t>1?1:t;const x=t*(MAG.length-1),i=Math.floor(x),f=x-i;const a=MAG[i],b=MAG[Math.min(i+1,MAG.length-1)];return[a[0]+(b[0]-a[0])*f|0,a[1]+(b[1]-a[1])*f|0,a[2]+(b[2]-a[2])*f|0];}
const c=document.getElementById("c"),ctx=c.getContext("2d",{alpha:false});
const W=c.width,H=c.height,VIS=180,cw=W/VIS;   // VIS columns visible (~18 s window)
let nf=72,ch=H/nf,cursor=0;
function paintCol(xRight,col){                 // draw one column at pixel x=xRight
 for(let y=0;y<nf;y++){const m=magma(col[y]/255);
  ctx.fillStyle="rgb("+m[0]+","+m[1]+","+m[2]+")";
  ctx.fillRect(xRight,H-(y+1)*ch,Math.ceil(cw),Math.ceil(ch));}
}
function pushCols(cols){                        // scroll left by cols.length, paint on the right
 if(!cols.length)return;
 if(cols.length>=VIS){ctx.fillStyle="#05060a";ctx.fillRect(0,0,W,H);cols=cols.slice(-VIS);
  for(let i=0;i<cols.length;i++)paintCol((VIS-cols.length+i)*cw,cols[i]);return;}
 ctx.drawImage(c,-cols.length*cw,0);            // shift existing content left
 ctx.fillStyle="#05060a";ctx.fillRect(W-cols.length*cw,0,cols.length*cw,H);
 for(let i=0;i<cols.length;i++)paintCol(W-(cols.length-i)*cw,cols[i]);
}
async function tick(){
 try{
  const d=await (await fetch("spectrum-stream?since="+cursor,{cache:"no-store"})).json();
  if(d.nfreq&&d.nfreq!==nf){nf=d.nfreq;ch=H/nf;}
  if(d.reset){ctx.fillStyle="#05060a";ctx.fillRect(0,0,W,H);}
  pushCols(d.cols||[]);
  cursor=d.cursor;
  document.getElementById("stat").textContent=d.label||"";
  if(d.fmax_khz)document.getElementById("band").textContent="0\\u2013"+d.fmax_khz+" kHz";
 }catch(e){document.getElementById("stat").textContent="waiting for service\\u2026";}
 setTimeout(tick,220);
}
async function showClip(){    // frozen mode: render the whole captured clip once, no scrolling
 try{
  const d=await (await fetch("spectrum-clip",{cache:"no-store"})).json();
  if(d.grid){
   nf=d.nfreq;ch=H/nf;const nt=d.ntime,gw=W/nt;
   ctx.fillStyle="#05060a";ctx.fillRect(0,0,W,H);
   for(let x=0;x<nt;x++)for(let y=0;y<nf;y++){const m=magma(d.grid[y][x]/255);
    ctx.fillStyle="rgb("+m[0]+","+m[1]+","+m[2]+")";
    ctx.fillRect(x*gw,H-(y+1)*ch,Math.ceil(gw),Math.ceil(ch));}
   document.getElementById("stat").textContent=d.label||"";
   if(d.fmax_khz)document.getElementById("band").textContent="0\\u2013"+d.fmax_khz+" kHz";
   document.getElementById("axis").textContent="start \\u2192 end ("+(d.seconds||0)+"s clip)";
  }else{document.getElementById("stat").textContent="no clip captured yet\\u2026";}
 }catch(e){document.getElementById("stat").textContent="no clip captured yet\\u2026";}
}
if(new URLSearchParams(location.search).has("clip")){
 document.querySelector(".live").innerHTML="&#9632; captured";
 showClip();
}else{tick();}
</script></body></html>"""
