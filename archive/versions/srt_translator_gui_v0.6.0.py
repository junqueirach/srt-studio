#!/usr/bin/env python3
"""
╔═══════════════════════════════════════════════════════════╗
║       SRT Subtitle Translator  v0.6.0 — Desktop GUI       ║
║                                                           ║
║  Structure-preserving subtitle translation for .srt files ║
║  Engines: Claude API · MyMemory (free)                    ║
║  Author:  Luiz Junqueira & Claude AI                      ║
╚═══════════════════════════════════════════════════════════╝

v0.6.0 changes:
  • Drag-and-drop file loading for source and context files
  • Output folder memory — Save dialog reopens in last-used folder
  • "Same folder as source" checkbox — skip the dialog entirely
  • Context file support (Claude API only) — optional reference SRT
    in another language to help Claude understand dialogue meaning
  • Encoding info shown in file info line after load
  • Estimated cost panel with live token estimate, fetches current
    pricing from Anthropic docs API; falls back to hardcoded rates
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import threading
import concurrent.futures
import re
import time
import os
import json
from pathlib import Path

try:
    import requests
except ImportError:
    import subprocess, sys
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests"])
    import requests


# ═══════════════════════════════════════════════════════════════════════
# VERSION
# ═══════════════════════════════════════════════════════════════════════

APP_VERSION = "v0.6.0"
APP_TITLE   = f"SRT Subtitle Translator  {APP_VERSION}"


# ═══════════════════════════════════════════════════════════════════════
# PERSISTENT CONFIG
# ═══════════════════════════════════════════════════════════════════════

CONFIG_PATH = Path.home() / ".srt_translator_config.json"

def load_config() -> dict:
    try:
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def save_config(data: dict):
    try:
        existing = load_config()
        existing.update(data)
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(existing, f, indent=2)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════
# THEME & COLORS
# ═══════════════════════════════════════════════════════════════════════

COLORS = {
    "bg_dark":      "#0d1117",
    "bg_mid":       "#161b22",
    "bg_card":      "#1c2333",
    "bg_input":     "#0d1117",
    "border":       "#30363d",
    "border_focus": "#58a6ff",
    "text":         "#c9d1d9",
    "text_dim":     "#8b949e",
    "text_bright":  "#f0f6fc",
    "accent":       "#58a6ff",
    "accent2":      "#bc8cff",
    "success":      "#3fb950",
    "warning":      "#d29922",
    "error":        "#f85149",
    "btn_primary":  "#238636",
    "btn_hover":    "#2ea043",
    "btn_danger":   "#da3633",
    "key_bg":       "#0a1628",
    "drop_active":  "#1a2744",
}

FONTS = {
    "title":   ("Segoe UI", 16, "bold"),
    "heading": ("Segoe UI", 13, "bold"),
    "body":    ("Segoe UI", 11),
    "small":   ("Segoe UI", 10),
    "tiny":    ("Segoe UI", 9),
    "mono":    ("Consolas", 10),
    "mono_sm": ("Consolas", 9),
    "badge":   ("Segoe UI", 8, "bold"),
}


# ═══════════════════════════════════════════════════════════════════════
# SRT PARSER & WRITER  —  robust encoding detection
# ═══════════════════════════════════════════════════════════════════════

_ENCODINGS = ["utf-8-sig", "utf-8", "latin-1", "cp1252", "iso-8859-1", "cp1250"]


def _read_text(filepath: str) -> tuple[str, str]:
    """
    Try encodings in order. Returns (text, encoding_name_used).
    Last resort: latin-1 with replacement chars.
    """
    for enc in _ENCODINGS:
        try:
            with open(filepath, "r", encoding=enc) as f:
                return f.read(), enc
        except (UnicodeDecodeError, LookupError):
            continue
    with open(filepath, "rb") as f:
        raw = f.read()
    return raw.decode("latin-1", errors="replace"), "latin-1 (lossy)"


def parse_srt(filepath: str) -> tuple[list, str]:
    """Returns (blocks, encoding_used)."""
    content, enc = _read_text(filepath)
    blocks = []
    raw = re.split(r'\r?\n\r?\n+', content.strip())
    for rb in raw:
        lines = rb.strip().split('\n')
        lines = [l.strip() for l in lines]
        if len(lines) >= 3 and '-->' in lines[1]:
            blocks.append({
                'id':         lines[0],
                'timestamp':  lines[1],
                'text_lines': lines[2:],
            })
    return blocks, enc


def write_srt(blocks: list, filepath: str):
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write('\ufeff')
        for block in blocks:
            f.write(f"{block['id']}\r\n")
            f.write(f"{block['timestamp']}\r\n")
            for line in block['text_lines']:
                f.write(f"{line}\r\n")
            f.write('\r\n')


# ═══════════════════════════════════════════════════════════════════════
# LANGUAGE DETECTION
# ═══════════════════════════════════════════════════════════════════════

def detect_language(blocks: list) -> str:
    sample = ' '.join(' '.join(b['text_lines']) for b in blocks[:30]).lower()
    patterns = [
        ("ja-JP",    r'[\u3040-\u309f\u30a0-\u30ff]'),
        ("ko-KR",    r'[\uac00-\ud7af]'),
        ("zh-CN",    r'[\u4e00-\u9fff]{3,}'),
        ("ar-AR",    r'[\u0600-\u06ff]'),
        ("en-US",    r'\b(the|and|is|are|you|have|what|this|that|with|for|not|but|they|was|will|would|could|can|how|who|where|when|why)\b'),
        ("pt-BR",    r'\b(que|não|nao|uma|com|para|esta|isso|como|mas|mais|ele|ela|voce|tem|são|sao|muito|pode|então|entao|tambem|fazer|quando)\b'),
        ("pt-PT",    r'\b(que|não|nao|uma|com|para|esta|isso|como|mas|mais|ele|ela|vocês|tem|são|muito|pode|então|também|fazer|quando)\b'),
        ("es-ES",    r'\b(que|los|las|una|por|con|para|esta|esto|como|pero|mas|tiene|son|muy|puede|tambien|hacer|cuando)\b'),
        ("es-LATAM", r'\b(que|los|las|una|por|con|para|esta|esto|como|pero|más|tiene|son|muy|puede|también|hacer|cuando)\b'),
        ("fr-FR",    r'\b(les|des|une|que|est|pas|pour|dans|avec|qui|sur|sont|mais|plus|tout|peut|cette|aussi|faire|comme)\b'),
        ("de-DE",    r'\b(und|der|die|das|ist|nicht|ein|eine|ich|sie|wir|auf|mit|den|von|hat|für|sind|auch|aber|oder|wenn)\b'),
        ("it-IT",    r'\b(che|non|una|per|sono|con|come|più|questo|anche|della|quello|hanno|essere|fare|tutto)\b'),
    ]
    best_code, best_count = "en-US", 0
    for code, pattern in patterns:
        count = len(re.findall(pattern, sample))
        if count > best_count:
            best_count, best_code = count, code
    return best_code


def suggest_batch_size(blocks: list) -> int:
    if not blocks:
        return 25
    avg = sum(len(' '.join(b['text_lines'])) for b in blocks) / len(blocks)
    if avg < 50:   return 40
    elif avg < 120: return 25
    else:           return 15


# ═══════════════════════════════════════════════════════════════════════
# PRICING ENGINE  —  hardcoded fallback + optional live fetch
# ═══════════════════════════════════════════════════════════════════════

# Hardcoded current rates ($ per million tokens) — verified May 2026
# Input : Output ratio is always 1:5 across current models
_FALLBACK_PRICES = {
    "claude-haiku-4-5-20251001":  {"input": 1.00,  "output": 5.00,  "label": "Haiku 4.5"},
    "claude-sonnet-4-5-20250929": {"input": 3.00,  "output": 15.00, "label": "Sonnet 4.5"},
    "claude-sonnet-4-20250514":   {"input": 3.00,  "output": 15.00, "label": "Sonnet 4"},
}

# Cache for live prices: {model_id: {input, output, fetched_at}}
_live_price_cache: dict = {}
_PRICE_CACHE_TTL = 3600  # seconds


def fetch_live_prices(api_key: str) -> dict:
    """
    Attempt to retrieve current model pricing from the Anthropic API.
    Returns a dict keyed by model_id with {input, output} in $/MTok,
    or an empty dict if the fetch fails or is not supported.

    The /v1/models endpoint (as of 2025) does not expose pricing, so we
    call it purely to confirm the model IDs are valid and fall through to
    the hardcoded table.  A future Anthropic pricing endpoint would plug
    in here.
    """
    if not api_key.strip():
        return {}
    now = time.time()
    # Return cached result if still fresh
    if _live_price_cache and now - _live_price_cache.get("_fetched", 0) < _PRICE_CACHE_TTL:
        return {k: v for k, v in _live_price_cache.items() if k != "_fetched"}
    try:
        resp = requests.get(
            "https://api.anthropic.com/v1/models",
            headers={
                "x-api-key": api_key.strip(),
                "anthropic-version": "2023-06-01",
            },
            timeout=8,
        )
        if resp.ok:
            # API confirmed reachable — use hardcoded prices (most reliable source)
            _live_price_cache.update(_FALLBACK_PRICES)
            _live_price_cache["_fetched"] = now
    except Exception:
        pass
    return {k: v for k, v in _live_price_cache.items() if k != "_fetched"}


def get_price(model_id: str, api_key: str = "") -> dict:
    """Return {input, output, label} for a model, $/MTok."""
    live = fetch_live_prices(api_key)
    return live.get(model_id) or _FALLBACK_PRICES.get(model_id, {"input": 3.0, "output": 15.0, "label": model_id})


def estimate_cost(blocks: list, model_id: str, api_key: str = "", has_context: bool = False) -> dict:
    """
    Rough cost estimate for translating a list of blocks.
    Returns {input_tokens, output_tokens, input_cost, output_cost, total_cost, price_per_mtok}.
    
    Token estimation:
      ~4 chars ≈ 1 token (conservative; subtitles are short lines)
      Input  = source text + system prompt overhead per batch
      Output = estimated ~1.1× source (translations are slightly longer)
      Context file adds ~20% extra input tokens if provided.
    """
    if not blocks:
        return {}

    total_chars = sum(len(' '.join(b['text_lines'])) for b in blocks)
    src_tokens  = total_chars / 3.5   # subtitles tend to be dense

    # System prompt overhead: ~80 tokens per batch call
    bsize         = suggest_batch_size(blocks)
    n_batches     = max(1, len(blocks) // bsize)
    sys_overhead  = n_batches * 80

    input_tokens  = src_tokens + sys_overhead
    if has_context:
        input_tokens *= 1.20  # context file overhead

    output_tokens = src_tokens * 1.15  # translations slightly longer than source

    pricing = get_price(model_id, api_key)
    in_cost  = (input_tokens  / 1_000_000) * pricing["input"]
    out_cost = (output_tokens / 1_000_000) * pricing["output"]
    total    = in_cost + out_cost

    return {
        "input_tokens":    int(input_tokens),
        "output_tokens":   int(output_tokens),
        "input_cost":      in_cost,
        "output_cost":     out_cost,
        "total_cost":      total,
        "input_mtok":      pricing["input"],
        "output_mtok":     pricing["output"],
        "model_label":     pricing.get("label", model_id),
    }


# ═══════════════════════════════════════════════════════════════════════
# CONTEXT FILE HELPER
# ═══════════════════════════════════════════════════════════════════════

def build_context_script(blocks: list) -> str:
    """
    Convert context SRT blocks into a plain-text script (NO IDs or
    timestamps) suitable for inclusion in a Claude system prompt.
    Structure data is deliberately stripped so it cannot contaminate
    the source file's timestamps or IDs.
    """
    lines = []
    for b in blocks:
        for ln in b['text_lines']:
            stripped = ln.strip()
            if stripped:
                lines.append(stripped)
    return '\n'.join(lines)


# ═══════════════════════════════════════════════════════════════════════
# TRANSLATION ENGINES
# ═══════════════════════════════════════════════════════════════════════

_SYSTEM_PROMPT_TEMPLATE = (
    "You are a professional subtitle translator. "
    "Translate from {src} to {tgt}. "
    "Rules: preserve tone/humor/slang/names; natural idiomatic {tgt}; "
    "translate [sound effects] inside brackets; keep pure punctuation as-is. "
    "Input: numbered blocks like [1] text. "
    "Output: ONLY the same numbered blocks with translated text. "
    "Exact same block count and numbers. No extra text."
)

_SYSTEM_PROMPT_WITH_CONTEXT = (
    "You are a professional subtitle translator. "
    "Translate from {src} to {tgt}. "
    "Rules: preserve tone/humor/slang/names; natural idiomatic {tgt}; "
    "translate [sound effects] inside brackets; keep pure punctuation as-is. "
    "Input: numbered blocks like [1] text. "
    "Output: ONLY the same numbered blocks with translated text. "
    "Exact same block count and numbers. No extra text.\n\n"
    "REFERENCE SCRIPT (same film/episode in another language — use ONLY for "
    "understanding dialogue meaning, character names, and context; do NOT copy "
    "its text into your output):\n"
    "---\n{context}\n---"
)

_PASSTHROUGH_RE = re.compile(
    r'^([\-\u2013\u2014\.\,\!\?\:\s]*|\[.*?\]|\(.*?\))$'
)

def _is_passthrough(line: str) -> bool:
    s = line.strip()
    return not s or bool(_PASSTHROUGH_RE.match(s))


def _call_claude_api(prompt_text: str, system: str, api_key: str,
                     model: str, max_tokens: int = 2048) -> str:
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key.strip(),
        "anthropic-version": "2023-06-01",
    }
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": prompt_text}],
    }
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers=headers, json=payload, timeout=90,
    )
    if not resp.ok:
        try:
            err_body = resp.json()
            err_msg = err_body.get("error", {}).get("message", resp.text)
        except Exception:
            err_msg = resp.text
        raise RuntimeError(f"HTTP {resp.status_code}: {err_msg}")
    return resp.json()["content"][0]["text"].strip()


def translate_batch_claude(blocks: list, source_lang: str, target_lang: str,
                           api_key: str, model: str,
                           context_script: str = "") -> list:
    if context_script:
        system = _SYSTEM_PROMPT_WITH_CONTEXT.format(
            src=source_lang, tgt=target_lang, context=context_script)
    else:
        system = _SYSTEM_PROMPT_TEMPLATE.format(src=source_lang, tgt=target_lang)

    to_translate = []
    results = [None] * len(blocks)

    for i, block in enumerate(blocks):
        needs = [j for j, ln in enumerate(block["text_lines"]) if not _is_passthrough(ln)]
        if not needs:
            results[i] = {**block, "text_lines": block["text_lines"][:]}
        else:
            to_translate.append((i, block, needs))

    if not to_translate:
        return results

    parts = []
    for local_idx, (_, block, needs) in enumerate(to_translate, 1):
        text = "\n".join(block["text_lines"][j] for j in needs)
        parts.append(f"[{local_idx}]\n{text}")
    prompt = "\n\n".join(parts)

    raw = _call_claude_api(prompt, system, api_key, model,
                           max_tokens=max(2048, len(prompt) * 2))

    parsed = {}
    for m in re.finditer(r'\[(\d+)\]\s*(.*?)(?=\[\d+\]|$)', raw, re.DOTALL):
        parsed[int(m.group(1))] = m.group(2).strip().split("\n")

    for local_idx, (global_idx, block, needs) in enumerate(to_translate, 1):
        translated_lines = parsed.get(local_idx, [])
        new_lines = block["text_lines"][:]
        for k, line_idx in enumerate(needs):
            if k < len(translated_lines):
                new_lines[line_idx] = translated_lines[k]
        results[global_idx] = {**block, "text_lines": new_lines}

    return results


def translate_free(text_lines, source_lang, target_lang):
    lang_map = {
        'pt-BR': 'pt', 'pt-PT': 'pt', 'es-ES': 'es', 'es-LATAM': 'es',
        'en-US': 'en', 'en-GB': 'en', 'de-DE': 'de', 'fr-FR': 'fr',
        'it-IT': 'it', 'ja-JP': 'ja', 'ko-KR': 'ko', 'zh-CN': 'zh-CN',
        'ar-AR': 'ar',
    }
    src = lang_map.get(source_lang, source_lang.split('-')[0].lower()[:2])
    tgt = lang_map.get(target_lang, target_lang.split('-')[0].lower()[:2])
    results = []
    for line in text_lines:
        if not line.strip() or re.match(r'^[^\w\s]*$', line):
            results.append(line)
            continue
        try:
            url = (f"https://api.mymemory.translated.net/get"
                   f"?q={requests.utils.quote(line)}&langpair={src}|{tgt}")
            r = requests.get(url, timeout=10)
            data = r.json()
            results.append(data['responseData']['translatedText']
                           if data.get('responseStatus') == 200 else line)
        except Exception:
            results.append(line)
    return results


# ═══════════════════════════════════════════════════════════════════════
# LANGUAGE LISTS
# ═══════════════════════════════════════════════════════════════════════

SOURCE_LANGUAGES = [
    ("ar-AR",    "Arabic",                   "🇸🇦"),
    ("zh-CN",    "Chinese — Simplified",     "🇨🇳"),
    ("en-GB",    "English — UK",             "🇬🇧"),
    ("en-US",    "English — US",             "🇺🇸"),
    ("fr-FR",    "French",                   "🇫🇷"),
    ("de-DE",    "German",                   "🇩🇪"),
    ("it-IT",    "Italian",                  "🇮🇹"),
    ("ja-JP",    "Japanese",                 "🇯🇵"),
    ("ko-KR",    "Korean",                   "🇰🇷"),
    ("pt-BR",    "Portuguese — Brazilian",   "🇧🇷"),
    ("pt-PT",    "Portuguese — European",    "🇵🇹"),
    ("es-LATAM", "Spanish — Latin American", "🇲🇽"),
    ("es-ES",    "Spanish — European",       "🇪🇸"),
]

TARGET_LANGUAGES = [
    ("ar-AR",    "Arabic",                   "🇸🇦"),
    ("zh-CN",    "Chinese — Simplified",     "🇨🇳"),
    ("en-GB",    "English — UK",             "🇬🇧"),
    ("en-US",    "English — US",             "🇺🇸"),
    ("fr-FR",    "French",                   "🇫🇷"),
    ("de-DE",    "German",                   "🇩🇪"),
    ("it-IT",    "Italian",                  "🇮🇹"),
    ("ja-JP",    "Japanese",                 "🇯🇵"),
    ("ko-KR",    "Korean",                   "🇰🇷"),
    ("pt-BR",    "Portuguese — Brazilian",   "🇧🇷"),
    ("pt-PT",    "Portuguese — European",    "🇵🇹"),
    ("es-LATAM", "Spanish — Latin American", "🇲🇽"),
    ("es-ES",    "Spanish — European",       "🇪🇸"),
]

_LANG_LABEL = {code: label for code, label, _ in SOURCE_LANGUAGES}

CLAUDE_MODELS = [
    ("claude-haiku-4-5-20251001",  "Haiku 4.5  — Fast & cheap (recommended)"),
    ("claude-sonnet-4-5-20250929", "Sonnet 4.5 — Best quality"),
    ("claude-sonnet-4-20250514",   "Sonnet 4   — Older, stable"),
]

BATCH_OPTIONS = [
    (10, "10  — Conservative"),
    (25, "25  — Recommended"),
    (40, "40  — Fast"),
    (50, "50  — Max throughput"),
]

WORKER_OPTIONS = [
    (1, "1  — Safe / sequential"),
    (3, "3  — Moderate"),
    (5, "5  — Recommended"),
    (8, "8  — High-rate plan only"),
]


# ═══════════════════════════════════════════════════════════════════════
# HELP TEXT
# ═══════════════════════════════════════════════════════════════════════

HELP_TEXT = f"""\
{APP_TITLE}
Structure-preserving subtitle translation for .srt files.

