"""
agent_shell — a reusable terminal agent for any local-LLM + tools project.

Nothing here is domain-specific. A "vertical" supplies only config:

  AGENT_NAME         banner title            (default "Agent")
  AGENT_SUB          banner subtitle
  MODEL              ollama model to start with (default qwen2.5:3b) — switch live with 'model'
  OLLAMA_HOST        ollama endpoint         (default http://ollama.acoustic:11434)
  TOOL_SERVERS       comma-separated base URLs of OpenAPI tool services
                     (each must serve <url>/openapi.json)
  SYSTEM_PROMPT      the system prompt, OR
  SYSTEM_PROMPT_FILE path to a file containing it
  SUGGESTIONS        starter questions (one per line), OR
  SUGGESTIONS_FILE   path to a file of them — shown as a numbered pick-list

The shell fetches each tool service's OpenAPI schema, turns every operation into
an Ollama tool, runs the tool-calling REPL, and dispatches calls back to the
right endpoint. Point it at a different tool service + prompt → a different agent,
same UI. (Acoustic Analyzer is just the first vertical — see deploy/agents/.)
"""

import itertools
import json
import os
import re
import sys
import threading
import time
import urllib.parse
import urllib.request

import ollama

# ---- config (the only per-vertical inputs) -------------------------------
NAME = os.environ.get("AGENT_NAME", "Agent")
SUB = os.environ.get("AGENT_SUB", "local edge-AI")
MODEL = os.environ.get("MODEL", "qwen2.5:3b")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://ollama.acoustic:11434")
TOOL_SERVERS = [u.strip().rstrip("/") for u in os.environ.get("TOOL_SERVERS", "").split(",") if u.strip()]


def _system_prompt():
    p = os.environ.get("SYSTEM_PROMPT")
    if p:
        return p
    f = os.environ.get("SYSTEM_PROMPT_FILE")
    if f and os.path.exists(f):
        return open(f, encoding="utf-8").read().strip()
    return "You are a helpful assistant. Use the available tools to answer, and cite what they return."


def _suggestions():
    """Starter questions for the pick-list. One per line; '#' comments and blanks ignored.
    Capped at 9 so every choice is a single keystroke."""
    raw = os.environ.get("SUGGESTIONS")
    if not raw:
        f = os.environ.get("SUGGESTIONS_FILE")
        if f and os.path.exists(f):
            raw = open(f, encoding="utf-8").read()
    lines = [ln.strip() for ln in (raw or "").splitlines()]
    return [x for x in lines if x and not x.startswith("#")][:9]


# ---- ANSI palette --------------------------------------------------------
R = "\033[0m"; B = "\033[1m"; D = "\033[2m"
CY = "\033[38;5;44m"; MG = "\033[38;5;207m"; YL = "\033[38;5;221m"
GY = "\033[38;5;244m"; RD = "\033[38;5;203m"


def c(txt, col):
    return f"{col}{txt}{R}"


# ---- OpenAPI → Ollama tools (the reusable magic) -------------------------
SKIP_PATHS = {"/", "/healthz", "/health", "/openapi.json", "/docs", "/redoc"}


def _clean_prop(p):
    """Collapse OpenAPI 3.1 anyOf/null and drop noise so Ollama gets a plain schema."""
    if "anyOf" in p:
        non_null = [x for x in p["anyOf"] if isinstance(x, dict) and x.get("type") != "null"]
        out = dict(non_null[0]) if non_null else {"type": "string"}
    else:
        out = dict(p)
    out.pop("title", None)
    return out


def _resolve(schema, comps):
    if isinstance(schema, dict) and "$ref" in schema:
        return comps.get(schema["$ref"].split("/")[-1], {})
    return schema or {}