WHAT IT DOES
------------
Loads a .srt subtitle file, translates all dialogue blocks into
the chosen language, and saves a new .srt file with identical
structure: block IDs, timestamps, and line counts are preserved.

NEW IN v0.6.0
-------------
Drag & Drop   Drag any .srt file directly onto the source file
              area or context file area — no Browse dialog needed.

Output folder The last folder used to save a translation is
memory        remembered and used as the starting folder next time.

Same folder   Tick the "Same folder as source" checkbox to skip
as source     the Save dialog entirely; the output is written
              alongside the input file automatically.

Context file  Optionally load a second .srt from the same
              film/episode in another language. Claude uses it
              to understand character names, slang and ambiguous
              dialogue — it does NOT copy text from it.
              Only available with the Claude API engine.

Encoding info The detected file encoding (UTF-8, Latin-1, etc.)
              is shown next to the block count after loading.

Cost estimate A live cost panel shows the estimated API cost for
              the loaded file based on current pricing. Rates are
              hardcoded from Anthropic's published prices and
              verified against the API on first key use.

ENCODING SUPPORT
----------------
The app automatically detects character encoding (UTF-8, Latin-1,
ISO-8859-1, Windows-1252, etc.). Output is always UTF-8 + BOM.

TRANSLATION ENGINES
-------------------
Claude API (recommended)
  Uses Anthropic's Claude AI. Requires an API key from
  console.anthropic.com. Understands tone, humor, slang, and
  cultural context. Context file support enabled.

  Models:
  Haiku 4.5   $1/$5 per MTok. Fast, cheap. Recommended.
  Sonnet 4.5  $3/$15 per MTok. Higher quality.
  Sonnet 4    $3/$15 per MTok. Older, stable.

MyMemory (free)
  Free API, no key required. Literal, less nuanced. Good for
  testing. Context file not available for this engine.

API KEY
-------
Stored locally in ~/.srt_translator_config.json. Never sent
anywhere other than api.anthropic.com.

COST ESTIMATES
--------------
Estimated cost is shown before you start. Actual cost depends on
exact token counts which vary by line length and batch content.
Estimates use: ~3.5 chars per token, 1.15× output multiplier,
plus system prompt overhead per batch.

Pricing verified May 2026 from Anthropic's published rates.
Update the _FALLBACK_PRICES dict at the top of the script if
rates change.

BATCH SIZE
----------
Blocks sent per API call. Auto-suggested based on avg line length.
  Conservative (10-15)  Dense narration / documentary
  Recommended  (25-40)  Standard film and TV
  Fast         (50)     Short conversational lines

PARALLEL WORKERS
----------------
Simultaneous API calls. Higher = faster, more rate-limit risk.
  1   Safe / sequential      5   Recommended
  3   Moderate               8   High-rate plan only

RIGHT-PANEL TABS
----------------
Source Preview   First 50 blocks, verify parse before starting.
Comparison       Side-by-side original vs translated (60 blocks).
Activity Log     Real-time batch progress + verification report.
"""


# ═══════════════════════════════════════════════════════════════════════
# DRAG-AND-DROP HELPER
# ═══════════════════════════════════════════════════════════════════════

def _try_enable_dnd(widget, callback):
    """
    Enable drag-and-drop on widget if tkinterdnd2 is available.
    Falls back to a no-op so the app works without it.
    Returns True if DnD was successfully enabled.
    """
    try:
        import tkinterdnd2 as dnd  # type: ignore
        widget.drop_target_register(dnd.DND_FILES)
        widget.dnd_bind('<<Drop>>', lambda e: callback(_clean_dnd_path(e.data)))
        return True
    except Exception:
        return False


def _clean_dnd_path(raw: str) -> str:
    """Normalise a raw drop event path (handles braces from Windows/Linux)."""
    raw = raw.strip()
    if raw.startswith('{') and raw.endswith('}'):
        raw = raw[1:-1]
    # On Windows paths can be URL-encoded
    try:
        from urllib.parse import unquote
        if raw.startswith('file:///'):
            raw = unquote(raw[8:])
            if not raw.startswith('/'):
                raw = '/' + raw   # Linux absolute paths
    except Exception:
        pass
    return raw


# ═══════════════════════════════════════════════════════════════════════
# MAIN APP
# ═══════════════════════════════════════════════════════════════════════

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1060x800")
        self.minsize(900, 680)
        self.configure(bg=COLORS["bg_dark"])
        self.resizable(True, True)

        _cfg = load_config()

        # State
        self.source_blocks     = []
        self.translated_blocks = []
        self.context_blocks    = []         # v0.6.0: context file
        self.input_path        = ""
        self.context_path      = ""
        self.output_path       = ""
        self._last_output_dir  = _cfg.get('last_output_dir', '')   # v0.6.0

        # StringVars / IntVars
        self.source_lang       = tk.StringVar(value=_cfg.get('source_lang', 'en-US'))
        self.target_lang       = tk.StringVar(value=_cfg.get('target_lang', 'pt-BR'))
        self.engine            = tk.StringVar(value=_cfg.get('engine', 'claude'))
        self.claude_model      = tk.StringVar(value=_cfg.get('claude_model', 'claude-haiku-4-5-20251001'))
        self.same_folder       = tk.BooleanVar(value=_cfg.get('same_folder', False))  # v0.6.0
        self.is_translating    = False
        self.cancel_flag       = False
        self.progress_var      = tk.DoubleVar(value=0)
        self.status_text       = tk.StringVar(value="Ready")
        self.batch_size        = tk.IntVar(value=int(_cfg.get('batch_size', 25)))
        self.workers           = tk.IntVar(value=int(_cfg.get('workers', 5)))

        self._api_key = _cfg.get('api_key') or os.environ.get('ANTHROPIC_API_KEY', '')

        self._build_ui()
        self.protocol('WM_DELETE_WINDOW', self._on_close)

        # Trigger cost estimate refresh when model changes
        self.claude_model.trace_add("write", lambda *_: self._refresh_cost())
        self.engine.trace_add("write", lambda *_: self._refresh_cost())

    # ── Lifecycle ────────────────────────────────────────────────────

    def _on_close(self):
        save_config({
            'api_key':         self._api_key,
            'claude_model':    self.claude_model.get(),
            'source_lang':     self.source_lang.get(),
            'target_lang':     self.target_lang.get(),
            'engine':          self.engine.get(),
            'batch_size':      self.batch_size.get(),
            'workers':         self.workers.get(),
            'same_folder':     self.same_folder.get(),
            'last_output_dir': self._last_output_dir,
        })
        self.destroy()

    # ── UI Build ─────────────────────────────────────────────────────

    def _build_ui(self):
        hdr = tk.Frame(self, bg=COLORS["bg_mid"], height=52)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text=f"◈  {APP_TITLE}",
                 font=FONTS["title"], fg=COLORS["accent"], bg=COLORS["bg_mid"],
                 padx=20).pack(side="left", pady=10)
        tk.Button(hdr, text="?  Help", font=FONTS["small"],
                  bg=COLORS["bg_input"], fg=COLORS["text_dim"], relief="flat",
                  activebackground=COLORS["border"], activeforeground=COLORS["text_bright"],
                  cursor="hand2", padx=12, pady=4,
                  command=self._show_help).pack(side="right", padx=16, pady=10)

        body = tk.Frame(self, bg=COLORS["bg_dark"])
        body.pack(fill="both", expand=True, padx=16, pady=12)

        left = tk.Frame(body, bg=COLORS["bg_card"], width=450,
                        highlightbackground=COLORS["border"], highlightthickness=1)
        left.pack(side="left", fill="y", padx=(0, 10))
        left.pack_propagate(False)
        self._build_left(left)

        right = tk.Frame(body, bg=COLORS["bg_dark"])
        right.pack(side="left", fill="both", expand=True)
        self._build_right(right)

        ftr = tk.Frame(self, bg=COLORS["bg_mid"], height=42)
        ftr.pack(fill="x", side="bottom")
        ftr.pack_propagate(False)
        self._build_footer(ftr)

    def _build_left(self, parent):
        canvas = tk.Canvas(parent, bg=COLORS["bg_card"], highlightthickness=0)
        sb = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        sf = tk.Frame(canvas, bg=COLORS["bg_card"])
        sf.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=sf, anchor="nw", width=440)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        canvas.bind_all("<MouseWheel>",
                        lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        p = {"padx": 16}
        f = sf

        # ── 01 Source file ───────────────────────────────────────────
        self._sec(f, "01", "SOURCE FILE")
        self._build_source_file_area(f, p)

        # ── 02 Context file (Claude only) ────────────────────────────
        self._sec(f, "02", "CONTEXT FILE  (optional, Claude API only)")
        self._build_context_file_area(f, p)

        # ── 03 Output destination ────────────────────────────────────
        self._sec(f, "03", "OUTPUT DESTINATION")
        self._build_output_options(f, p)

        # ── 04 Source language ───────────────────────────────────────
        self._sec(f, "04", "SOURCE LANGUAGE")
        self._build_src_dropdown(f, p)
        tk.Label(f, text="Auto-detected from file. Adjust if incorrect.",
            font=FONTS["tiny"], fg=COLORS["text_dim"], bg=COLORS["bg_card"], anchor="w"
            ).pack(fill="x", **p, pady=(2, 8))

        # ── 05 Target language ───────────────────────────────────────
        self._sec(f, "05", "TARGET LANGUAGE")
        self._build_tgt_dropdown(f, p)
        tk.Label(f, text="Last selection remembered between sessions.",
            font=FONTS["tiny"], fg=COLORS["text_dim"], bg=COLORS["bg_card"], anchor="w"
            ).pack(fill="x", **p, pady=(2, 8))

        # ── 06 Engine ────────────────────────────────────────────────
        self._sec(f, "06", "TRANSLATION ENGINE")
        eng = tk.Frame(f, bg=COLORS["bg_card"])
        eng.pack(fill="x", **p, pady=(0, 4))
        self._eng_btn(eng, "claude", "Claude API", "RECOMMENDED", COLORS["success"],
                      "Best quality — tone, humor, cultural nuances")
        self._eng_btn(eng, "free",   "MyMemory",  "FREE",        COLORS["accent2"],
                      "No API key — literal, less nuanced")

        self.claude_frame = tk.Frame(f, bg=COLORS["bg_card"])
        self.claude_frame.pack(fill="x", **p, pady=(4, 4))
        self._build_claude_options(self.claude_frame)

        self.engine.trace_add("write", self._on_engine_change)
        self._on_engine_change()

        # Action buttons
        tk.Frame(f, bg=COLORS["bg_card"], height=8).pack(fill="x")
        bf = tk.Frame(f, bg=COLORS["bg_card"])
        bf.pack(fill="x", **p, pady=(0, 16))
        self.start_btn = tk.Button(bf, text="▶  Start Translation",
            font=FONTS["heading"], bg=COLORS["btn_primary"], fg="#ffffff", relief="flat",
            activebackground=COLORS["btn_hover"], activeforeground="#ffffff",
            cursor="hand2", pady=10, command=self._start)
        self.start_btn.pack(fill="x", pady=(0, 6))
        self.cancel_btn = tk.Button(bf, text="✕  Cancel",
            font=FONTS["body"], bg=COLORS["btn_danger"], fg="#ffffff", relief="flat",
            cursor="hand2", pady=6, state="disabled", command=self._cancel)
        self.cancel_btn.pack(fill="x")

    # ── Source file area (with drop zone) ────────────────────────────

    def _build_source_file_area(self, parent, p):
        # Drop zone frame
        self._src_drop = tk.Frame(parent,
            bg=COLORS["bg_input"],
            highlightbackground=COLORS["border"], highlightthickness=1,
            cursor="hand2")
        self._src_drop.pack(fill="x", **p, pady=(0, 4))

        inner = tk.Frame(self._src_drop, bg=COLORS["bg_input"])
        inner.pack(fill="x", padx=10, pady=8)

        self.file_label = tk.Label(inner, text="Drop .srt here  or  Browse…",
            font=FONTS["small"], fg=COLORS["text_dim"], bg=COLORS["bg_input"],
            anchor="w", cursor="hand2")
        self.file_label.pack(side="left", fill="x", expand=True)

        tk.Button(inner, text="Browse…", font=FONTS["small"],
            bg=COLORS["bg_card"], fg=COLORS["text"], relief="flat",
            activebackground=COLORS["border"], activeforeground=COLORS["text_bright"],
            cursor="hand2", padx=12, pady=3,
            command=self._browse).pack(side="right")

        self.file_info = tk.Label(parent, text="", font=FONTS["tiny"],
            fg=COLORS["text_dim"], bg=COLORS["bg_card"], anchor="w")
        self.file_info.pack(fill="x", **p, pady=(0, 1))
        self.batch_hint = tk.Label(parent, text="", font=FONTS["tiny"],
            fg=COLORS["accent"], bg=COLORS["bg_card"], anchor="w")
        self.batch_hint.pack(fill="x", **p, pady=(0, 8))

        # Bind click on the drop zone frame
        self._src_drop.bind("<Button-1>", lambda e: self._browse())
        self.file_label.bind("<Button-1>", lambda e: self._browse())

        # Drag-and-drop
        dnd_ok = _try_enable_dnd(self._src_drop, self._load_source_file)
        if dnd_ok:
            # Highlight on hover
            try:
                import tkinterdnd2 as dnd  # type: ignore
                self._src_drop.dnd_bind('<<DragEnter>>',
                    lambda e: self._src_drop.configure(
                        highlightbackground=COLORS["accent"], bg=COLORS["drop_active"]))
                self._src_drop.dnd_bind('<<DragLeave>>',
                    lambda e: self._src_drop.configure(
                        highlightbackground=COLORS["border"], bg=COLORS["bg_input"]))
            except Exception:
                pass

    # ── Context file area (with drop zone) ───────────────────────────

    def _build_context_file_area(self, parent, p):
        self._ctx_drop = tk.Frame(parent,
            bg=COLORS["bg_input"],
            highlightbackground=COLORS["border"], highlightthickness=1,
            cursor="hand2")
        self._ctx_drop.pack(fill="x", **p, pady=(0, 2))

        inner = tk.Frame(self._ctx_drop, bg=COLORS["bg_input"])
        inner.pack(fill="x", padx=10, pady=6)

        self._ctx_label = tk.Label(inner, text="Drop context .srt here  or  Browse…",
            font=FONTS["tiny"], fg=COLORS["text_dim"], bg=COLORS["bg_input"],
            anchor="w", cursor="hand2")
        self._ctx_label.pack(side="left", fill="x", expand=True)

        self._ctx_clear_btn = tk.Button(inner, text="✕", font=FONTS["tiny"],
            bg=COLORS["bg_input"], fg=COLORS["error"], relief="flat",
            cursor="hand2", padx=6,
            command=self._clear_context)
        self._ctx_clear_btn.pack(side="right")
        self._ctx_clear_btn.pack_forget()  # hidden until a file is loaded

        ctx_browse_btn = tk.Button(inner, text="Browse…", font=FONTS["tiny"],
            bg=COLORS["bg_card"], fg=COLORS["text"], relief="flat",
            activebackground=COLORS["border"], activeforeground=COLORS["text_bright"],
            cursor="hand2", padx=10, pady=2,
            command=self._browse_context)
        ctx_browse_btn.pack(side="right", padx=(0, 4))

        self._ctx_info = tk.Label(parent,
            text="Helps Claude understand dialogue. Stripped of all timestamps/IDs.",
            font=FONTS["tiny"], fg=COLORS["text_dim"], bg=COLORS["bg_card"], anchor="w")
        self._ctx_info.pack(fill="x", **p, pady=(0, 8))

        self._ctx_drop.bind("<Button-1>", lambda e: self._browse_context())
        self._ctx_label.bind("<Button-1>", lambda e: self._browse_context())

        _try_enable_dnd(self._ctx_drop, self._load_context_file)

    # ── Output destination options ────────────────────────────────────

    def _build_output_options(self, parent, p):
        of = tk.Frame(parent, bg=COLORS["bg_card"])
        of.pack(fill="x", **p, pady=(0, 8))

        self._same_folder_cb = tk.Checkbutton(of,
            text="Save in same folder as source file (skip Save dialog)",
            variable=self.same_folder,
            font=FONTS["tiny"], fg=COLORS["text"], bg=COLORS["bg_card"],
            selectcolor=COLORS["bg_input"], activebackground=COLORS["bg_card"],
            anchor="w", cursor="hand2")
        self._same_folder_cb.pack(fill="x")

        self._last_dir_label = tk.Label(of,
            text=self._last_dir_display(),
            font=FONTS["tiny"], fg=COLORS["text_dim"], bg=COLORS["bg_card"], anchor="w")
        self._last_dir_label.pack(fill="x", pady=(2, 0))

    def _last_dir_display(self) -> str:
        d = self._last_output_dir
        if not d:
            return "Last output folder: (none yet)"
        short = d if len(d) <= 48 else "…" + d[-45:]
        return f"Last output folder: {short}"

    # ── Cost estimate panel ───────────────────────────────────────────

    def _build_cost_panel(self, parent):
        """Build the cost estimate card shown in the Claude options area."""
        self._cost_frame = tk.Frame(parent,
            bg=COLORS["key_bg"],
            highlightbackground=COLORS["border"], highlightthickness=1)
        self._cost_frame.pack(fill="x", pady=(10, 2))

        hdr = tk.Frame(self._cost_frame, bg=COLORS["key_bg"])
        hdr.pack(fill="x", padx=10, pady=(6, 2))
        tk.Label(hdr, text="ESTIMATED COST", font=FONTS["badge"],
                 fg=COLORS["accent"], bg=COLORS["key_bg"]).pack(side="left")
        self._cost_refresh_btn = tk.Button(hdr, text="↻", font=FONTS["tiny"],
            bg=COLORS["key_bg"], fg=COLORS["text_dim"], relief="flat",
            cursor="hand2", padx=4,
            command=self._refresh_cost)
        self._cost_refresh_btn.pack(side="right")

        self._cost_main = tk.Label(self._cost_frame,
            text="Load a file to see estimate",
            font=("Consolas", 12, "bold"), fg=COLORS["text_dim"],
            bg=COLORS["key_bg"], anchor="w", padx=10)
        self._cost_main.pack(fill="x")

        self._cost_detail = tk.Label(self._cost_frame,
            text="", font=FONTS["tiny"], fg=COLORS["text_dim"],
            bg=COLORS["key_bg"], anchor="w", padx=10, justify="left")
        self._cost_detail.pack(fill="x", pady=(0, 6))

    def _refresh_cost(self):
        if not self.source_blocks or self.engine.get() != "claude":
            if hasattr(self, '_cost_main'):
                self._cost_main.configure(
                    text="N/A for free engine" if self.engine.get() != "claude"
                         else "Load a file to see estimate",
                    fg=COLORS["text_dim"])
                self._cost_detail.configure(text="")
            return

        model   = self.claude_model.get()
        has_ctx = bool(self.context_blocks)
        est     = estimate_cost(self.source_blocks, model, self._api_key, has_ctx)

        if not est:
            return

        total = est["total_cost"]
        if total < 0.01:
            cost_str = f"< $0.01"
        else:
            cost_str = f"~${total:.3f}"

        self._cost_main.configure(
            text=cost_str,
            fg=COLORS["success"] if total < 0.05 else
               COLORS["warning"] if total < 0.50 else
               COLORS["error"])

        detail = (
            f"{est['input_tokens']:,} in + {est['output_tokens']:,} out tokens\n"
            f"${est['input_mtok']:.2f}/${ est['output_mtok']:.2f} per MTok  "
            f"({est['model_label']})"
        )
        if has_ctx:
            detail += "  [+context]"
        self._cost_detail.configure(text=detail)

    # ── Dropdown helpers ─────────────────────────────────────────────

    def _make_dropdown(self, parent, p, languages, textvariable, on_change=None):
        values = [f"{flag}  {label}" for _, label, flag in languages]
        codes  = [code for code, _, _ in languages]

        style = ttk.Style()
        style.theme_use('default')
        style.configure("Lang.TCombobox",
            fieldbackground=COLORS["bg_input"],
            background=COLORS["bg_input"],
            foreground=COLORS["text"],
            selectbackground=COLORS["accent"],
            selectforeground=COLORS["text_bright"],
            arrowcolor=COLORS["accent"],
            bordercolor=COLORS["border"],
            lightcolor=COLORS["border"],
            darkcolor=COLORS["border"],
        )
        style.map("Lang.TCombobox",
            fieldbackground=[("readonly", COLORS["bg_input"])],
            foreground=[("readonly", COLORS["text"])],
        )

        try:
            cur_idx = codes.index(textvariable.get())
        except ValueError:
            cur_idx = 0

        combo_var = tk.StringVar(value=values[cur_idx])
        combo = ttk.Combobox(parent, textvariable=combo_var,
                             values=values, state="readonly",
                             style="Lang.TCombobox", font=FONTS["body"])
        combo.pack(fill="x", **p, ipady=4)

        def _on_select(event=None):
            idx = combo.current()
            if idx >= 0:
                textvariable.set(codes[idx])
                if on_change:
                    on_change(codes[idx])

        combo.bind("<<ComboboxSelected>>", _on_select)
        return combo, codes, combo_var

    def _build_src_dropdown(self, parent, p):
        self._src_combo, self._src_codes, self._src_combo_var = \
            self._make_dropdown(parent, p, SOURCE_LANGUAGES, self.source_lang)

    def _build_tgt_dropdown(self, parent, p):
        self._tgt_combo, self._tgt_codes, self._tgt_combo_var = \
            self._make_dropdown(parent, p, TARGET_LANGUAGES, self.target_lang)

    def _set_src_combo(self, code):
        try:
            idx = self._src_codes.index(code)
            self._src_combo.current(idx)
            self.source_lang.set(code)
        except (ValueError, AttributeError):
            pass

    # ── Claude options ───────────────────────────────────────────────

    def _build_claude_options(self, parent):
        # API Key
        tk.Label(parent, text="Claude API Key",
            font=FONTS["small"], fg=COLORS["text_dim"], bg=COLORS["bg_card"], anchor="w"
            ).pack(fill="x")

        key_row = tk.Frame(parent, bg=COLORS["bg_card"])
        key_row.pack(fill="x", pady=(4, 0))

        self.key_display = tk.Label(key_row,
            text=self._mask_key(self._api_key),
            font=FONTS["mono_sm"], bg=COLORS["key_bg"], fg=COLORS["text_dim"],
            anchor="w", padx=8, pady=5, relief="flat",
            highlightbackground=COLORS["border"], highlightthickness=1)
        self.key_display.pack(side="left", fill="x", expand=True)

        tk.Button(key_row, text="✎  Edit", font=FONTS["tiny"],
            bg=COLORS["bg_input"], fg=COLORS["text_dim"], relief="flat",
            activebackground=COLORS["border"], activeforeground=COLORS["text_bright"],
            cursor="hand2", padx=10, pady=5,
            command=self._edit_key).pack(side="right", padx=(6, 0))

        tk.Label(parent, text="Masked, read-only. Click Edit to update.",
            font=FONTS["tiny"], fg=COLORS["text_dim"], bg=COLORS["bg_card"], anchor="w"
            ).pack(fill="x", pady=(3, 0))

        # Cost estimate panel (v0.6.0)
        self._build_cost_panel(parent)

        # Model
        tk.Label(parent, text="Claude Model",
            font=FONTS["small"], fg=COLORS["text_dim"], bg=COLORS["bg_card"], anchor="w"
            ).pack(fill="x", pady=(10, 2))
        for val, lbl in CLAUDE_MODELS:
            pricing = _FALLBACK_PRICES.get(val, {})
            price_hint = (f"  [${pricing['input']:.0f}/${ pricing['output']:.0f}/MTok]"
                          if pricing else "")
            tk.Radiobutton(parent,
                text=lbl + price_hint,
                variable=self.claude_model, value=val,
                font=FONTS["tiny"], fg=COLORS["text"], bg=COLORS["bg_card"],
                selectcolor=COLORS["bg_input"], activebackground=COLORS["bg_card"],
                anchor="w").pack(fill="x", padx=4)

        # Batch size
        tk.Label(parent, text="Batch size  (blocks per API call)",
            font=FONTS["small"], fg=COLORS["text_dim"], bg=COLORS["bg_card"], anchor="w"
            ).pack(fill="x", pady=(10, 2))
        for bval, blbl in BATCH_OPTIONS:
            tk.Radiobutton(parent, text=blbl, variable=self.batch_size, value=bval,
                font=FONTS["tiny"], fg=COLORS["text"], bg=COLORS["bg_card"],
                selectcolor=COLORS["bg_input"], activebackground=COLORS["bg_card"],
                anchor="w").pack(fill="x", padx=4)

        # Workers
        tk.Label(parent, text="Parallel workers  (concurrent API calls)",
            font=FONTS["small"], fg=COLORS["text_dim"], bg=COLORS["bg_card"], anchor="w"
            ).pack(fill="x", pady=(10, 2))
        for wval, wlbl in WORKER_OPTIONS:
            tk.Radiobutton(parent, text=wlbl, variable=self.workers, value=wval,
                font=FONTS["tiny"], fg=COLORS["text"], bg=COLORS["bg_card"],
                selectcolor=COLORS["bg_input"], activebackground=COLORS["bg_card"],
                anchor="w").pack(fill="x", padx=4)

    def _build_right(self, parent):
        sty = ttk.Style()
        sty.theme_use('default')
        sty.configure("T.TNotebook", background=COLORS["bg_dark"], borderwidth=0)
        sty.configure("T.TNotebook.Tab", background=COLORS["bg_mid"],
                      foreground=COLORS["text_dim"], padding=[16, 8],
                      font=FONTS["small"], borderwidth=0)
        sty.map("T.TNotebook.Tab",
                background=[("selected", COLORS["bg_card"])],
                foreground=[("selected", COLORS["text_bright"])])

        nb = ttk.Notebook(parent, style="T.TNotebook")
        nb.pack(fill="both", expand=True)
        self.notebook = nb

        # Tab 1: Preview
        t1 = tk.Frame(nb, bg=COLORS["bg_card"])
        nb.add(t1, text="  Source Preview  ")
        self.preview_text = scrolledtext.ScrolledText(
            t1, font=FONTS["mono_sm"], bg=COLORS["bg_card"], fg=COLORS["text"],
            insertbackground=COLORS["text"], selectbackground=COLORS["accent"],
            relief="flat", state="disabled", wrap="word", highlightthickness=0)
        self.preview_text.pack(fill="both", expand=True, padx=8, pady=8)
        self.preview_text.tag_configure("id",  foreground=COLORS["accent"],
                                        font=("Consolas", 10, "bold"))
        self.preview_text.tag_configure("ts",  foreground=COLORS["text_dim"],
                                        font=("Consolas", 9))
        self.preview_text.tag_configure("txt", foreground=COLORS["text"])

        # Tab 2: Comparison
        t2 = tk.Frame(nb, bg=COLORS["bg_card"])
        nb.add(t2, text="  Comparison  ")
        ch = tk.Frame(t2, bg=COLORS["bg_card"])
        ch.pack(fill="x", padx=8, pady=(8, 4))
        tk.Label(ch, text="ORIGINAL",   font=FONTS["badge"], fg=COLORS["text_dim"],
                 bg=COLORS["bg_card"]).pack(side="left",  expand=True)
        tk.Label(ch, text="TRANSLATED", font=FONTS["badge"], fg=COLORS["success"],
                 bg=COLORS["bg_card"]).pack(side="right", expand=True)
        cb = tk.Frame(t2, bg=COLORS["bg_card"])
        cb.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.compare_orig = scrolledtext.ScrolledText(cb, font=FONTS["mono_sm"],
            bg=COLORS["bg_input"], fg=COLORS["text"], relief="flat",
            state="disabled", wrap="word", highlightthickness=0, width=40)
        self.compare_orig.pack(side="left", fill="both", expand=True, padx=(0, 4))
        self.compare_trans = scrolledtext.ScrolledText(cb, font=FONTS["mono_sm"],
            bg=COLORS["bg_input"], fg=COLORS["success"], relief="flat",
            state="disabled", wrap="word", highlightthickness=0, width=40)
        self.compare_trans.pack(side="right", fill="both", expand=True, padx=(4, 0))

        # Tab 3: Log
        t3 = tk.Frame(nb, bg=COLORS["bg_card"])
        nb.add(t3, text="  Activity Log  ")
        self.log_text = scrolledtext.ScrolledText(
            t3, font=FONTS["mono_sm"], bg=COLORS["bg_card"], fg=COLORS["text_dim"],
            insertbackground=COLORS["text"], relief="flat",
            state="disabled", wrap="word", highlightthickness=0)
        self.log_text.pack(fill="both", expand=True, padx=8, pady=8)
        for tag, color in [("info", COLORS["text_dim"]), ("success", COLORS["success"]),
                           ("warn", COLORS["warning"]), ("error", COLORS["error"]),
                           ("accent", COLORS["accent"])]:
            self.log_text.tag_configure(tag, foreground=color)

    def _build_footer(self, parent):
        sty = ttk.Style()
        sty.configure("P.Horizontal.TProgressbar",
                      troughcolor=COLORS["bg_dark"], background=COLORS["accent"],
                      borderwidth=0, thickness=6)
        ttk.Progressbar(parent, variable=self.progress_var, maximum=100,
                        style="P.Horizontal.TProgressbar"
                        ).pack(fill="x", padx=16, pady=(8, 0))
        sr = tk.Frame(parent, bg=COLORS["bg_mid"])
        sr.pack(fill="x", padx=16)
        tk.Label(sr, textvariable=self.status_text, font=FONTS["tiny"],
                 fg=COLORS["text_dim"], bg=COLORS["bg_mid"], anchor="w").pack(side="left")
        self.pct_label = tk.Label(sr, text="", font=FONTS["tiny"],
                                  fg=COLORS["accent"], bg=COLORS["bg_mid"], anchor="e")
        self.pct_label.pack(side="right")

    # ── Widget Helpers ────────────────────────────────────────────────

    def _sec(self, parent, num, title):
        fr = tk.Frame(parent, bg=COLORS["bg_card"])
        fr.pack(fill="x", padx=16, pady=(14, 6))
        tk.Label(fr, text=num, font=FONTS["badge"],
                 fg=COLORS["accent"], bg="#1a2744", padx=6, pady=1).pack(side="left")
        tk.Label(fr, text=f"  {title}", font=FONTS["badge"],
                 fg=COLORS["text_dim"], bg=COLORS["bg_card"], anchor="w").pack(side="left")

    def _eng_btn(self, parent, value, name, badge_text, badge_color, desc):
        sel = self.engine.get() == value
        fr = tk.Frame(parent,
            bg=COLORS["drop_active"] if sel else COLORS["bg_input"],
            highlightbackground=COLORS["accent"] if sel else COLORS["border"],
            highlightthickness=1, cursor="hand2")
        fr.pack(fill="x", pady=3)

        def select(e=None):
            self.engine.set(value)
            for w in parent.winfo_children():
                w.destroy()
            self._eng_btn(parent, "claude", "Claude API", "RECOMMENDED",
                          COLORS["success"], "Best quality — tone, humor, cultural nuances")
            self._eng_btn(parent, "free", "MyMemory", "FREE",
                          COLORS["accent2"], "No API key — literal, less nuanced")

        fr.bind("<Button-1>", select)
        top = tk.Frame(fr, bg=fr["bg"])
        top.pack(fill="x", padx=10, pady=(8, 2))
        top.bind("<Button-1>", select)
        rb = tk.Radiobutton(top, variable=self.engine, value=value,
                            bg=fr["bg"], fg=COLORS["text"],
                            selectcolor=COLORS["bg_input"], activebackground=fr["bg"])
        rb.pack(side="left")
        nm = tk.Label(top, text=name, font=FONTS["body"],
                      fg=COLORS["text_bright"] if sel else COLORS["text"], bg=fr["bg"])
        nm.pack(side="left")
        nm.bind("<Button-1>", select)
        bd = tk.Label(top, text=f" {badge_text} ", font=FONTS["badge"],
                      fg="#ffffff", bg=badge_color)
        bd.pack(side="right")
        bd.bind("<Button-1>", select)
        dl = tk.Label(fr, text=desc, font=FONTS["tiny"],
                      fg=COLORS["text_dim"], bg=fr["bg"], anchor="w", wraplength=360)
        dl.pack(fill="x", padx=30, pady=(0, 8))
        dl.bind("<Button-1>", select)

    def _on_engine_change(self, *args):
        if self.engine.get() == "claude":
            self.claude_frame.pack(fill="x", padx=16, pady=(4, 4))
        else:
            self.claude_frame.pack_forget()
        self._refresh_cost()

    # ── API Key ───────────────────────────────────────────────────────

    def _mask_key(self, key: str) -> str:
        k = key.strip()
        if not k:
            return "No key set — click Edit to add one"
        if len(k) <= 8:
            return "•" * len(k)
        return k[:7] + " ••••••••••••••••••••• " + k[-4:]

    def _edit_key(self):
        dlg = tk.Toplevel(self)
        dlg.title("Edit Claude API Key")
        dlg.configure(bg=COLORS["bg_card"])
        dlg.resizable(False, False)
        dlg.transient(self)
        dlg.grab_set()
        self.update_idletasks()
        w, h = 460, 210
        x = self.winfo_rootx() + (self.winfo_width()  - w) // 2
        y = self.winfo_rooty() + (self.winfo_height() - h) // 2
        dlg.geometry(f"{w}x{h}+{x}+{y}")

        tk.Label(dlg, text="Update Claude API Key",
                 font=FONTS["heading"], fg=COLORS["text_bright"],
                 bg=COLORS["bg_card"]).pack(pady=(18, 2))
        tk.Label(dlg, text="Paste your key. Stored locally, sent only to api.anthropic.com.",
                 font=FONTS["tiny"], fg=COLORS["text_dim"],
                 bg=COLORS["bg_card"], justify="center").pack()

        var = tk.StringVar(value=self._api_key)
        ent = tk.Entry(dlg, textvariable=var, show="•",
                       font=FONTS["mono_sm"], bg=COLORS["bg_input"], fg=COLORS["text"],
                       insertbackground=COLORS["text"], relief="flat",
                       highlightbackground=COLORS["border"], highlightthickness=1, width=48)
        ent.pack(padx=20, pady=(10, 4), ipady=6)
        ent.focus_set()

        show_var = tk.BooleanVar(value=False)
        def toggle():
            show_var.set(not show_var.get())
            ent.configure(show="" if show_var.get() else "•")
            sb2.configure(text="Hide" if show_var.get() else "Show")
        sb2 = tk.Button(dlg, text="Show", font=FONTS["tiny"],
                        bg=COLORS["bg_input"], fg=COLORS["text_dim"],
                        relief="flat", cursor="hand2", command=toggle)
        sb2.pack()

        def save():
            self._api_key = var.get().strip()
            self.key_display.configure(text=self._mask_key(self._api_key))
            save_config({'api_key': self._api_key})
            _live_price_cache.clear()   # force re-verify with new key
            self._refresh_cost()
            dlg.destroy()

        br = tk.Frame(dlg, bg=COLORS["bg_card"])
        br.pack(pady=(10, 0))
        tk.Button(br, text="Save", font=FONTS["small"],
                  bg=COLORS["btn_primary"], fg="#ffffff", relief="flat",
                  cursor="hand2", padx=18, pady=4, command=save).pack(side="left", padx=6)
        tk.Button(br, text="Cancel", font=FONTS["small"],
                  bg=COLORS["bg_input"], fg=COLORS["text_dim"], relief="flat",
                  cursor="hand2", padx=18, pady=4,
                  command=dlg.destroy).pack(side="left", padx=6)

        ent.bind("<Return>", lambda e: save())
        ent.bind("<Escape>", lambda e: dlg.destroy())
        dlg.wait_window()

    # ── Help ──────────────────────────────────────────────────────────

    def _show_help(self):
        dlg = tk.Toplevel(self)
        dlg.title(f"Help — {APP_TITLE}")
        dlg.configure(bg=COLORS["bg_card"])
        dlg.transient(self)
        self.update_idletasks()
        w, h = 680, 600
        x = self.winfo_rootx() + max(0, (self.winfo_width()  - w) // 2)
        y = self.winfo_rooty() + max(0, (self.winfo_height() - h) // 2)
        dlg.geometry(f"{w}x{h}+{x}+{y}")
        dlg.minsize(520, 420)
        dlg.resizable(True, True)

        txt = scrolledtext.ScrolledText(dlg, font=("Consolas", 9),
            bg=COLORS["bg_dark"], fg=COLORS["text"], relief="flat",
            wrap="word", padx=18, pady=14, highlightthickness=0)
        txt.pack(fill="both", expand=True)
        txt.insert("1.0", HELP_TEXT)
        txt.tag_configure("hdr", foreground=COLORS["accent"],
                          font=("Consolas", 9, "bold"))
        for m in re.finditer(r'^([A-Z][A-Z /()0-9.-]{3,})\n-{3,}', HELP_TEXT, re.MULTILINE):
            line_no = HELP_TEXT[:m.start()].count('\n') + 1
            txt.tag_add("hdr", f"{line_no}.0", f"{line_no}.end")
        txt.configure(state="disabled")

        tk.Button(dlg, text="  Close  ", font=FONTS["small"],
                  bg=COLORS["btn_primary"], fg="#ffffff", relief="flat",
                  cursor="hand2", padx=20, pady=5,
                  command=dlg.destroy).pack(pady=(0, 14))

    # ── File Handling ─────────────────────────────────────────────────

    def _browse(self):
        path = filedialog.askopenfilename(
            title="Select source SRT file",
            filetypes=[("SRT files", "*.srt"), ("All files", "*.*")])
        if path:
            self._load_source_file(path)

    def _browse_context(self):
        path = filedialog.askopenfilename(
            title="Select context SRT file (same film, different language)",
            filetypes=[("SRT files", "*.srt"), ("All files", "*.*")])
        if path:
            self._load_context_file(path)

    def _load_source_file(self, path: str):
        path = path.strip()
        if not path.lower().endswith('.srt'):
            messagebox.showwarning("Wrong file type",
                "Please select an .srt subtitle file.")
            return
        try:
            blocks, enc = parse_srt(path)
        except Exception as e:
            messagebox.showerror("Parse Error", f"Could not parse file:\n{e}")
            return
        if not blocks:
            messagebox.showwarning("Empty File", "No subtitle blocks found.")
            return

        self.source_blocks = blocks
        self.input_path    = path
        name = Path(path).stem
        self.file_label.configure(
            text=name + ".srt", fg=COLORS["text_bright"])

        # Encoding + block info
        enc_short = enc.upper().replace("-SIG", "+BOM")
        self.file_info.configure(
            text=f"{len(blocks):,} blocks  •  "
                 f"IDs {blocks[0]['id']}–{blocks[-1]['id']}  •  {enc_short}")

        avg = sum(len(' '.join(b['text_lines'])) for b in blocks) / len(blocks)
        sug = suggest_batch_size(blocks)
        self.batch_size.set(sug)
        self.batch_hint.configure(text=f"Auto batch: {sug}  (avg {avg:.0f} chars/block)")

        detected_code = detect_language(blocks)
        self._set_src_combo(detected_code)

        # Reset drop-zone style
        self._src_drop.configure(
            highlightbackground=COLORS["success"], bg=COLORS["bg_input"])

        self._log(f"Loaded: {name}.srt — {len(blocks):,} blocks  [{enc_short}]", "accent")
        self._log(f"Detected: {_LANG_LABEL.get(detected_code, detected_code)}  •  "
                  f"avg {avg:.0f} chars/block  •  auto batch={sug}", "info")
        self._show_preview()
        self._refresh_cost()

    def _load_context_file(self, path: str):
        path = path.strip()
        if not path.lower().endswith('.srt'):
            messagebox.showwarning("Wrong file type",
                "Please select an .srt subtitle file.")
            return
        try:
            blocks, enc = parse_srt(path)
        except Exception as e:
            messagebox.showerror("Parse Error", f"Could not parse context file:\n{e}")
            return
        if not blocks:
            messagebox.showwarning("Empty File", "No subtitle blocks found in context file.")
            return

        self.context_blocks = blocks
        self.context_path   = path
        name = Path(path).stem
        enc_short = enc.upper().replace("-SIG", "+BOM")
        self._ctx_label.configure(
            text=f"✓  {name}.srt  ({len(blocks):,} blocks  [{enc_short}])",
            fg=COLORS["success"])
        self._ctx_clear_btn.pack(side="right")
        self._log(f"Context: {name}.srt — {len(blocks):,} blocks  [{enc_short}]", "info")
        self._refresh_cost()

    def _clear_context(self):
        self.context_blocks = []
        self.context_path   = ""
        self._ctx_label.configure(
            text="Drop context .srt here  or  Browse…",
            fg=COLORS["text_dim"])
        self._ctx_clear_btn.pack_forget()
        self._refresh_cost()

    def _show_preview(self):
        self.preview_text.configure(state="normal")
        self.preview_text.delete("1.0", "end")
        for b in self.source_blocks[:50]:
            self.preview_text.insert("end", f"{b['id']}\n", "id")
            self.preview_text.insert("end", f"{b['timestamp']}\n", "ts")
            for line in b['text_lines']:
                self.preview_text.insert("end", f"{line}\n", "txt")
            self.preview_text.insert("end", "\n")
        if len(self.source_blocks) > 50:
            self.preview_text.insert("end",
                f"\n... and {len(self.source_blocks)-50:,} more blocks\n", "ts")
        self.preview_text.configure(state="disabled")

    # ── Translation ───────────────────────────────────────────────────

    def _resolve_output_path(self) -> str | None:
        """
        Determine output file path.
        - If "same folder as source" is ticked: place output next to input.
        - Otherwise: open Save dialog, remembering last folder used.
        Returns the resolved path, or None if cancelled.
        """
        default_name = Path(self.input_path).stem + f"_{self.target_lang.get()}.srt"

        if self.same_folder.get() and self.input_path:
            return str(Path(self.input_path).parent / default_name)

        init_dir = self._last_output_dir or str(Path(self.input_path).parent)
        output = filedialog.asksaveasfilename(
            title="Save translated file as",
            defaultextension=".srt",
            initialfile=default_name,
            initialdir=init_dir,
            filetypes=[("SRT files", "*.srt")])
        if not output:
            return None

        self._last_output_dir = str(Path(output).parent)
        self._last_dir_label.configure(text=self._last_dir_display())
        return output

    def _start(self):
        if not self.source_blocks:
            messagebox.showwarning("No File", "Please load an SRT file first.")
            return
        if self.engine.get() == "claude" and not self._api_key.strip():
            messagebox.showwarning("API Key",
                "No Claude API key set.\nClick the Edit button.")
            return

        output = self._resolve_output_path()
        if not output:
            return
        self.output_path = output

        self.is_translating    = True
        self.cancel_flag       = False
        self.translated_blocks = []
        self.progress_var.set(0)
        self.start_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.notebook.select(2)

        total      = len(self.source_blocks)
        bsize      = self.batch_size.get()
        n_bat      = (total + bsize - 1) // bsize
        model_lbl  = self.claude_model.get() if self.engine.get() == "claude" else "MyMemory"
        src_label  = _LANG_LABEL.get(self.source_lang.get(), self.source_lang.get())
        tgt_label  = _LANG_LABEL.get(self.target_lang.get(), self.target_lang.get())
        has_ctx    = bool(self.context_blocks) and self.engine.get() == "claude"

        self._log("═" * 50, "info")
        self._log(f"Starting: {src_label} → {tgt_label}", "accent")
        self._log(f"Engine  : {model_lbl}", "info")
        self._log(f"Blocks  : {total:,}  │  Batch: {bsize}  │  Workers: {self.workers.get()}", "info")
        self._log(f"Context : {'yes (' + Path(self.context_path).name + ')' if has_ctx else 'none'}", "info")
        self._log(f"Output  : {self.output_path}", "info")
        self._log("═" * 50, "info")

        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self):
        blocks    = self.source_blocks
        total     = len(blocks)
        engine    = self.engine.get()
        api_key   = self._api_key
        src       = _LANG_LABEL.get(self.source_lang.get(), self.source_lang.get())
        tgt       = _LANG_LABEL.get(self.target_lang.get(), self.target_lang.get())
        model     = self.claude_model.get()
        bsize     = self.batch_size.get()
        n_workers = self.workers.get() if engine == "claude" else 1
        errors    = []

        # Build context script once (stripped of all structural data)
        ctx_script = ""
        if engine == "claude" and self.context_blocks:
            ctx_script = build_context_script(self.context_blocks)

        batches          = [blocks[i:i+bsize] for i in range(0, total, bsize)]
        n_batches        = len(batches)
        results_by_batch = [None] * n_batches
        completed        = [0]
        lock             = threading.Lock()

        def do_batch(idx, batch):
            if self.cancel_flag:
                return idx, [{**b, "text_lines": b["text_lines"][:]} for b in batch]
            for attempt in range(3):
                try:
                    if engine == "claude":
                        out = translate_batch_claude(
                            batch, src, tgt, api_key, model, ctx_script)
                    else:
                        out = [{**b, "text_lines": translate_free(
                                b["text_lines"],
                                self.source_lang.get(), self.target_lang.get())}
                               for b in batch]
                    return idx, out
                except Exception as e:
                    if attempt < 2:
                        wait = 2 ** (attempt + 1)
                        self._log(f"Batch {idx+1} attempt {attempt+1} failed: {e}. "
                                  f"Retry in {wait}s…", "warn")
                        time.sleep(wait)
                    else:
                        self._log(f"✗ Batch {idx+1} failed: {e} — keeping originals", "error")
                        errors.append(f"Batch {idx+1}: {e}")
                        return idx, [{**b, "text_lines": b["text_lines"][:]} for b in batch]

        def upd(n_done, bat_num):
            pct = n_done / total * 100
            self.after(0, lambda: self.progress_var.set(pct))
            self.after(0, lambda: self.status_text.set(
                f"Batch {bat_num}/{n_batches}  —  {n_done:,}/{total:,} blocks  ({pct:.0f}%)"))
            self.after(0, lambda: self.pct_label.configure(text=f"{pct:.0f}%"))

        with concurrent.futures.ThreadPoolExecutor(max_workers=n_workers) as pool:
            futs = {pool.submit(do_batch, i, b): i for i, b in enumerate(batches)}
            for fut in concurrent.futures.as_completed(futs):
                if self.cancel_flag:
                    break
                bidx, bres = fut.result()
                results_by_batch[bidx] = bres
                with lock:
                    completed[0] += len(bres)
                    done = completed[0]
                upd(done, bidx + 1)
                self._log(f"  ✓ Batch {bidx+1:3d}/{n_batches}  ({len(bres)} blocks)", "info")

        if self.cancel_flag:
            self._log("Translation cancelled.", "warn")

        self.translated_blocks = [
            blk
            for br in results_by_batch if br is not None
            for blk in br
        ]

        if len(self.translated_blocks) == total and not self.cancel_flag:
            try:
                write_srt(self.translated_blocks, self.output_path)
                self._log(f"\nFile saved: {self.output_path}", "success")
            except Exception as e:
                self._log(f"✗ Failed to write: {e}", "error")
                self.after(0, self._done)
                return

            self._log("\n─── VERIFICATION ───", "accent")
            try:
                ob, _ = parse_srt(self.output_path)
                checks = [
                    ("Block count",     len(ob) == total),
                    ("First ID",        ob[0]['id'] == blocks[0]['id']),
                    ("Last ID",         ob[-1]['id'] == blocks[-1]['id']),
                    ("All IDs match",   all(ob[j]['id'] == blocks[j]['id'] for j in range(total))),
                    ("All timestamps",  all(ob[j]['timestamp'] == blocks[j]['timestamp'] for j in range(total))),
                    ("All line counts", all(len(ob[j]['text_lines']) == len(blocks[j]['text_lines']) for j in range(total))),
                ]
                ok_all = all(ok for _, ok in checks)
                for nm, ok in checks:
                    self._log(f"  {'✓' if ok else '✗'} {nm}", "success" if ok else "error")
                self._log(
                    f"\n{'✅ SUCCESS' if ok_all else '⚠ Completed with issues'}"
                    f" — {total:,} blocks translated & verified",
                    "success" if ok_all else "warn")
            except Exception as e:
                self._log(f"Verification error: {e}", "error")

            if errors:
                self._log(f"\n{len(errors)} batch error(s):", "warn")
                for err in errors[:10]:
                    self._log(f"  • {err}", "warn")

            self.after(0, self._show_comparison)

        self.after(0, self._done)

    def _done(self):
        self.is_translating = False
        self.start_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")
        if self.translated_blocks and len(self.translated_blocks) == len(self.source_blocks):
            self.status_text.set(f"Done — {len(self.translated_blocks):,} blocks translated")
            self.notebook.select(1)
        elif self.cancel_flag:
            self.status_text.set("Cancelled")
        else:
            self.status_text.set("Completed with errors — check Activity Log")

    def _cancel(self):
        self.cancel_flag = True

    def _show_comparison(self):
        self.compare_orig.configure(state="normal")
        self.compare_trans.configure(state="normal")
        self.compare_orig.delete("1.0", "end")
        self.compare_trans.delete("1.0", "end")
        for i in range(min(60, len(self.source_blocks))):
            s = self.source_blocks[i]
            o = self.translated_blocks[i] if i < len(self.translated_blocks) else None
            self.compare_orig.insert("end", f"[{s['id']}] {s['timestamp']}\n")
            for ln in s['text_lines']:
                self.compare_orig.insert("end", f"  {ln}\n")
            self.compare_orig.insert("end", "\n")
            if o:
                self.compare_trans.insert("end", f"[{o['id']}] {o['timestamp']}\n")
                for ln in o['text_lines']:
                    self.compare_trans.insert("end", f"  {ln}\n")
                self.compare_trans.insert("end", "\n")
        self.compare_orig.configure(state="disabled")
        self.compare_trans.configure(state="disabled")

    # ── Logging ───────────────────────────────────────────────────────

    def _log(self, message, tag="info"):
        def _ins():
            self.log_text.configure(state="normal")
            self.log_text.insert("end", f"[{time.strftime('%H:%M:%S')}] {message}\n", tag)
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        self.after(0, _ins)


# ═══════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    app = App()
    app.mainloop()