def discover_tools(base_urls):
    """Return (ollama_tool_specs, dispatch_map) built from each service's OpenAPI."""
    tools, dispatch = [], {}
    for base in base_urls:
        try:
            spec = json.load(urllib.request.urlopen(base + "/openapi.json", timeout=10))
        except Exception as e:
            print(c(f"  ! could not load tools from {base}: {e}", RD))
            continue
        comps = spec.get("components", {}).get("schemas", {})
        for path, methods in spec.get("paths", {}).items():
            if path in SKIP_PATHS:
                continue
            for method, op in methods.items():
                if method.lower() not in ("get", "post"):
                    continue
                # clean name from the path segment ("/analyze" -> "analyze"), not FastAPI's
                # noisy operationId ("analyze_analyze_post") which confuses small models.
                seg = path.strip("/").split("/")[-1] or op.get("operationId") or method
                name = re.sub(r"[^A-Za-z0-9_]", "_", seg)
                if name in dispatch:            # disambiguate if two methods share a path
                    name = f"{name}_{method}"
                params = {"type": "object", "properties": {}, "required": []}
                rb = (op.get("requestBody", {}).get("content", {})
                        .get("application/json", {}).get("schema"))
                if rb:
                    sch = _resolve(rb, comps)
                    for k, v in (sch.get("properties") or {}).items():
                        params["properties"][k] = _clean_prop(v)
                    params["required"] = sch.get("required", [])
                for pr in op.get("parameters", []):
                    if pr.get("in") == "query":
                        params["properties"][pr["name"]] = _clean_prop(pr.get("schema", {}))
                        if pr.get("required"):
                            params["required"].append(pr["name"])
                desc = (op.get("summary") or op.get("description") or name).strip()[:1024]
                tools.append({"type": "function",
                              "function": {"name": name, "description": desc, "parameters": params}})
                dispatch[name] = (base, path, method.lower())
    return tools, dispatch


def run_tool(name, args, dispatch):
    base, path, method = dispatch[name]
    url = base + path
    if method == "post":
        req = urllib.request.Request(url, data=json.dumps(args or {}).encode(),
                                     headers={"Content-Type": "application/json"})
    else:
        if args:
            url += "?" + urllib.parse.urlencode(args)
        req = urllib.request.Request(url)
    resp = urllib.request.urlopen(req, timeout=60)
    ct = resp.headers.get("Content-Type", "")
    body = resp.read()
    if "json" in ct or "text" in ct or not ct:
        return body.decode(errors="replace")
    return f"[{name} returned {len(body)} bytes of {ct}]"   # e.g. an image — describe, don't dump


# ---- UI ------------------------------------------------------------------
def banner(n_tools):
    print(f"""{CY}
   ┌────────────────────────────────────────────────────────┐
   │  {B}{NAME.upper()}{R}{CY}
   │  {GY}∿∿∿∿∿  {SUB}{CY}
   └────────────────────────────────────────────────────────┘{R}
   {GY}model{R} {MODEL}   {GY}ollama{R} {OLLAMA_HOST}
   {GY}tools{R} {n_tools} discovered from {', '.join(TOOL_SERVERS) or '(none)'}
   {D}pick a number below, ask your own · '?' list · 'model' to switch · 'quit' to exit{R}
""")


def list_models(client):
    """Names of the models Ollama actually has pulled (tolerant of ollama-python versions)."""
    def _name(m):
        if isinstance(m, dict):
            return m.get("model") or m.get("name")
        return getattr(m, "model", None) or getattr(m, "name", None)
    try:
        resp = client.list()
        items = resp.get("models", []) if isinstance(resp, dict) else getattr(resp, "models", [])
        return sorted(n for n in (_name(m) for m in items) if n)
    except Exception:
        return []


def show_models(models, cur):
    if not models:
        print(c("  ! no models found on the ollama host", RD) + "\n")
        return
    print(c("  models:", D))
    for i, m in enumerate(models, 1):
        print("   " + c(str(i), YL) + c(" · ", GY) + m + (c("  ← current", CY) if m == cur else ""))
    print(c("  switch with:  model <number|name>", D) + "\n")


def show_suggestions(sugg):
    if not sugg:
        return
    print(c("  try:", D))
    for i, s in enumerate(sugg, 1):
        print("   " + c(str(i), YL) + c(" · ", GY) + s)
    print()


class Spinner:
    def __init__(self, label):
        self.label = label; self._stop = threading.Event()
        self._t = threading.Thread(target=self._run)

    def _run(self):
        for ch in itertools.cycle("⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"):
            if self._stop.is_set():
                break
            sys.stdout.write(f"\r{D}{ch} {self.label}{R}"); sys.stdout.flush(); time.sleep(0.08)
        sys.stdout.write("\r\033[K"); sys.stdout.flush()

    def __enter__(self):
        if sys.stdout.isatty():
            self._t.start()
        return self

    def __exit__(self, *a):
        self._stop.set()
        if self._t.is_alive():
            self._t.join()


def brief(result):
    try:
        d = json.loads(result)
        if isinstance(d, dict):
            bits = [f"{k}={v}" for k, v in d.items() if isinstance(v, (str, int, float, bool))][:3]
            return " · ".join(bits) or (result[:70])
    except Exception:
        pass
    return result[:70]


_URL_KEYS = ("view_url", "spectrum_url", "url")


def collect_urls(result, allowed):
    """Remember the links a REAL tool call returned — the only ones we'll ever show the user."""
    try:
        d = json.loads(result)
        if isinstance(d, dict):
            for k in _URL_KEYS:
                v = d.get(k)
                if isinstance(v, str) and v.strip():
                    allowed.add(v.strip())
    except Exception:
        pass
    for u in re.findall(r"https?://[^\s\"')>\]]+", result or ""):
        allowed.add(u)


def _plain(text, allowed=()):
    """Render the model's reply for a terminal, and refuse to print links it made up.

    Small models fabricate URLs (a fake /spectrogram, or an internal path dressed as a signed
    URL). Only links a tool actually returned are allowed through; everything else is dropped,
    so a hallucinated link can never reach the user regardless of the model."""
    text = (text or "").strip()
    ok = lambda u: u.strip() in allowed

    # markdown image / link — keep it only if the target came from a tool
    text = re.sub(r"!\[([^\]]*)\]\(([^)\s]+)\)",
                  lambda m: m.group(2) if ok(m.group(2)) else "", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)",
                  lambda m: (m.group(2) if m.group(1) == m.group(2) else f"{m.group(1)} ({m.group(2)})")
                  if ok(m.group(2)) else m.group(1), text)
    # bare URLs no tool returned, and internal filesystem paths, must never surface
    text = re.sub(r"https?://[^\s\"')>\]]+",
                  lambda m: m.group(0) if ok(m.group(0)) else "[link removed — not from a tool]", text)
    text = re.sub(r"(?<![\w])/(?:tmp|var|home|root|app|etc)/\S+", "[internal path removed]", text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def main():
    client = ollama.Client(host=OLLAMA_HOST)
    tools, dispatch = discover_tools(TOOL_SERVERS)
    banner(len(tools))
    sugg = _suggestions()
    show_suggestions(sugg)
    current = MODEL
    models = list_models(client)
    if models and current not in models:      # e.g. the configured model was never pulled
        print(c(f"  ! {current} is not on the ollama host — 'model' to pick one of: "
                f"{', '.join(models)}", RD) + "\n")
    messages = [{"role": "system", "content": _system_prompt()}]
    allowed_urls = set()          # links real tool calls returned — the only printable ones

    while True:
        try:
            user = input(c("┌─[", GY) + c("you", CY) + c("] ", GY)).strip()
        except (EOFError, KeyboardInterrupt):
            print("\n" + c("bye ∿", GY)); return
        if not user:
            continue
        if user.lower() in ("quit", "exit", "q"):
            print(c("bye ∿", GY)); return
        if user in ("?", "menu", "help", "h"):
            show_suggestions(sugg); show_models(models, current); continue
        if user.split()[0].lstrip("/").lower() == "model":       # switch model live
            arg = user.split(maxsplit=1)[1].strip() if len(user.split(maxsplit=1)) > 1 else ""
            models = list_models(client) or models
            if not arg:
                show_models(models, current); continue
            hits = [m for m in models if arg in m]               # number, exact, or substring ("7b")
            pick = (models[int(arg) - 1] if arg.isdigit() and 1 <= int(arg) <= len(models)
                    else arg if arg in models
                    else hits[0] if len(hits) == 1 else None)
            if pick:
                current = pick
                print(c(f"  → model: {current}", CY) + c("  (conversation kept)", D) + "\n")
            else:
                print(c(f"  ! no single match for '{arg}'", RD)); show_models(models, current)
            continue
        if user.isdigit() and 1 <= int(user) <= len(sugg):   # a picked suggestion
            user = sugg[int(user) - 1]
            print(c("  → ", GY) + c(user, CY))

        messages.append({"role": "user", "content": user})
        while True:
            with Spinner("thinking…"):
                resp = client.chat(model=current, messages=messages, tools=tools or None)
            msg = resp.message
            messages.append(msg)
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    args = dict(tc.function.arguments or {})
                    shown = ", ".join(f"{k}={v}" for k, v in args.items())
                    print(c(f"  ⚡ {tc.function.name}({shown})", YL))
                    try:
                        result = run_tool(tc.function.name, args, dispatch)
                        collect_urls(result, allowed_urls)      # these links are now printable
                        print(c(f"  ↳ {brief(result)}", GY))
                    except Exception as e:
                        result = json.dumps({"error": str(e)})
                        print(c(f"  ↳ error: {e}", RD))
                    messages.append({"role": "tool", "content": result})
                continue
            print(c("└─[", GY) + c(NAME.split()[0].lower(), MG) + c("] ", GY)
                  + _plain(msg.content, allowed_urls) + "\n")
            break


if __name__ == "__main__":
    main()
