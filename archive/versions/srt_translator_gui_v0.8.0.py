#!/usr/bin/env python3
"""
╔═══════════════════════════════════════════════════════════╗
║       SRT Subtitle Translator  v0.8.0 — Desktop GUI       ║
║                                                           ║
║  Structure-preserving subtitle translation for .srt files ║
║  Engines: Claude API · MyMemory (free)                    ║
║  Author:  Luiz Junqueira & Claude AI                      ║
╚═══════════════════════════════════════════════════════════╝

v0.8.0 changes (GUI redesign, translation engine unchanged):
  • One-screen layout: FILE, LANGUAGES, ENGINE and a collapsible
    Advanced section; nothing scrolls at 1000×700
  • Fixed action bar with the cost estimate right above Start / Sample /
    Cancel and the progress bar
  • Languages side by side with a swap button; engine as a two-way
    toggle with the model drop-down beside it
  • Settings dialog (⚙) for the API key, catalog refresh and file paths
  • Names tab in the right panel (full height, auto-detect, load/save)
  • Tooltips instead of hint paragraphs; status line says the next step
  • Window size and position remembered; Advanced state remembered
  • Mouse wheel no longer changes drop-downs while scrolling

v0.7.0 changes:
  • Live model list from the Anthropic API (newest first, cached offline)
  • Live pricing from Anthropic's published pricing page, refreshed daily,
    with a pricing.json override and a built-in fallback table
  • Exact input-token count (count_tokens endpoint) for the estimate and
    real cost reported after each run from the API usage figures
  • Hearing-impaired cues ([brackets], (parentheses), ALL CAPS) are now
    translated; a checkbox turns this off
  • Structured JSON protocol: one entry per line, enforced by the API's
    JSON-schema output, so lines can no longer be merged, split or lost
  • Quality control pass: unchanged blocks are detected and retranslated,
    cut-off batches are split and retried, a QC report is logged
  • "Preserve names" list (UI + optional <file>.names.txt sidecar) and
    an auto-detect button that extracts people/places/institutions
  • Context file sent by time window (only the lines around each batch)
    with prompt caching on the fixed prompt
  • Formatting tags (<i>, <b>, {\\an8}) protected with placeholders
  • Sample run: translate the first 20 blocks to judge quality and cost
  • Output name without the source language tag (Movie.pt-BR.srt)
  • Fast cancel, local mouse wheel, empty blocks kept, invalid saved
    model falls back, dependencies installed on demand with a dialog
  • Claude calls use the official anthropic SDK (auto-retry, typed errors)
"""

import concurrent.futures
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext


# ═══════════════════════════════════════════════════════════════════════
# VERSION
# ═══════════════════════════════════════════════════════════════════════

APP_VERSION = "v0.8.0"
APP_TITLE   = f"SRT Subtitle Translator  {APP_VERSION}"
IS_FROZEN   = bool(getattr(sys, "frozen", False))
APP_DIR     = Path(sys.executable).parent if IS_FROZEN else Path(__file__).resolve().parent


# ═══════════════════════════════════════════════════════════════════════
# DEPENDENCIES  —  imported lazily, installed on demand (never at import)
# ═══════════════════════════════════════════════════════════════════════

REQUIRED_PACKAGES = [
    # (import name, pip name, why)
    ("requests",  "requests",  "MyMemory engine and pricing download"),
    ("anthropic", "anthropic", "Claude API engine"),
]


def _try_import(name):
    try:
        return __import__(name)
    except ImportError:
        return None


def _pip_install(pip_name: str) -> tuple[bool, str]:
    """Install a package with the running interpreter's pip. Returns (ok, output)."""
    cmd = [sys.executable, "-m", "pip", "install", "--upgrade", pip_name]
    try:
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600,
                              creationflags=flags)
        return proc.returncode == 0, (proc.stdout + proc.stderr)[-2000:]
    except Exception as e:  # pragma: no cover - environment specific
        return False, str(e)


def ensure_dependencies(parent=None) -> list:
    """
    Check the optional packages. Ask the user before installing anything.
    Returns the list of import names that are still missing afterwards.
    Inside a frozen .exe nothing can be installed; the exe bundles them.
    """
    missing = [(imp, pip, why) for imp, pip, why in REQUIRED_PACKAGES if _try_import(imp) is None]
    if not missing or IS_FROZEN:
        return [m[0] for m in missing]
    names = ", ".join(pip for _, pip, _ in missing)
    ok = messagebox.askyesno(
        "Install dependencies",
        f"{APP_TITLE} needs these Python packages:\n\n"
        + "\n".join(f"  • {pip}  ({why})" for _, pip, why in missing)
        + f"\n\nInstall now with pip?  (python -m pip install {names})",
        parent=parent)
    if not ok:
        return [m[0] for m in missing]
    still = []
    for imp, pip, _ in missing:
        done, out = _pip_install(pip)
        if not done or _try_import(imp) is None:
            still.append(imp)
            messagebox.showerror("Install failed",
                                 f"Could not install '{pip}'.\n\n{out}\n\n"
                                 f"Try manually:  python -m pip install {pip}", parent=parent)
    return still


def _anthropic():
    import anthropic  # noqa: F401  (lazy so the module imports without it)
    return anthropic


def _requests():
    import requests  # noqa: F401
    return requests


# ═══════════════════════════════════════════════════════════════════════
# PERSISTENT CONFIG
# ═══════════════════════════════════════════════════════════════════════

CONFIG_PATH = Path.home() / ".srt_translator_config.json"


def load_config() -> dict:
    try:
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def save_config(data: dict):
    try:
        existing = load_config()
        existing.update(data)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
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
# SRT PARSER & WRITER
# ═══════════════════════════════════════════════════════════════════════

_ENCODINGS = ["utf-8-sig", "utf-8", "cp1252", "latin-1", "cp1250"]
_TS_RE = re.compile(r"(\d+):(\d\d):(\d\d)[,.](\d{1,3})\s*-->\s*(\d+):(\d\d):(\d\d)[,.](\d{1,3})")


def _read_text(filepath: str) -> tuple:
    """Try encodings in order. Returns (text, encoding_name_used)."""
    for enc in _ENCODINGS:
        try:
            with open(filepath, "r", encoding=enc) as f:
                return f.read(), enc
        except (UnicodeDecodeError, LookupError):
            continue
    with open(filepath, "rb") as f:
        raw = f.read()
    return raw.decode("latin-1", errors="replace"), "latin-1 (lossy)"


def parse_srt_text(content: str) -> list:
    """Parse SRT text into blocks. Blocks with no text are kept (empty list)."""
    blocks = []
    content = content.replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")
    for rb in re.split(r"\n\s*\n+", content.strip()):
        lines = [l.strip() for l in rb.strip().split("\n")]
        if len(lines) >= 2 and "-->" in lines[1]:
            blocks.append({"id": lines[0], "timestamp": lines[1],
                           "text_lines": [l for l in lines[2:]]})
        elif len(lines) >= 1 and "-->" in lines[0]:
            # Missing index line: synthesise one so structure stays valid
            blocks.append({"id": str(len(blocks) + 1), "timestamp": lines[0],
                           "text_lines": lines[1:]})
    return blocks


def parse_srt(filepath: str) -> tuple:
    """Returns (blocks, encoding_used)."""
    content, enc = _read_text(filepath)
    return parse_srt_text(content), enc


def write_srt(blocks: list, filepath: str):
    with open(filepath, "w", encoding="utf-8", newline="") as f:
        f.write("﻿")
        for block in blocks:
            f.write(f"{block['id']}\r\n{block['timestamp']}\r\n")
            for line in block["text_lines"]:
                f.write(f"{line}\r\n")
            f.write("\r\n")


def timestamp_ms(timestamp: str) -> tuple:
    """'00:01:02,345 --> 00:01:04,000' → (62345, 64000). (0, 0) if unparsable."""
    m = _TS_RE.search(timestamp)
    if not m:
        return 0, 0
    g = [int(x) for x in m.groups()]
    start = ((g[0] * 60 + g[1]) * 60 + g[2]) * 1000 + int(str(g[3]).ljust(3, "0"))
    end   = ((g[4] * 60 + g[5]) * 60 + g[6]) * 1000 + int(str(g[7]).ljust(3, "0"))
    return start, end


# ═══════════════════════════════════════════════════════════════════════
# LANGUAGE DETECTION & BATCH SIZE
# ═══════════════════════════════════════════════════════════════════════

def detect_language(blocks: list) -> str:
    sample = " ".join(" ".join(b["text_lines"]) for b in blocks[:40]).lower()
    patterns = [
        ("ja-JP",    r"[぀-ゟ゠-ヿ]"),
        ("ko-KR",    r"[가-힯]"),
        ("zh-CN",    r"[一-鿿]{3,}"),
        ("ar-AR",    r"[؀-ۿ]"),
        ("en-US",    r"\b(the|and|is|are|you|have|what|this|that|with|for|not|but|they|was|will|would|could|can|how|who|where|when|why)\b"),
        ("pt-BR",    r"\b(que|não|nao|uma|com|para|esta|isso|como|mas|mais|ele|ela|voce|você|tem|são|sao|muito|pode|então|entao|também|fazer|quando)\b"),
        ("es-ES",    r"\b(que|los|las|una|por|con|para|esta|esto|como|pero|más|tiene|son|muy|puede|también|hacer|cuando)\b"),
        ("fr-FR",    r"\b(les|des|une|que|est|pas|pour|dans|avec|qui|sur|sont|mais|plus|tout|peut|cette|aussi|faire|comme)\b"),
        ("de-DE",    r"\b(und|der|die|das|ist|nicht|ein|eine|ich|sie|wir|auf|mit|den|von|hat|für|sind|auch|aber|oder|wenn)\b"),
        ("it-IT",    r"\b(che|non|una|per|sono|con|come|più|questo|anche|della|quello|hanno|essere|fare|tutto)\b"),
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
    avg = sum(len(" ".join(b["text_lines"])) for b in blocks) / len(blocks)
    if avg < 50:
        return 40
    if avg < 120:
        return 25
    return 15


# ═══════════════════════════════════════════════════════════════════════
# OUTPUT NAMING  —  strip the source language tag (Movie.en.srt → Movie)
# ═══════════════════════════════════════════════════════════════════════

_LANG_TAG_WORDS = {
    "en", "eng", "english", "es", "spa", "spanish", "pt", "por", "ptbr", "portuguese",
    "fr", "fra", "fre", "french", "de", "ger", "deu", "german", "it", "ita", "italian",
    "ja", "jpn", "japanese", "ko", "kor", "korean", "zh", "chi", "zho", "chinese",
    "ar", "ara", "arabic", "ru", "rus", "nl", "dut", "sv", "swe", "no", "nor", "da", "dan",
    "fi", "fin", "pl", "pol", "tr", "tur", "hi", "hin", "cs", "hu", "el", "he", "th", "vi",
    "sdh", "cc", "forced", "hi",
}
_LANG_TAG_RE = re.compile(r"\.([A-Za-z]{2,10})(?:[-_]([A-Za-z]{2,4}))?$")


def strip_language_tag(stem: str) -> str:
    """'Movie.en' → 'Movie'; 'Movie.en-US.sdh' → 'Movie'; 'Movie.2023' unchanged."""
    changed = True
    while changed:
        changed = False
        m = _LANG_TAG_RE.search(stem)
        if m and m.group(1).lower() in _LANG_TAG_WORDS:
            stem = stem[:m.start()]
            changed = True
    return stem


def default_output_name(input_path: str, target_code: str) -> str:
    return f"{strip_language_tag(Path(input_path).stem)}.{target_code}.srt"


# ═══════════════════════════════════════════════════════════════════════
# CUES, TAGS & PASSTHROUGH
# ═══════════════════════════════════════════════════════════════════════

_TAG_RE = re.compile(r"(</?[A-Za-z][^<>]*>|\{\\[^{}]*\})")
_PUNCT_ONLY_RE = re.compile(r"^[\W\d_♪♫]*$")   # no letters at all (♪, digits, dashes)
_CUE_BRACKET_RE = re.compile(r"^\s*[\[(].*[\])]\s*:?\s*$")
_CUE_CAPS_RE = re.compile(r"^[^a-z]*[A-Z][^a-z]*$")


def protect_tags(line: str) -> tuple:
    """Replace <i>…</i> / {\\an8} tags with {T1}, {T2}… placeholders."""
    tags = []

    def rep(m):
        tags.append(m.group(0))
        return f"{{T{len(tags)}}}"
    return _TAG_RE.sub(rep, line), tags


def restore_tags(line: str, tags: list) -> str:
    for i, tag in enumerate(tags, 1):
        ph = f"{{T{i}}}"
        if ph in line:
            line = line.replace(ph, tag, 1)
        elif tag.startswith("</"):
            line = line + tag
        else:
            line = tag + line
    # Remove any stray placeholder the model may have invented
    return re.sub(r"\{T\d+\}", "", line)


def is_cue(line: str) -> bool:
    """Hearing-impaired cue: [door slams], (laughs), APPLAUSE, MAN ON TV:"""
    s = _TAG_RE.sub("", line).strip()
    if not s or _PUNCT_ONLY_RE.match(s):
        return False
    if _CUE_BRACKET_RE.match(s):
        return True
    letters = re.sub(r"[^A-Za-z]", "", s)
    return len(letters) >= 3 and bool(_CUE_CAPS_RE.match(s))


def is_passthrough(line: str, translate_cues: bool = True) -> bool:
    """Lines that are never sent for translation."""
    s = _TAG_RE.sub("", line).strip()
    if not s or _PUNCT_ONLY_RE.match(s):
        return True
    if not translate_cues and is_cue(s):
        return True
    return False


# ═══════════════════════════════════════════════════════════════════════
# GLOSSARY  (names to preserve)
# ═══════════════════════════════════════════════════════════════════════

def parse_glossary(text: str) -> list:
    """One term per line (commas also accepted). Keeps order, drops duplicates."""
    seen, out = set(), []
    for raw in re.split(r"[\n,;]+", text or ""):
        term = raw.strip().strip("•-–").strip()
        if len(term) >= 2 and term.lower() not in seen:
            seen.add(term.lower())
            out.append(term)
    return out


def glossary_sidecar_path(srt_path: str) -> Path:
    p = Path(srt_path)
    return p.with_name(strip_language_tag(p.stem) + ".names.txt")


def glossary_violations(src_text: str, out_text: str, terms: list) -> list:
    """Terms present in the source block but absent from the translated block."""
    missing = []
    for term in terms:
        pat = r"(?<!\w)" + re.escape(term) + r"(?!\w)"
        if re.search(pat, src_text) and not re.search(pat, out_text, re.IGNORECASE):
            missing.append(term)
    return missing


# ═══════════════════════════════════════════════════════════════════════
# MODEL CATALOG & PRICING
# ═══════════════════════════════════════════════════════════════════════

PRICING_URL = "https://platform.claude.com/docs/en/about-claude/pricing.md"
PRICING_OVERRIDE_PATH = APP_DIR / "pricing.json"
PRICING_TTL_S = 24 * 3600
MODELS_TTL_S  = 24 * 3600
DEFAULT_MODEL = "claude-haiku-5-5"

# $ per million tokens — verified 2026-10-09 against the official pricing page.
# Keys are "family version" (see model_family_key). Last-resort fallback only.
_BUILTIN_PRICES = {
    "fable 5.1":  {"input": 10.0, "output": 50.0, "cache_read": 0.25, "cache_write": 12.5},
    "fable 5":    {"input": 10.0, "output": 50.0, "cache_read": 1.0,  "cache_write": 12.5},
    "opus 5.5":   {"input": 4.0,  "output": 20.0, "cache_read": 0.20, "cache_write": 5.0},
    "opus 5":     {"input": 5.0,  "output": 25.0, "cache_read": 0.50, "cache_write": 6.25},
    "opus 4.8":   {"input": 5.0,  "output": 25.0, "cache_read": 0.50, "cache_write": 6.25},
    "opus 4.7":   {"input": 5.0,  "output": 25.0, "cache_read": 0.50, "cache_write": 6.25},
    "opus 4.6":   {"input": 5.0,  "output": 25.0, "cache_read": 0.50, "cache_write": 6.25},
    "opus 4.5":   {"input": 5.0,  "output": 25.0, "cache_read": 0.50, "cache_write": 6.25},
    "sonnet 5.5": {"input": 2.0,  "output": 10.0, "cache_read": 0.20, "cache_write": 2.5},
    "sonnet 5":   {"input": 2.0,  "output": 10.0, "cache_read": 0.20, "cache_write": 2.5},
    "sonnet 4.6": {"input": 3.0,  "output": 15.0, "cache_read": 0.30, "cache_write": 3.75},
    "sonnet 4.5": {"input": 3.0,  "output": 15.0, "cache_read": 0.30, "cache_write": 3.75},
    "haiku 5.5":  {"input": 0.10, "output": 0.50, "cache_read": 0.01, "cache_write": 0.125},
    "haiku 4.5":  {"input": 1.0,  "output": 5.0,  "cache_read": 0.10, "cache_write": 1.25},
}

# Offline fallback list (what the API returned on 2026-10-09), newest first.
_BUILTIN_MODELS = [
    {"id": "claude-haiku-5-5",          "display_name": "Claude Haiku 5.5",  "created_at": "2026-10-07", "max_input_tokens": 1000000, "max_tokens": 128000, "thinking_off": "disabled", "effort": True,  "structured": True},
    {"id": "claude-sonnet-5-5",         "display_name": "Claude Sonnet 5.5", "created_at": "2026-09-28", "max_input_tokens": 1000000, "max_tokens": 128000, "thinking_off": "effort",   "effort": True,  "structured": True},
    {"id": "claude-opus-5-5",           "display_name": "Claude Opus 5.5",   "created_at": "2026-09-21", "max_input_tokens": 1000000, "max_tokens": 128000, "thinking_off": "effort",   "effort": True,  "structured": True},
    {"id": "claude-fable-5-1",          "display_name": "Claude Fable 5.1",  "created_at": "2026-08-28", "max_input_tokens": 1000000, "max_tokens": 128000, "thinking_off": "effort",   "effort": True,  "structured": True},
    {"id": "claude-opus-5",             "display_name": "Claude Opus 5",     "created_at": "2026-07-24", "max_input_tokens": 1000000, "max_tokens": 128000, "thinking_off": "disabled", "effort": True,  "structured": True},
    {"id": "claude-sonnet-5",           "display_name": "Claude Sonnet 5",   "created_at": "2026-06-29", "max_input_tokens": 1000000, "max_tokens": 128000, "thinking_off": "disabled", "effort": True,  "structured": True},
    {"id": "claude-fable-5",            "display_name": "Claude Fable 5",    "created_at": "2026-06-07", "max_input_tokens": 1000000, "max_tokens": 128000, "thinking_off": "effort",   "effort": True,  "structured": True},
    {"id": "claude-opus-4-8",           "display_name": "Claude Opus 4.8",   "created_at": "2026-05-28", "max_input_tokens": 1000000, "max_tokens": 128000, "thinking_off": "disabled", "effort": True,  "structured": True},
    {"id": "claude-opus-4-7",           "display_name": "Claude Opus 4.7",   "created_at": "2026-04-14", "max_input_tokens": 1000000, "max_tokens": 128000, "thinking_off": "disabled", "effort": True,  "structured": True},
    {"id": "claude-sonnet-4-6",         "display_name": "Claude Sonnet 4.6", "created_at": "2026-02-17", "max_input_tokens": 1000000, "max_tokens": 128000, "thinking_off": "disabled", "effort": True,  "structured": True},
    {"id": "claude-opus-4-6",           "display_name": "Claude Opus 4.6",   "created_at": "2026-02-04", "max_input_tokens": 1000000, "max_tokens": 128000, "thinking_off": "disabled", "effort": True,  "structured": True},
    {"id": "claude-opus-4-5-20251101",  "display_name": "Claude Opus 4.5",   "created_at": "2025-11-24", "max_input_tokens": 200000,  "max_tokens": 64000,  "thinking_off": None,       "effort": False, "structured": True},
    {"id": "claude-haiku-4-5-20251001", "display_name": "Claude Haiku 4.5",  "created_at": "2025-10-15", "max_input_tokens": 200000,  "max_tokens": 64000,  "thinking_off": None,       "effort": False, "structured": True},
    {"id": "claude-sonnet-4-5-20250929","display_name": "Claude Sonnet 4.5", "created_at": "2025-09-29", "max_input_tokens": 200000,  "max_tokens": 64000,  "thinking_off": None,       "effort": False, "structured": True},
]

_FAMILY_NAME_RE = re.compile(r"^\s*Claude\s+(Haiku|Sonnet|Opus|Fable|Mythos)\s+(\d+(?:\.\d+)?)", re.I)
_FAMILY_ID_RE   = re.compile(r"^claude-(haiku|sonnet|opus|fable|mythos)-(\d)(?:-(\d))?(?:-\d{8})?$")


def model_family_key(model_id_or_name: str) -> str:
    """'claude-haiku-4-5-20251001' or 'Claude Haiku 4.5 (…)' → 'haiku 4.5'; '' if unknown."""
    s = model_id_or_name.strip()
    m = _FAMILY_ID_RE.match(s)
    if m:
        ver = m.group(2) + (f".{m.group(3)}" if m.group(3) else "")
        return f"{m.group(1)} {ver}"
    m = _FAMILY_NAME_RE.match(s)
    if m:
        return f"{m.group(1).lower()} {m.group(2)}"
    return ""


def _money(cell: str):
    m = re.search(r"\$\s*([\d.]+)", cell)
    return float(m.group(1)) if m else None


def parse_pricing_markdown(text: str) -> dict:
    """Parse the official pricing page (markdown) into {family_key: prices}."""
    prices, in_table = {}, False
    for line in text.splitlines():
        if not line.startswith("|"):
            in_table = False
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if "Base input tokens" in line and "Output tokens" in line:
            in_table = True
            continue
        if not in_table or len(cells) < 6 or set(cells[1]) <= set(":- "):
            continue
        key = model_family_key(cells[0])
        if not key or key in prices:          # first row wins (Haiku 5.5 ≤100k tier)
            continue
        vals = [_money(c) for c in cells[1:6]]
        if None in vals:
            continue
        prices[key] = {"input": vals[0], "cache_write": vals[1],
                       "cache_read": vals[3], "output": vals[4]}
    return prices


def fetch_official_prices(timeout: int = 15) -> dict:
    """Download and parse the official pricing page. {} on any failure."""
    try:
        r = _requests().get(PRICING_URL, timeout=timeout,
                            headers={"User-Agent": f"srt-translator/{APP_VERSION}"})
        if r.ok:
            return parse_pricing_markdown(r.text)
    except Exception:
        pass
    return {}


def load_pricing_override() -> dict:
    """Optional pricing.json next to the app: {"haiku 5.5": {"input": 0.1, "output": 0.5}, …}"""
    try:
        if PRICING_OVERRIDE_PATH.exists():
            data = json.load(open(PRICING_OVERRIDE_PATH, encoding="utf-8"))
            return {k.lower().strip(): v for k, v in data.items() if isinstance(v, dict)}
    except Exception:
        pass
    return {}


def _cap(caps: dict, *path) -> bool:
    node = caps or {}
    for p in path:
        if not isinstance(node, dict):
            return False
        node = node.get(p)
    return bool(node)


def model_info_from_api(m) -> dict:
    """Normalise an SDK ModelInfo into the dict shape used by the app."""
    caps = getattr(m, "capabilities", None) or {}
    if hasattr(caps, "model_dump"):
        caps = caps.model_dump()
    thinking_off = None
    if _cap(caps, "thinking", "types", "disabled", "supported"):
        thinking_off = "disabled"
    elif _cap(caps, "effort", "low", "supported"):
        thinking_off = "effort"
    created = getattr(m, "created_at", None)
    return {
        "id":               m.id,
        "display_name":     getattr(m, "display_name", m.id),
        "created_at":       created.strftime("%Y-%m-%d") if hasattr(created, "strftime") else str(created or "")[:10],
        "max_input_tokens": getattr(m, "max_input_tokens", None),
        "max_tokens":       getattr(m, "max_tokens", None),
        "thinking_off":     thinking_off,
        "effort":           _cap(caps, "effort", "supported"),
        "structured":       _cap(caps, "structured_outputs", "supported") if "structured_outputs" in caps else True,
    }


def fetch_models(api_key: str) -> list:
    """Live model list from the API, newest first. Raises on failure."""
    client = _anthropic().Anthropic(api_key=api_key.strip(), max_retries=2, timeout=20)
    models = [model_info_from_api(m) for m in client.models.list(limit=100)]
    models = [m for m in models if model_family_key(m["id"])]      # Claude chat models only
    models.sort(key=lambda m: m["created_at"], reverse=True)
    return models


class Catalog:
    """Models + prices with offline cache in the config file."""

    def __init__(self, cfg: dict):
        mc = cfg.get("models_cache") or {}
        pc = cfg.get("pricing_cache") or {}
        self.models: list = mc.get("models") or list(_BUILTIN_MODELS)
        self.models_fetched_at: float = float(mc.get("fetched_at") or 0)
        self.models_source = "cache" if mc.get("models") else "built-in"
        self.prices: dict = pc.get("prices") or {}
        self.prices_fetched_at: float = float(pc.get("fetched_at") or 0)
        self.prices_source = "cache" if pc.get("prices") else "built-in"
        self.override = load_pricing_override()

    # ── refresh ──────────────────────────────────────────────────────
    def models_stale(self) -> bool:
        return time.time() - self.models_fetched_at > MODELS_TTL_S

    def prices_stale(self) -> bool:
        return time.time() - self.prices_fetched_at > PRICING_TTL_S

    def refresh_models(self, api_key: str) -> bool:
        if not api_key.strip():
            return False
        self.models = fetch_models(api_key)
        self.models_fetched_at = time.time()
        self.models_source = "live"
        save_config({"models_cache": {"models": self.models, "fetched_at": self.models_fetched_at}})
        return True

    def refresh_prices(self) -> bool:
        prices = fetch_official_prices()
        if not prices:
            return False
        self.prices = prices
        self.prices_fetched_at = time.time()
        self.prices_source = "live"
        save_config({"pricing_cache": {"prices": prices, "fetched_at": self.prices_fetched_at}})
        return True

    # ── lookups ──────────────────────────────────────────────────────
    def model(self, model_id: str) -> dict:
        for m in self.models:
            if m["id"] == model_id:
                return m
        for m in _BUILTIN_MODELS:
            if m["id"] == model_id:
                return m
        return {"id": model_id, "display_name": model_id, "created_at": "", "max_input_tokens": None,
                "max_tokens": None, "thinking_off": None, "effort": False, "structured": True}

    def has_model(self, model_id: str) -> bool:
        return any(m["id"] == model_id for m in self.models)

    def pick_default(self, preferred: str) -> str:
        if preferred and self.has_model(preferred):
            return preferred
        if self.has_model(DEFAULT_MODEL):
            return DEFAULT_MODEL
        return self.models[0]["id"] if self.models else DEFAULT_MODEL

    def price(self, model_id: str) -> dict:
        """{input, output, cache_read, cache_write, source}; None values if unknown."""
        key = model_family_key(model_id)
        for src, table in (("override", self.override), (self.prices_source, self.prices),
                           ("built-in", _BUILTIN_PRICES)):
            p = table.get(key)
            if p and p.get("input") is not None and p.get("output") is not None:
                out = {"input": float(p["input"]), "output": float(p["output"]),
                       "cache_read": float(p.get("cache_read", p["input"] * 0.1)),
                       "cache_write": float(p.get("cache_write", p["input"] * 1.25)),
                       "source": src}
                return out
        return {"input": None, "output": None, "cache_read": None, "cache_write": None, "source": "unknown"}

    def label(self, model_id: str) -> str:
        m, p = self.model(model_id), self.price(model_id)
        ctx = m.get("max_input_tokens")
        ctx_s = f"{ctx // 1000}K" if ctx and ctx < 1_000_000 else ("1M" if ctx else "?")
        price_s = (f"${p['input']:g} / ${p['output']:g}" if p["input"] is not None else "price unknown")
        tag = "   ★ recommended" if model_id == DEFAULT_MODEL else ("   (older)" if re.search(r"-\d{8}$", model_id) else "")
        return f"{m['display_name']}   ·   {price_s} per MTok   ·   {ctx_s} ctx{tag}"


# ═══════════════════════════════════════════════════════════════════════
# COST ESTIMATE & USAGE
# ═══════════════════════════════════════════════════════════════════════

_OUTPUT_RATIO = {"ja": 0.9, "zh": 0.8, "ko": 0.9, "ar": 1.0, "de": 1.1, "pt": 1.15,
                 "es": 1.15, "fr": 1.15, "it": 1.1, "en": 1.0}


class UsageTotals:
    """Thread-safe accumulator for API usage across batches."""

    def __init__(self):
        self.lock = threading.Lock()
        self.input = self.output = self.cache_read = self.cache_write = 0
        self.calls = 0

    def add(self, usage):
        if usage is None:
            return
        with self.lock:
            self.input       += int(getattr(usage, "input_tokens", 0) or 0)
            self.output      += int(getattr(usage, "output_tokens", 0) or 0)
            self.cache_read  += int(getattr(usage, "cache_read_input_tokens", 0) or 0)
            self.cache_write += int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
            self.calls += 1

    def cost(self, price: dict):
        if price.get("input") is None:
            return None
        return (self.input * price["input"] + self.output * price["output"]
                + self.cache_read * price["cache_read"] + self.cache_write * price["cache_write"]) / 1e6

    def summary(self, price: dict) -> str:
        c = self.cost(price)
        cost_s = f"${c:.4f}" if c is not None else "unknown price"
        return (f"{cost_s}  ({self.input:,} in · {self.output:,} out · "
                f"{self.cache_read:,} cached · {self.calls} calls)")


def estimate_cost(blocks: list, model_id: str, catalog: Catalog, *, api_key: str = "",
                  ctx_blocks: list = None, glossary: list = None, batch_size: int = 25,
                  translate_cues: bool = True, target_code: str = "pt-BR",
                  src_label: str = "English", tgt_label: str = "Portuguese",
                  exact: bool = False) -> dict:
    """
    Cost estimate. exact=True calls the free count_tokens endpoint for the
    input side (needs api_key); otherwise ~3.5 chars per token.
    """
    if not blocks:
        return {}
    glossary = glossary or []
    ctx_blocks = ctx_blocks or []
    n_batches = max(1, -(-len(blocks) // max(1, batch_size)))
    system = build_system_prompt(src_label, tgt_label, glossary)
    all_prompt, items = build_batch_prompt(blocks, translate_cues)
    n_lines = sum(len(needs) for _, needs, _, _ in items)
    ctx_script = "\n".join(l for b in ctx_blocks for l in b["text_lines"] if l.strip())

    method = "approx"
    if exact and api_key.strip():
        try:
            client = _anthropic().Anthropic(api_key=api_key.strip(), max_retries=1, timeout=30)

            def count(text):
                return client.messages.count_tokens(
                    model=model_id, messages=[{"role": "user", "content": text or "x"}]).input_tokens
            sys_tokens  = count(system)
            text_tokens = count(all_prompt)
            ctx_tokens  = count(ctx_script) if ctx_script else 0
            method = "exact"
        except Exception:
            exact = False
    if method == "approx":
        sys_tokens  = len(system) / 3.5
        text_tokens = len(all_prompt) / 3.5
        ctx_tokens  = len(ctx_script) / 3.5

    ratio = _OUTPUT_RATIO.get(target_code.split("-")[0].lower(), 1.1)
    input_tokens  = text_tokens + n_batches * (sys_tokens + 40) + ctx_tokens * 1.3
    output_tokens = text_tokens * ratio + n_lines * 7 + n_batches * 12

    price = catalog.price(model_id)
    if price["input"] is None:
        return {"input_tokens": int(input_tokens), "output_tokens": int(output_tokens),
                "total_cost": None, "method": method, "price": price}
    in_cost  = input_tokens / 1e6 * price["input"]
    out_cost = output_tokens / 1e6 * price["output"]
    return {"input_tokens": int(input_tokens), "output_tokens": int(output_tokens),
            "input_cost": in_cost, "output_cost": out_cost, "total_cost": in_cost + out_cost,
            "method": method, "price": price, "n_batches": n_batches}


# ═══════════════════════════════════════════════════════════════════════
# PROMPTS & TRANSLATION  (Claude)
# ═══════════════════════════════════════════════════════════════════════

_SYSTEM_PROMPT = """You are a professional subtitle translator. Translate from {src} to {tgt}.

Rules:
1. Translate EVERY line, including hearing-impaired cues such as [door slams], (laughs) or APPLAUSE. Keep the same bracket, parenthesis or ALL-CAPS style the cue had.
2. Each block is shown on screen at its own time, so translate each block using only the words of that block: never move words into the previous or next block. Each block has a fixed number of lines; return exactly that many lines, in order. You may rebalance wording between the lines of one block so each line reads naturally, but never merge lines, drop a line or add one.
3. Keep placeholders like {{T1}} exactly where they belong; they stand for formatting tags. {{Q}} stands for a double-quote character: keep {{Q}} where the quote belongs in the translation.
4. Do NOT translate or transliterate proper names of people, schools, universities, companies, institutions, brands and titles of works: keep them exactly as written. Countries, cities and nationalities use their normal {tgt} form.{glossary}
5. Natural, idiomatic {tgt}; preserve tone, register, humour, slang and profanity level. Keep numbers, dates and currency as written.
6. If a block is already in {tgt} or is a name/number only, return it unchanged.

Input: labelled blocks like
[k07]
line one
line two

Output: JSON only, of the form {{"blocks":[{{"k":"k07","lines":["…","…"]}}]}} with one entry per input block. Copy each label exactly as given (labels are not sequential and must never be invented or renumbered) and keep the line count of that block.
"""

_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "blocks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "k": {"type": "string"},
                    "lines": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["k", "lines"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["blocks"],
    "additionalProperties": False,
}

_NAMES_SCHEMA = {
    "type": "object",
    "properties": {"names": {"type": "array", "items": {"type": "string"}}},
    "required": ["names"],
    "additionalProperties": False,
}

CONTEXT_MARGIN_MS = 8000
CONTEXT_MAX_LINES = 150


def build_system_prompt(src_label: str, tgt_label: str, glossary: list) -> str:
    g = ""
    if glossary:
        g = "\n   Preserve exactly these terms: " + "; ".join(glossary)
    return _SYSTEM_PROMPT.format(src=src_label, tgt=tgt_label, glossary=g)


_KEY_ALPHA = "abcdefghjkmnpqrstuvwxyz"   # no i / l / o


def block_key(n: int) -> str:
    """Non-sequential label for the n-th block of a batch (unique for n < 69).
    Labels that cannot be produced by counting force the model to copy them,
    so a merged or dropped block becomes a missing key instead of a silent
    shift of every following block."""
    # 36n + 41 is never a multiple of 100, so the digits never equal n itself
    return f"{_KEY_ALPHA[n % len(_KEY_ALPHA)]}{(n * 37 + 41) % 100:02d}"


def build_batch_prompt(blocks: list, translate_cues: bool) -> tuple:
    """
    Returns (prompt_text, items). items = [(block_index, needs, tags_per_line, key)]
    where needs lists the line indexes sent for translation.
    """
    parts, items = [], []
    for i, block in enumerate(blocks):
        needs = [j for j, ln in enumerate(block["text_lines"]) if not is_passthrough(ln, translate_cues)]
        if not needs:
            continue
        protected, tags = [], {}
        for j in needs:
            core, t = protect_tags(block["text_lines"][j])
            protected.append(core.replace('"', "{Q}"))   # quotes as a placeholder: no JSON escaping needed
            tags[j] = t
        key = block_key(len(items) + 1)
        items.append((i, needs, tags, key))
        parts.append(f"[{key}]\n" + "\n".join(protected))
    return "\n\n".join(parts), items


def context_window_text(ctx_blocks: list, start_ms: int, end_ms: int,
                        frac_start: float = 0.0, frac_end: float = 1.0) -> str:
    """Context lines whose timing overlaps [start-margin, end+margin]; falls back to
    the proportional position in the file when timings do not overlap at all."""
    if not ctx_blocks:
        return ""
    lo, hi = start_ms - CONTEXT_MARGIN_MS, end_ms + CONTEXT_MARGIN_MS
    lines = []
    for b in ctx_blocks:
        s, e = b.get("_ms") or timestamp_ms(b["timestamp"])
        if e >= lo and s <= hi:
            lines.extend(l.strip() for l in b["text_lines"] if l.strip())
    if not lines:
        n = len(ctx_blocks)
        a = max(0, int(frac_start * n) - 5)
        z = min(n, int(frac_end * n) + 5)
        lines = [l.strip() for b in ctx_blocks[a:z] for l in b["text_lines"] if l.strip()]
    return "\n".join(lines[:CONTEXT_MAX_LINES])


def rewrap(lines: list, n: int) -> list:
    """Force a list of lines into exactly n lines, balancing by length."""
    text = " ".join(l.strip() for l in lines if l is not None).strip()
    text = re.sub(r"\s+", " ", text)
    if n <= 1:
        return [text]
    words = text.split(" ")
    if len(words) <= n:
        return words + [""] * (n - len(words))
    out, target = [], len(text) / n
    cur = ""
    for w in words:
        remaining = n - len(out) - 1
        if remaining > 0 and cur and len(cur) + 1 + len(w) > target and len(words) - words.index(w) >= remaining:
            out.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    out.append(cur)
    while len(out) < n:
        out.append("")
    while len(out) > n:
        last = out.pop()
        out[-1] = (out[-1] + " " + last).strip()
    return out


def _parse_json_blocks(raw: str) -> dict:
    """{key: [lines]} from the model text; tolerant of stray text around the JSON."""
    txt = raw.strip()
    try:
        data = json.loads(txt)
    except Exception:
        m = re.search(r"\{.*\}", txt, re.DOTALL)
        data = json.loads(m.group(0)) if m else {"blocks": []}
    out = {}
    for b in data.get("blocks", []):
        try:
            key = str(b.get("k", b.get("n", ""))).strip().strip("[]")
            out[key] = [str(x) for x in b.get("lines", [])]
        except Exception:
            continue
    return out


class BatchRefused(RuntimeError):
    pass


def _request_options(model_info: dict) -> dict:
    """Thinking/effort settings that keep translation cheap on every model."""
    opts = {}
    if model_info.get("thinking_off") == "disabled":
        opts["thinking"] = {"type": "disabled"}
    elif model_info.get("thinking_off") == "effort":
        opts.setdefault("output_config", {})["effort"] = "low"
    if model_info.get("structured", True):
        opts.setdefault("output_config", {})["format"] = {"type": "json_schema", "schema": _OUTPUT_SCHEMA}
    return opts


def claude_translate_batch(client, blocks: list, src_label: str, tgt_label: str,
                           model_info: dict, glossary: list, ctx_text: str,
                           translate_cues: bool, usage: UsageTotals, depth: int = 0) -> list:
    """
    Translate one batch. Returns new block dicts (same order). Lines that
    could not be translated keep the source text and are flagged with
    block["_untranslated"] = True so the QC pass can retry them.
    """
    results = [{**b, "text_lines": b["text_lines"][:]} for b in blocks]
    prompt, items = build_batch_prompt(blocks, translate_cues)
    if not items:
        return results

    system = build_system_prompt(src_label, tgt_label, glossary)
    user = ""
    if ctx_text:
        user += ("REFERENCE (same scene in another language; use only to understand "
                 "meaning, names and context; never copy it):\n---\n" + ctx_text + "\n---\n\n")
    user += "SUBTITLES:\n\n" + prompt

    max_out = min(int(model_info.get("max_tokens") or 16000), 16000)
    resp = client.messages.create(
        model=model_info["id"],
        max_tokens=max_out,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user}],
        **_request_options(model_info),
    )
    usage.add(resp.usage)

    if resp.stop_reason == "refusal":
        raise BatchRefused("the model declined this batch (safety filter)")
    if resp.stop_reason == "max_tokens":
        if len(blocks) > 1 and depth < 6:
            mid = len(blocks) // 2
            left  = claude_translate_batch(client, blocks[:mid], src_label, tgt_label, model_info,
                                           glossary, ctx_text, translate_cues, usage, depth + 1)
            right = claude_translate_batch(client, blocks[mid:], src_label, tgt_label, model_info,
                                           glossary, ctx_text, translate_cues, usage, depth + 1)
            return left + right
        raise RuntimeError("output cut off (max_tokens) even for a single block")

    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    parsed = _parse_json_blocks(text)

    missing = 0
    for idx, needs, tags, key in items:
        got = parsed.get(key)
        if not got or not any(g.strip() for g in got):
            missing += 1
            results[idx]["_untranslated"] = True
            continue
        if len(got) != len(needs):
            got = rewrap(got, len(needs))
        for k, j in enumerate(needs):
            results[idx]["text_lines"][j] = restore_tags(got[k].replace("{Q}", '"').strip(), tags[j])
    if missing and missing > len(items) // 2:
        raise RuntimeError(f"model returned {len(items) - missing}/{len(items)} blocks")
    return results


def extract_names(client, blocks: list, model_info: dict, src_label: str) -> tuple:
    """Ask the model for proper names found in the subtitles. Returns (names, usage)."""
    usage = UsageTotals()
    script = "\n".join(l.strip() for b in blocks for l in b["text_lines"] if l.strip())
    opts = {}
    if model_info.get("thinking_off") == "disabled":
        opts["thinking"] = {"type": "disabled"}
    elif model_info.get("thinking_off") == "effort":
        opts.setdefault("output_config", {})["effort"] = "low"
    if model_info.get("structured", True):
        opts.setdefault("output_config", {})["format"] = {"type": "json_schema", "schema": _NAMES_SCHEMA}
    resp = client.messages.create(
        model=model_info["id"], max_tokens=8000,
        system=(f"You extract proper names from {src_label} subtitles. Return a JSON object "
                '{"names": [...]} listing every distinct proper name that must stay untranslated '
                "in a subtitle translation: people (full names and surnames as they appear), "
                "companies, schools, universities, institutions, foundations, brands, product names, "
                "streets, venues and titles of works. Exclude countries, continents, nationalities, "
                "well-known cities and regions (they have a translated form), common nouns, job titles "
                "and generic words. "
                "Keep the original spelling and casing. Return JSON only."),
        messages=[{"role": "user", "content": script[:400_000]}],
        **opts,
    )
    usage.add(resp.usage)
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    try:
        data = json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        data = json.loads(m.group(0)) if m else {"names": []}
    names = parse_glossary("\n".join(str(x) for x in data.get("names", [])))
    return names, usage


# ═══════════════════════════════════════════════════════════════════════
# TRANSLATION  (MyMemory, free)
# ═══════════════════════════════════════════════════════════════════════

_MM_LANG = {"pt-BR": "pt", "pt-PT": "pt", "es-ES": "es", "es-LATAM": "es", "en-US": "en",
            "en-GB": "en", "de-DE": "de", "fr-FR": "fr", "it-IT": "it", "ja-JP": "ja",
            "ko-KR": "ko", "zh-CN": "zh-CN", "ar-AR": "ar"}


def translate_free(text_lines: list, source_lang: str, target_lang: str,
                   translate_cues: bool = True) -> list:
    requests = _requests()
    src = _MM_LANG.get(source_lang, source_lang.split("-")[0].lower()[:2])
    tgt = _MM_LANG.get(target_lang, target_lang.split("-")[0].lower()[:2])
    results = []
    for line in text_lines:
        if is_passthrough(line, translate_cues):
            results.append(line)
            continue
        core, tags = protect_tags(line)
        try:
            url = (f"https://api.mymemory.translated.net/get"
                   f"?q={requests.utils.quote(core)}&langpair={src}|{tgt}")
            data = requests.get(url, timeout=10).json()
            out = data["responseData"]["translatedText"] if data.get("responseStatus") == 200 else core
        except Exception:
            out = core
        results.append(restore_tags(out, tags))
    return results


# ═══════════════════════════════════════════════════════════════════════
# QUALITY CONTROL
# ═══════════════════════════════════════════════════════════════════════

def _norm(text: str) -> str:
    return re.sub(r"[^\w]+", " ", _TAG_RE.sub("", text).lower()).strip()


def _word_count(text: str) -> int:
    return len([w for w in re.findall(r"[^\W\d_]{2,}", _TAG_RE.sub("", text))])


def qc_block(src: dict, out: dict, glossary: list, translate_cues: bool) -> list:
    """Issues for one block: list of (kind, detail)."""
    issues = []
    s_lines, o_lines = src["text_lines"], out["text_lines"]
    if len(s_lines) != len(o_lines):
        issues.append(("line_count", f"{len(s_lines)} → {len(o_lines)} lines"))
    translatable = [l for l in s_lines if not is_passthrough(l, translate_cues)]
    if translatable:
        s_text, o_text = " ".join(s_lines), " ".join(o_lines)
        if out.get("_untranslated"):
            issues.append(("untranslated", "no translation returned"))
        elif _norm(s_text) == _norm(o_text) and _word_count(s_text) >= 3:
            issues.append(("unchanged", "text identical to source"))
        for j, (a, b) in enumerate(zip(s_lines, o_lines)):
            if a.strip() and not is_passthrough(a, translate_cues) and not b.strip():
                issues.append(("empty_line", f"line {j + 1} empty"))
        if re.search(r"\{T\d+\}", o_text):
            issues.append(("placeholder", "tag placeholder left in text"))
        miss = glossary_violations(s_text, o_text, glossary)
        if miss:
            issues.append(("name", "missing: " + ", ".join(miss)))
        years = [y for y in re.findall(r"\b(1[89]\d\d|20\d\d)\b", s_text) if y not in o_text]
        if years:
            issues.append(("number", "missing: " + ", ".join(years)))
    return issues


def qc_report(source_blocks: list, out_blocks: list, glossary: list, translate_cues: bool) -> list:
    """[(index, kind, detail)] for every block with a problem."""
    report = []
    for i, (s, o) in enumerate(zip(source_blocks, out_blocks)):
        for kind, detail in qc_block(s, o, glossary, translate_cues):
            report.append((i, kind, detail))
    return report


# ═══════════════════════════════════════════════════════════════════════
# LANGUAGE LISTS & OPTIONS
# ═══════════════════════════════════════════════════════════════════════

LANGUAGES = [
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
_LANG_LABEL = {code: label for code, label, _ in LANGUAGES}

BATCH_OPTIONS  = [(10, "10  — Conservative"), (25, "25  — Recommended"), (40, "40  — Fast"), (50, "50  — Max throughput")]
WORKER_OPTIONS = [(1, "1  — Safe / sequential"), (3, "3  — Moderate"), (5, "5  — Recommended"), (8, "8  — High-rate plan only")]
SAMPLE_BLOCKS  = 20


# ═══════════════════════════════════════════════════════════════════════
# HELP TEXT
# ═══════════════════════════════════════════════════════════════════════

HELP_TEXT = f"""\
{APP_TITLE}
Structure-preserving subtitle translation for .srt files.

WHAT IT DOES
------------
Loads a .srt subtitle file, translates every dialogue block into
the chosen language, and saves a new .srt with identical structure:
block IDs, timestamps and line counts are preserved.

NEW IN v0.8.0
-------------
One screen    FILE, LANGUAGES and ENGINE are the three things you
              set for every run. Batch size, workers, cues and the
              output-folder rule live under "Advanced". The cost
              estimate and the Start / Sample / Cancel buttons stay
              at the bottom of the column.

Settings (⚙)  API key, model and price catalog refresh, file paths.

Names tab     The preserve-names list moved to the right panel with
              full height, Auto-detect, Load from file, Save next to
              SRT and Clear. The tab title shows the count.

Tooltips      Hover any control for a short explanation. The status
              line at the bottom tells you the next step.

NEW IN v0.7.0
-------------
Live models    The Claude model list is read from the API (newest
               first) and cached for offline use. Click ↻ to refresh.

Live pricing   Prices come from Anthropic's published pricing page,
               refreshed once a day. A pricing.json file next to the
               app overrides them; a built-in table is the fallback.

Exact estimate The ↻ button on the cost panel counts the real input
               tokens with the free count_tokens endpoint. The real
               cost of each run is reported from the API usage.

Cues           [door slams], (laughs) and APPLAUSE lines are now
               translated, keeping their style. Untick "Translate
               hearing-impaired cues" to leave them as they are.

Quality control Each block is checked after the run: unchanged text,
               missing lines, lost tags and missing names are flagged.
               Unchanged blocks are retranslated once automatically.
               The QC report appears in the Activity Log and flagged
               blocks are highlighted in the Comparison tab.

Preserve names Names tab: one per line (people, schools, companies,
               brands). "Auto-detect" asks Claude to list them from
               the file for you to review. A <file>.names.txt next to
               the subtitle is loaded automatically and can be saved
               with "Save next to SRT".

Context file   Only the context lines around each batch (by timestamp)
               are sent, so the extra cost is small.

Sample run     Translates the first {SAMPLE_BLOCKS} blocks only, without saving,
               and shows the result and its real cost.

Output name    Movie.en.srt → Movie.pt-BR.srt (source tag removed).

TRANSLATION ENGINES
-------------------
Claude API (recommended)
  Requires an API key from console.anthropic.com. Understands tone,
  humour, slang and context. Supports context files, name
  preservation and quality control.

MyMemory (free)
  No key required. Literal, less nuanced. Good for testing.

API KEY
-------
Stored locally in ~/.srt_translator_config.json. Sent only to
api.anthropic.com. Set the ANTHROPIC_API_KEY environment variable
as an alternative.

BATCH SIZE & WORKERS
--------------------
Batch size = blocks per API call (auto-suggested from line length).
Workers = simultaneous API calls. Higher is faster but can hit
rate limits; the app retries automatically.

RIGHT-PANEL TABS
----------------
Source Preview   First 50 blocks, verify parse before starting.
Names            Terms that must stay untranslated (see above).
Comparison       Original vs translated, QC-flagged blocks in colour.
Activity Log     Batch progress, QC report, real cost.
"""


ENGINE_HELP_TEXT = """\
TRANSLATION ENGINES
-------------------
The app can translate with two different services. Pick one with
the ENGINE toggle. Everything else (file loading, structure checks,
output naming) works the same way for both.

CLAUDE API  (recommended)
-------------------------
What it is   Anthropic's Claude language models, called through
             your own API key from console.anthropic.com.

How it works The subtitle is cut into batches of blocks (section
             "Batch size"). Each batch is sent with instructions
             about tone, names and line structure; several batches
             run at the same time ("Parallel workers"). The reply
             is checked block by block, anything missing or
             unchanged is sent again, and the real cost is reported.

Quality      Understands context, humour, slang, register and
             hearing-impaired cues. Keeps names from the Preserve
             list. Can use a context file in another language.

Cost         Pay per token. The estimate panel shows the price
             before you start; a 90-minute film costs a few cents
             with Haiku 5.5 and well under a dollar with the
             larger models. Prices come from Anthropic's pricing
             page and are refreshed daily.

Needs        An API key (⚙ Settings) and an internet connection.
             The key is stored only on this computer.

MYMEMORY  (free)
----------------
What it is   A public translation-memory service
             (mymemory.translated.net) with a free web API.

How it works Each subtitle line is sent on its own, one at a
             time, with no context from the lines around it.
             Lines that fail are kept in the original language.

Quality      Literal, phrase-by-phrase. Good for a quick test or
             for very simple dialogue; names, jokes and idioms
             are often translated word for word.

Cost         Free, no key. The service limits anonymous use to a
             few thousand characters per day, so long films may
             stop part-way; wait a day or use Claude.

Limits       No context file, no name preservation, no quality-
             control repair pass, slower (one request per line).

WHICH ONE?
----------
Use Claude for anything you will actually watch. Use MyMemory to
try the app without an account or to check that a file parses.
"""


# ═══════════════════════════════════════════════════════════════════════
# DRAG-AND-DROP HELPER
# ═══════════════════════════════════════════════════════════════════════

def _try_enable_dnd(widget, callback, on_enter=None, on_leave=None) -> bool:
    try:
        import tkinterdnd2 as dnd  # type: ignore
        # Load the tkdnd Tcl package into this interpreter. A plain tk.Tk() root never
        # does it, so without this call drop_target_register fails and DnD stays off.
        dnd.TkinterDnD.require(widget.winfo_toplevel())
        widget.drop_target_register(dnd.DND_FILES)
        widget.dnd_bind("<<Drop>>", lambda e: callback(_clean_dnd_path(e.data)))
        if on_enter:
            widget.dnd_bind("<<DragEnter>>", lambda e: on_enter())
        if on_leave:
            widget.dnd_bind("<<DragLeave>>", lambda e: on_leave())
        return True
    except Exception:
        return False


def _clean_dnd_path(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("{") and raw.endswith("}"):
        raw = raw[1:-1]
    if raw.startswith("file:///"):
        from urllib.parse import unquote
        raw = unquote(raw[8:])
        if not re.match(r"^[A-Za-z]:", raw):
            raw = "/" + raw
    return raw


# ═══════════════════════════════════════════════════════════════════════
# SMALL UI HELPERS  (v0.8.0)
# ═══════════════════════════════════════════════════════════════════════

class Tooltip:
    """Hover tooltip: appears after a short delay, disappears on leave or click."""

    def __init__(self, widget, text, delay_ms=550):
        self.widget, self.text, self.delay = widget, text, delay_ms
        self._after = None
        self._tip = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _e=None):
        self._cancel()
        self._after = self.widget.after(self.delay, self._show)

    def _cancel(self):
        if self._after:
            try:
                self.widget.after_cancel(self._after)
            except Exception:
                pass
            self._after = None

    def _show(self):
        if self._tip or not self.text:
            return
        try:
            x = self.widget.winfo_rootx() + 12
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        except Exception:
            return
        tip = tk.Toplevel(self.widget)
        tip.wm_overrideredirect(True)
        tip.attributes("-topmost", True)
        tk.Label(tip, text=self.text, font=FONTS["tiny"], fg=COLORS["text_bright"],
                 bg="#2a3550", padx=8, pady=5, justify="left", wraplength=320,
                 highlightbackground=COLORS["accent"], highlightthickness=1).pack()
        tip.wm_geometry(f"+{x}+{y}")
        self._tip = tip

    def _hide(self, _e=None):
        self._cancel()
        if self._tip:
            try:
                self._tip.destroy()
            except Exception:
                pass
            self._tip = None


def _no_wheel(widget):
    """Stop the mouse wheel from changing a combobox/spinbox while the column scrolls."""
    widget.bind("<MouseWheel>", lambda e: "break")


# ═══════════════════════════════════════════════════════════════════════
# MAIN APP
# ═══════════════════════════════════════════════════════════════════════

_GEOMETRY_RE = re.compile(r"^(\d{3,4})x(\d{3,4})([+-]\d+)([+-]\d+)$")
LEFT_WIDTH = 440


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        cfg = load_config()
        geo = cfg.get("window_geometry", "")
        self.geometry(geo if _GEOMETRY_RE.match(geo or "") else "1000x700")
        self.minsize(900, 620)
        self.configure(bg=COLORS["bg_dark"])

        self.catalog = Catalog(cfg)

        # State
        self.source_blocks     = []
        self.translated_blocks = []
        self.context_blocks    = []
        self.qc_issues         = []
        self.input_path        = ""
        self.context_path      = ""
        self.output_path       = ""
        self._last_output_dir  = cfg.get("last_output_dir", "")
        self._api_key          = cfg.get("api_key") or os.environ.get("ANTHROPIC_API_KEY", "")
        self._settings_dlg     = None

        # Vars
        self.source_lang    = tk.StringVar(value=cfg.get("source_lang", "en-US"))
        self.target_lang    = tk.StringVar(value=cfg.get("target_lang", "pt-BR"))
        self.engine         = tk.StringVar(value=cfg.get("engine", "claude"))
        self.claude_model   = tk.StringVar(value=self.catalog.pick_default(cfg.get("claude_model", "")))
        self.same_folder    = tk.BooleanVar(value=cfg.get("same_folder", False))
        self.translate_cues = tk.BooleanVar(value=cfg.get("translate_cues", True))
        self.advanced_open  = tk.BooleanVar(value=cfg.get("advanced_open", False))
        self.batch_size     = tk.IntVar(value=int(cfg.get("batch_size", 25)))
        self.workers        = tk.IntVar(value=int(cfg.get("workers", 5)))
        self.progress_var   = tk.DoubleVar(value=0)
        self.status_text    = tk.StringVar(value="Load a .srt file to begin")
        self._catalog_status = tk.StringVar(value="")
        self._names_count   = tk.StringVar(value="0 names")
        self.is_translating = False
        self.cancel_flag    = False
        self._initial_glossary = cfg.get("glossary", "")

        self._ui_queue = queue.Queue()
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(40, self._drain_ui_queue)

        self.claude_model.trace_add("write", lambda *_: self._refresh_cost())
        self.target_lang.trace_add("write", lambda *_: (self._update_file_info(), self._refresh_cost()))
        self.translate_cues.trace_add("write", lambda *_: (self._update_adv_summary(), self._refresh_cost()))
        self.batch_size.trace_add("write", lambda *_: (self._update_adv_summary(), self._refresh_cost()))
        self.workers.trace_add("write", lambda *_: self._update_adv_summary())
        self.same_folder.trace_add("write", lambda *_: self._update_adv_summary())
        self.engine.trace_add("write", self._on_engine_change)
        self._on_engine_change()
        self._update_adv_summary()
        self._update_names_count()

        self.after(300, self._startup_refresh)

    # ── Cross-thread UI updates ──────────────────────────────────────

    def _post(self, fn):
        """Run fn on the Tk main thread (safe to call from worker threads)."""
        self._ui_queue.put(fn)

    def _drain_ui_queue(self):
        try:
            while True:
                fn = self._ui_queue.get_nowait()
                try:
                    fn()
                except Exception:
                    pass
        except queue.Empty:
            pass
        try:
            self.after(40, self._drain_ui_queue)
        except tk.TclError:
            pass

    # ── Lifecycle ────────────────────────────────────────────────────

    def _int(self, var, default, lo, hi) -> int:
        """Safe read of an IntVar bound to a spinbox (empty/invalid text → default)."""
        try:
            v = int(var.get())
        except (tk.TclError, ValueError):
            return default
        return max(lo, min(hi, v))

    def _on_close(self):
        save_config({
            "api_key":         self._api_key,
            "claude_model":    self.claude_model.get(),
            "source_lang":     self.source_lang.get(),
            "target_lang":     self.target_lang.get(),
            "engine":          self.engine.get(),
            "batch_size":      self._int(self.batch_size, 25, 5, 60),
            "workers":         self._int(self.workers, 5, 1, 8),
            "same_folder":     self.same_folder.get(),
            "translate_cues":  self.translate_cues.get(),
            "advanced_open":   self.advanced_open.get(),
            "last_output_dir": self._last_output_dir,
            "glossary":        self._glossary_text(),
            "window_geometry": self.winfo_geometry(),
        })
        self.destroy()

    def _startup_refresh(self):
        self._log(f"Models: {len(self.catalog.models)} ({self.catalog.models_source})  •  "
                  f"Prices: {self.catalog.prices_source}"
                  + ("  •  pricing.json override active" if self.catalog.override else ""), "info")
        if self.catalog.override:
            self._log(f"Price override file: {PRICING_OVERRIDE_PATH}", "info")
        if self.catalog.prices_stale() or (self.catalog.models_stale() and self._api_key.strip()):
            self._refresh_catalog(force=False)

    # ── UI build ─────────────────────────────────────────────────────

    def _build_ui(self):
        self._style()
        hdr = tk.Frame(self, bg=COLORS["bg_mid"], height=50)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text=f"◈  {APP_TITLE}", font=FONTS["title"], fg=COLORS["accent"],
                 bg=COLORS["bg_mid"], padx=18).pack(side="left", pady=9)
        self._flat_btn(hdr, "?  Help", self._show_help, dim=True).pack(side="right", padx=(6, 16), pady=9)
        b = self._flat_btn(hdr, "⚙  Settings", self._show_settings, dim=True)
        b.pack(side="right", pady=9)
        Tooltip(b, "API key, model and price catalog, file locations")

        body = tk.Frame(self, bg=COLORS["bg_dark"])
        body.pack(fill="both", expand=True, padx=14, pady=(10, 6))

        left = tk.Frame(body, bg=COLORS["bg_card"], width=LEFT_WIDTH,
                        highlightbackground=COLORS["border"], highlightthickness=1)
        left.pack(side="left", fill="y", padx=(0, 10))
        left.pack_propagate(False)
        self._build_left(left)

        right = tk.Frame(body, bg=COLORS["bg_dark"])
        right.pack(side="left", fill="both", expand=True)
        self._build_right(right)

        ftr = tk.Frame(self, bg=COLORS["bg_mid"], height=30)
        ftr.pack(fill="x", side="bottom")
        ftr.pack_propagate(False)
        tk.Label(ftr, textvariable=self.status_text, font=FONTS["tiny"], fg=COLORS["text_dim"],
                 bg=COLORS["bg_mid"], anchor="w", padx=16).pack(side="left", fill="x", expand=True)

    def _style(self):
        style = ttk.Style()
        style.theme_use("default")
        style.configure("Lang.TCombobox", fieldbackground=COLORS["bg_input"], background=COLORS["bg_input"],
                        foreground=COLORS["text"], selectbackground=COLORS["accent"],
                        selectforeground=COLORS["text_bright"], arrowcolor=COLORS["accent"],
                        bordercolor=COLORS["border"], lightcolor=COLORS["border"], darkcolor=COLORS["border"])
        style.map("Lang.TCombobox", fieldbackground=[("readonly", COLORS["bg_input"]), ("disabled", COLORS["bg_mid"])],
                  foreground=[("readonly", COLORS["text"]), ("disabled", COLORS["text_dim"])])
        style.configure("T.TNotebook", background=COLORS["bg_dark"], borderwidth=0)
        style.configure("T.TNotebook.Tab", background=COLORS["bg_mid"], foreground=COLORS["text_dim"],
                        padding=[14, 7], font=FONTS["small"], borderwidth=0)
        style.map("T.TNotebook.Tab", background=[("selected", COLORS["bg_card"])],
                  foreground=[("selected", COLORS["text_bright"])])
        style.configure("P.Horizontal.TProgressbar", troughcolor=COLORS["bg_dark"],
                        background=COLORS["accent"], borderwidth=0, thickness=6)
        style.configure("L.Vertical.TScrollbar", background=COLORS["bg_mid"], troughcolor=COLORS["bg_card"],
                        arrowcolor=COLORS["text_dim"], bordercolor=COLORS["bg_card"])

    def _flat_btn(self, parent, text, cmd, primary=False, danger=False, dim=False, font=None, **kw):
        bg = COLORS["btn_primary"] if primary else COLORS["btn_danger"] if danger else COLORS["bg_input"]
        fg = "#ffffff" if (primary or danger) else COLORS["text_dim"] if dim else COLORS["text"]
        return tk.Button(parent, text=text, font=font or FONTS["small"], bg=bg, fg=fg, relief="flat",
                         activebackground=COLORS["btn_hover"] if primary else COLORS["border"],
                         activeforeground=COLORS["text_bright"], cursor="hand2",
                         padx=kw.pop("padx", 12), pady=kw.pop("pady", 4), command=cmd, **kw)

    def _heading(self, parent, text, right_widget_factory=None):
        fr = tk.Frame(parent, bg=COLORS["bg_card"])
        fr.pack(fill="x", padx=14, pady=(6, 2))
        tk.Label(fr, text=text, font=FONTS["badge"], fg=COLORS["accent"], bg=COLORS["bg_card"],
                 anchor="w").pack(side="left")
        if right_widget_factory:
            right_widget_factory(fr).pack(side="right")
        return fr

    # ── Left column ──────────────────────────────────────────────────

    def _build_left(self, parent):
        # Action bar first (bottom, always visible), then a scrollable area for the form
        self._build_action_bar(parent)

        canvas = tk.Canvas(parent, bg=COLORS["bg_card"], highlightthickness=0)
        sb = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview, style="L.Vertical.TScrollbar")
        form = tk.Frame(canvas, bg=COLORS["bg_card"])
        win = canvas.create_window((0, 0), window=form, anchor="nw", width=LEFT_WIDTH - 2)

        def _resize(_e=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
            need = form.winfo_reqheight() > canvas.winfo_height()
            if need and not sb.winfo_ismapped():
                sb.pack(side="right", fill="y")
                canvas.itemconfigure(win, width=LEFT_WIDTH - 2 - sb.winfo_reqwidth())
            elif not need and sb.winfo_ismapped():
                sb.pack_forget()
                canvas.itemconfigure(win, width=LEFT_WIDTH - 2)
                canvas.yview_moveto(0)
        form.bind("<Configure>", _resize)
        canvas.bind("<Configure>", _resize)
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)

        def _wheel(e):
            if sb.winfo_ismapped():
                canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _wheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))
        self._form = form

        self._build_file_section(form)
        self._build_language_section(form)
        self._build_engine_section(form)
        self._build_advanced_section(form)

    # FILE ────────────────────────────────────────────────────────────
    def _build_file_section(self, f):
        self._heading(f, "FILE")
        self._src_drop = tk.Frame(f, bg=COLORS["bg_input"], highlightbackground=COLORS["border"],
                                  highlightthickness=1, cursor="hand2")
        self._src_drop.pack(fill="x", padx=14)
        inner = tk.Frame(self._src_drop, bg=COLORS["bg_input"])
        inner.pack(fill="x", padx=10, pady=5)
        self.file_label = tk.Label(inner, text="Drop a .srt here  or  Browse…", font=FONTS["small"],
                                   fg=COLORS["text_dim"], bg=COLORS["bg_input"], anchor="w", cursor="hand2")
        self.file_label.pack(side="left", fill="x", expand=True)
        self._flat_btn(inner, "Browse…", self._browse, pady=3).pack(side="right")
        for w in (self._src_drop, self.file_label):
            w.bind("<Button-1>", lambda e: self._browse())
        _try_enable_dnd(self._src_drop, self._load_source_file,
                        on_enter=lambda: self._src_drop.configure(highlightbackground=COLORS["accent"], bg=COLORS["drop_active"]),
                        on_leave=lambda: self._src_drop.configure(highlightbackground=COLORS["border"], bg=COLORS["bg_input"]))
        Tooltip(self._src_drop, "The subtitle to translate. Drag a .srt file here or click to browse.\n"
                                "Block IDs, timestamps and line counts are never changed.")

        self.file_info = tk.Label(f, text="", font=FONTS["tiny"], fg=COLORS["text_dim"], bg=COLORS["bg_card"],
                                  anchor="w", justify="left", wraplength=LEFT_WIDTH - 30)
        self.file_info.pack(fill="x", padx=14, pady=(2, 0))

        # Context row
        row = tk.Frame(f, bg=COLORS["bg_card"])
        row.pack(fill="x", padx=14, pady=(3, 0))
        self._ctx_row = row
        self._ctx_label = tk.Label(row, text="Context: none", font=FONTS["tiny"], fg=COLORS["text_dim"],
                                   bg=COLORS["bg_card"], anchor="w")
        self._ctx_label.pack(side="left", fill="x", expand=True)
        self._ctx_clear_btn = self._flat_btn(row, "✕", self._clear_context, dim=True, font=FONTS["tiny"], padx=6, pady=1)
        self._ctx_add_btn = self._flat_btn(row, "+ add", self._browse_context, dim=True, font=FONTS["tiny"], padx=8, pady=1)
        self._ctx_add_btn.pack(side="right")
        _try_enable_dnd(row, self._load_context_file)
        Tooltip(row, "Optional, Claude only: the same film in another language. Only the lines\n"
                     "around each batch (by timestamp) are sent, so the extra cost is small.")

    # LANGUAGES ───────────────────────────────────────────────────────
    def _build_language_section(self, f):
        self._heading(f, "LANGUAGES")
        row = tk.Frame(f, bg=COLORS["bg_card"])
        row.pack(fill="x", padx=14)
        row.columnconfigure(0, weight=1)
        row.columnconfigure(2, weight=1)
        self._src_combo, self._src_codes, self._src_combo_var = self._make_dropdown(row, self.source_lang)
        self._src_combo.grid(row=0, column=0, sticky="ew", ipady=3)
        swap = self._flat_btn(row, "⇄", self._swap_languages, dim=True, font=FONTS["body"], padx=8, pady=2)
        swap.grid(row=0, column=1, padx=6)
        Tooltip(swap, "Swap source and target language")
        self._tgt_combo, self._tgt_codes, self._tgt_combo_var = self._make_dropdown(row, self.target_lang)
        self._tgt_combo.grid(row=0, column=2, sticky="ew", ipady=3)
        Tooltip(self._src_combo, "Source language, detected from the file. Adjust if wrong.")
        Tooltip(self._tgt_combo, "Target language. Remembered between sessions.")

    def _make_dropdown(self, parent, textvariable):
        values = [f"{flag}  {label}" for _, label, flag in LANGUAGES]
        codes  = [code for code, _, _ in LANGUAGES]
        try:
            cur_idx = codes.index(textvariable.get())
        except ValueError:
            cur_idx = 0
        combo_var = tk.StringVar(value=values[cur_idx])
        combo = ttk.Combobox(parent, textvariable=combo_var, values=values, state="readonly",
                             style="Lang.TCombobox", font=FONTS["small"])
        _no_wheel(combo)

        def _on_select(event=None):
            idx = combo.current()
            if idx >= 0:
                textvariable.set(codes[idx])
        combo.bind("<<ComboboxSelected>>", _on_select)
        return combo, codes, combo_var

    def _set_combo(self, combo, codes, var, code):
        try:
            combo.current(codes.index(code))
            var.set(code)
        except (ValueError, AttributeError):
            pass

    def _set_src_combo(self, code):
        self._set_combo(self._src_combo, self._src_codes, self.source_lang, code)

    def _swap_languages(self):
        s, t = self.source_lang.get(), self.target_lang.get()
        self._set_combo(self._src_combo, self._src_codes, self.source_lang, t)
        self._set_combo(self._tgt_combo, self._tgt_codes, self.target_lang, s)

    # ENGINE ──────────────────────────────────────────────────────────
    def _build_engine_section(self, f):
        self._heading(f, "ENGINE", lambda fr: tk.Button(
            fr, text="?", font=FONTS["badge"], fg=COLORS["accent"], bg="#1a2744",
            activebackground=COLORS["border"], activeforeground=COLORS["text_bright"],
            relief="flat", cursor="hand2", padx=7, pady=0, command=self._show_engine_help))
        row = tk.Frame(f, bg=COLORS["bg_card"])
        row.pack(fill="x", padx=14)
        seg = tk.Frame(row, bg=COLORS["border"], highlightthickness=0)
        seg.pack(side="left")
        self._eng_btns = {}
        for value, text in (("claude", "Claude API ★"), ("free", "MyMemory (free)")):
            b = tk.Button(seg, text=text, font=FONTS["small"], relief="flat", cursor="hand2",
                          padx=10, pady=4, bd=0, command=lambda v=value: self.engine.set(v))
            b.pack(side="left", padx=1, pady=1)
            self._eng_btns[value] = b
        Tooltip(seg, "Claude API: best quality, needs your API key (Settings).\n"
                     "MyMemory: free, literal, no key, limited daily volume.")

        mrow = tk.Frame(f, bg=COLORS["bg_card"])
        mrow.pack(fill="x", padx=14, pady=(4, 0))
        self._model_combo_var = tk.StringVar()
        self._model_combo = ttk.Combobox(mrow, textvariable=self._model_combo_var, state="readonly",
                                         style="Lang.TCombobox", font=FONTS["tiny"])
        self._model_combo.pack(side="left", fill="x", expand=True, ipady=3)
        self._model_combo.bind("<<ComboboxSelected>>", self._on_model_selected)
        _no_wheel(self._model_combo)
        self._model_refresh_btn = self._flat_btn(mrow, "⟳", lambda: self._refresh_catalog(force=True), dim=True,
                                                 font=FONTS["small"], padx=8, pady=2)
        self._model_refresh_btn.pack(side="right", padx=(6, 0))
        Tooltip(self._model_combo, "Claude model. ★ marks the cheapest current model.\nPrice per million tokens, in / out.")
        Tooltip(self._model_refresh_btn, "Re-read the model list from the API and the prices from anthropic.com")
        self._fill_model_combo()

    # ADVANCED ────────────────────────────────────────────────────────
    def _build_advanced_section(self, f):
        hdr = tk.Frame(f, bg=COLORS["bg_card"])
        hdr.pack(fill="x", padx=14, pady=(6, 2))
        self._adv_btn = tk.Button(hdr, text="▸ Advanced", font=FONTS["badge"], fg=COLORS["accent"],
                                  bg=COLORS["bg_card"], activebackground=COLORS["bg_card"],
                                  activeforeground=COLORS["text_bright"], relief="flat", cursor="hand2",
                                  anchor="w", padx=0, command=self._toggle_advanced)
        self._adv_btn.pack(side="left")
        self._adv_summary = tk.Label(hdr, text="", font=FONTS["tiny"], fg=COLORS["text_dim"], bg=COLORS["bg_card"], anchor="w")
        self._adv_summary.pack(side="left", padx=(8, 0))

        self._adv_body = tk.Frame(f, bg=COLORS["bg_card"])
        b = self._adv_body
        r1 = tk.Frame(b, bg=COLORS["bg_card"])
        r1.pack(fill="x", padx=14, pady=(0, 2))

        def spin(parent, var, lo, hi, inc):
            s = tk.Spinbox(parent, from_=lo, to=hi, increment=inc, textvariable=var, width=4,
                           font=FONTS["small"], bg=COLORS["bg_input"], fg=COLORS["text"],
                           buttonbackground=COLORS["bg_mid"], insertbackground=COLORS["text"], relief="flat",
                           highlightbackground=COLORS["border"], highlightthickness=1)
            _no_wheel(s)
            return s
        tk.Label(r1, text="Batch size", font=FONTS["tiny"], fg=COLORS["text"], bg=COLORS["bg_card"]).pack(side="left")
        sp1 = spin(r1, self.batch_size, 5, 60, 5); sp1.pack(side="left", padx=(6, 18))
        tk.Label(r1, text="Workers", font=FONTS["tiny"], fg=COLORS["text"], bg=COLORS["bg_card"]).pack(side="left")
        sp2 = spin(r1, self.workers, 1, 8, 1); sp2.pack(side="left", padx=(6, 0))
        Tooltip(sp1, "Blocks per API call (5–60). Suggested automatically from the average line length.")
        Tooltip(sp2, "Simultaneous API calls (1–8). More is faster but can hit rate limits; the app retries.")

        def check(text, var, tip):
            c = tk.Checkbutton(b, text=text, variable=var, font=FONTS["tiny"], fg=COLORS["text"],
                               bg=COLORS["bg_card"], selectcolor=COLORS["bg_input"],
                               activebackground=COLORS["bg_card"], anchor="w", cursor="hand2", pady=0)
            c.pack(fill="x", padx=14)
            Tooltip(c, tip)
            return c
        check("Translate hearing-impaired cues  [door slams]  (laughs)  APPLAUSE", self.translate_cues,
              "Cue lines are translated and keep their bracket or capital style. Untick to leave them as they are.")
        check("Save next to the source file (skip the Save dialog)", self.same_folder,
              "Output name: source name without its language tag + target code, e.g. Movie.pt-BR.srt.\n"
              "Unticked: a Save dialog opens in the last folder you used (shown in Settings).")
        self._last_dir_var = tk.StringVar(value=self._last_dir_display())
        if self.advanced_open.get():
            self._adv_body.pack(fill="x")
            self._adv_btn.configure(text="▾ Advanced")

    def _toggle_advanced(self):
        if self.advanced_open.get():
            self._adv_body.pack_forget()
            self.advanced_open.set(False)
            self._adv_btn.configure(text="▸ Advanced")
        else:
            self._adv_body.pack(fill="x")
            self.advanced_open.set(True)
            self._adv_btn.configure(text="▾ Advanced")

    def _update_adv_summary(self):
        if not hasattr(self, "_adv_summary"):
            return
        self._adv_summary.configure(
            text=f"batch {self._int(self.batch_size, 25, 5, 60)} · workers {self._int(self.workers, 5, 1, 8)} · "
                 f"cues {'on' if self.translate_cues.get() else 'off'} · "
                 f"{'same folder' if self.same_folder.get() else 'ask where to save'}")

    def _last_dir_display(self) -> str:
        d = self._last_output_dir
        return "Last output folder: " + (d if d else "(none yet)")

    # ACTION BAR ──────────────────────────────────────────────────────
    def _build_action_bar(self, parent):
        bar = tk.Frame(parent, bg=COLORS["bg_card"], highlightbackground=COLORS["border"], highlightthickness=1)
        bar.pack(side="bottom", fill="x")
        cost = tk.Frame(bar, bg=COLORS["key_bg"])
        cost.pack(fill="x")
        top = tk.Frame(cost, bg=COLORS["key_bg"])
        top.pack(fill="x", padx=12, pady=(5, 0))
        tk.Label(top, text="ESTIMATED COST", font=FONTS["badge"], fg=COLORS["accent"], bg=COLORS["key_bg"]).pack(side="left")
        self._cost_main = tk.Label(top, text="—", font=("Consolas", 12, "bold"), fg=COLORS["text_dim"],
                                   bg=COLORS["key_bg"], anchor="w")
        self._cost_main.pack(side="left", padx=(10, 0))
        self._cost_method = tk.Label(top, text="", font=FONTS["tiny"], fg=COLORS["text_dim"], bg=COLORS["key_bg"])
        self._cost_method.pack(side="left", padx=8)
        exact = tk.Button(top, text="↻ exact", font=FONTS["tiny"], bg=COLORS["key_bg"], fg=COLORS["text_dim"],
                          relief="flat", cursor="hand2", padx=4, command=lambda: self._refresh_cost(exact=True))
        exact.pack(side="right")
        Tooltip(exact, "Count the real input tokens with the free count_tokens endpoint (needs the API key)")
        self._cost_detail = tk.Label(cost, text="", font=FONTS["tiny"], fg=COLORS["text_dim"], bg=COLORS["key_bg"],
                                     anchor="w", justify="left")
        self._cost_detail.pack(fill="x", padx=12, pady=(0, 5))

        btns = tk.Frame(bar, bg=COLORS["bg_card"])
        btns.pack(fill="x", padx=12, pady=(8, 2))
        self.start_btn = tk.Button(btns, text="▶  Start Translation", font=FONTS["heading"],
                                   bg=COLORS["btn_primary"], fg="#ffffff", relief="flat",
                                   activebackground=COLORS["btn_hover"], activeforeground="#ffffff",
                                   cursor="hand2", pady=6, command=lambda: self._start(sample=False))
        self.start_btn.pack(fill="x")
        row = tk.Frame(btns, bg=COLORS["bg_card"])
        row.pack(fill="x", pady=(5, 0))
        self.sample_btn = self._flat_btn(row, f"◐  Sample ({SAMPLE_BLOCKS} blocks)", lambda: self._start(sample=True), pady=5)
        self.sample_btn.pack(side="left", fill="x", expand=True, padx=(0, 3))
        Tooltip(self.sample_btn, f"Translate only the first {SAMPLE_BLOCKS} blocks, show them in Comparison\n"
                                 "with the real cost, save nothing.")
        self.cancel_btn = self._flat_btn(row, "✕  Cancel", self._cancel, danger=True, pady=5)
        self.cancel_btn.configure(state="disabled")
        self.cancel_btn.pack(side="left", fill="x", expand=True, padx=(3, 0))

        prog = tk.Frame(bar, bg=COLORS["bg_card"])
        prog.pack(fill="x", padx=12, pady=(3, 5))
        self.pct_label = tk.Label(prog, text="", font=FONTS["tiny"], fg=COLORS["accent"], bg=COLORS["bg_card"],
                                  anchor="e", width=5)
        self.pct_label.pack(side="right")
        ttk.Progressbar(prog, variable=self.progress_var, maximum=100, style="P.Horizontal.TProgressbar"
                        ).pack(side="left", fill="x", expand=True, pady=4)

    # ── Right panel ──────────────────────────────────────────────────

    def _build_right(self, parent):
        nb = ttk.Notebook(parent, style="T.TNotebook")
        nb.pack(fill="both", expand=True)
        self.notebook = nb
        self.TAB_PREVIEW, self.TAB_NAMES, self.TAB_COMPARE, self.TAB_LOG = 0, 1, 2, 3

        def text_widget(frame, fg=COLORS["text"], bg=COLORS["bg_card"]):
            return scrolledtext.ScrolledText(frame, font=FONTS["mono_sm"], bg=bg, fg=fg,
                                             insertbackground=COLORS["text"], selectbackground=COLORS["accent"],
                                             relief="flat", state="disabled", wrap="word", highlightthickness=0)

        t1 = tk.Frame(nb, bg=COLORS["bg_card"])
        nb.add(t1, text="  Source Preview  ")
        self.preview_text = text_widget(t1)
        self.preview_text.pack(fill="both", expand=True, padx=8, pady=8)
        self.preview_text.tag_configure("id", foreground=COLORS["accent"], font=("Consolas", 10, "bold"))
        self.preview_text.tag_configure("ts", foreground=COLORS["text_dim"], font=("Consolas", 9))
        self.preview_text.tag_configure("txt", foreground=COLORS["text"])

        t2 = tk.Frame(nb, bg=COLORS["bg_card"])
        nb.add(t2, text="  Names  ")
        self._build_names_tab(t2)

        t3 = tk.Frame(nb, bg=COLORS["bg_card"])
        nb.add(t3, text="  Comparison  ")
        ch = tk.Frame(t3, bg=COLORS["bg_card"])
        ch.pack(fill="x", padx=8, pady=(8, 4))
        tk.Label(ch, text="ORIGINAL", font=FONTS["badge"], fg=COLORS["text_dim"], bg=COLORS["bg_card"]).pack(side="left", expand=True)
        self._cmp_title = tk.Label(ch, text="TRANSLATED", font=FONTS["badge"], fg=COLORS["success"], bg=COLORS["bg_card"])
        self._cmp_title.pack(side="right", expand=True)
        cb = tk.PanedWindow(t3, orient="horizontal", bg=COLORS["border"], sashwidth=6,
                            sashrelief="flat", bd=0, opaqueresize=True)
        cb.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.compare_orig = text_widget(cb, bg=COLORS["bg_input"])
        self.compare_trans = text_widget(cb, fg=COLORS["success"], bg=COLORS["bg_input"])
        cb.add(self.compare_orig, stretch="always", minsize=120, width=300)
        cb.add(self.compare_trans, stretch="always", minsize=120, width=300)
        for w in (self.compare_orig, self.compare_trans):
            w.tag_configure("flag", foreground=COLORS["error"])
            w.tag_configure("hdr", foreground=COLORS["text_dim"])
            w.tag_configure("flaghdr", foreground=COLORS["warning"], font=("Consolas", 9, "bold"))

        def _sync(src, dst):
            def cb_(first, last):
                src.vbar.set(first, last)
                if abs(dst.yview()[0] - float(first)) > 1e-6:
                    dst.yview_moveto(first)
            return cb_
        self.compare_orig.configure(yscrollcommand=_sync(self.compare_orig, self.compare_trans))
        self.compare_trans.configure(yscrollcommand=_sync(self.compare_trans, self.compare_orig))

        t4 = tk.Frame(nb, bg=COLORS["bg_card"])
        nb.add(t4, text="  Activity Log  ")
        self.log_text = text_widget(t4, fg=COLORS["text_dim"])
        self.log_text.pack(fill="both", expand=True, padx=8, pady=8)
        for tag, color in [("info", COLORS["text_dim"]), ("success", COLORS["success"]),
                           ("warn", COLORS["warning"]), ("error", COLORS["error"]), ("accent", COLORS["accent"])]:
            self.log_text.tag_configure(tag, foreground=color)

    # NAMES TAB ───────────────────────────────────────────────────────
    def _build_names_tab(self, t):
        top = tk.Frame(t, bg=COLORS["bg_card"])
        top.pack(fill="x", padx=10, pady=(10, 4))
        tk.Label(top, text="PRESERVE NAMES — never translated", font=FONTS["badge"], fg=COLORS["accent"],
                 bg=COLORS["bg_card"]).pack(side="left")
        tk.Label(top, textvariable=self._names_count, font=FONTS["tiny"], fg=COLORS["text_dim"],
                 bg=COLORS["bg_card"]).pack(side="right")
        tk.Label(t, text="One name per line: people, companies, schools, institutions, brands, titles. "
                         "Countries and cities are translated normally. A <file>.names.txt next to the "
                         "subtitle is loaded automatically.",
                 font=FONTS["tiny"], fg=COLORS["text_dim"], bg=COLORS["bg_card"], anchor="w", justify="left",
                 wraplength=520).pack(fill="x", padx=10)
        self._gloss_text = tk.Text(t, font=FONTS["mono"], bg=COLORS["bg_input"], fg=COLORS["text"],
                                   insertbackground=COLORS["text"], relief="flat", wrap="word",
                                   highlightbackground=COLORS["border"], highlightthickness=1, padx=8, pady=6)
        self._gloss_text.pack(fill="both", expand=True, padx=10, pady=(6, 4))
        self._gloss_text.insert("1.0", self._initial_glossary)
        self._gloss_text.bind("<KeyRelease>", lambda e: self._update_names_count())
        row = tk.Frame(t, bg=COLORS["bg_card"])
        row.pack(fill="x", padx=10, pady=(0, 6))
        self._names_btn = self._flat_btn(row, "✦  Auto-detect names (Claude)", self._auto_detect_names, font=FONTS["tiny"], pady=4)
        self._names_btn.pack(side="left")
        Tooltip(self._names_btn, "Ask the cheapest Claude model to list the proper names in the loaded file.\n"
                                 "Costs a fraction of a cent. Review the list before you start.")
        self._flat_btn(row, "Save next to SRT", self._save_glossary_sidecar, dim=True, font=FONTS["tiny"], pady=4).pack(side="left", padx=(6, 0))
        self._flat_btn(row, "Load from file…", self._load_glossary_file, dim=True, font=FONTS["tiny"], pady=4).pack(side="left", padx=(6, 0))
        self._flat_btn(row, "Clear", self._clear_glossary, dim=True, font=FONTS["tiny"], pady=4).pack(side="right")
        self._gloss_status = tk.Label(t, text="", font=FONTS["tiny"], fg=COLORS["text_dim"], bg=COLORS["bg_card"], anchor="w")
        self._gloss_status.pack(fill="x", padx=10, pady=(0, 8))

    def _glossary_text(self) -> str:
        try:
            return self._gloss_text.get("1.0", "end").strip()
        except Exception:
            return ""

    def _glossary_terms(self) -> list:
        return parse_glossary(self._glossary_text())

    def _update_names_count(self):
        n = len(self._glossary_terms())
        self._names_count.set(f"{n} name{'s' if n != 1 else ''}")
        try:
            self.notebook.tab(self.TAB_NAMES, text=f"  Names ({n})  " if n else "  Names  ")
        except Exception:
            pass

    def _merge_glossary(self, terms: list) -> int:
        existing = {t.lower() for t in self._glossary_terms()}
        new = [t for t in terms if t.lower() not in existing]
        if new:
            cur = self._glossary_text()
            self._gloss_text.insert("end", ("\n" if cur else "") + "\n".join(new))
        self._update_names_count()
        self._refresh_cost()
        return len(new)

    def _clear_glossary(self):
        self._gloss_text.delete("1.0", "end")
        self._update_names_count()
        self._gloss_status.configure(text="")
        self._refresh_cost()

    def _load_glossary_file(self):
        path = filedialog.askopenfilename(title="Load names list", filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if not path:
            return
        try:
            n = self._merge_glossary(parse_glossary(Path(path).read_text(encoding="utf-8")))
            self._gloss_status.configure(text=f"Loaded {Path(path).name}: {n} new names")
        except Exception as e:
            messagebox.showerror("Load failed", str(e))

    def _save_glossary_sidecar(self):
        if not self.input_path:
            messagebox.showwarning("No file", "Load a source SRT first.")
            return
        path = glossary_sidecar_path(self.input_path)
        try:
            path.write_text("\n".join(self._glossary_terms()) + "\n", encoding="utf-8")
            self._gloss_status.configure(text=f"Saved: {path.name}")
            self._log(f"Names saved to {path}", "info")
        except Exception as e:
            messagebox.showerror("Save failed", str(e))

    def _auto_detect_names(self):
        if not self.source_blocks:
            messagebox.showwarning("No file", "Load a source SRT first.")
            return
        if not self._api_key.strip():
            messagebox.showwarning("API Key", "Auto-detect needs a Claude API key (Settings).")
            return
        mid = DEFAULT_MODEL if self.catalog.has_model(DEFAULT_MODEL) else self.claude_model.get()
        model_info = self.catalog.model(mid)
        self._names_btn.configure(state="disabled")
        self._gloss_status.configure(text=f"Detecting names with {model_info['display_name']}…")

        def work():
            try:
                client = _anthropic().Anthropic(api_key=self._api_key.strip(), max_retries=2, timeout=180)
                names, usage = extract_names(client, self.source_blocks, model_info,
                                             _LANG_LABEL.get(self.source_lang.get(), self.source_lang.get()))
                cost = usage.summary(self.catalog.price(mid))

                def done():
                    n = self._merge_glossary(names)
                    self._gloss_status.configure(text=f"{len(names)} names found, {n} added  ·  cost {cost}")
                    self._log(f"Auto-detect names: {len(names)} found, {n} added  ·  {cost}", "accent")
                self._post(done)
            except Exception as e:
                msg = _err(e)
                self._post(lambda: (self._gloss_status.configure(text=f"Failed: {msg}"),
                                    self._log(f"Auto-detect names failed: {msg}", "error")))
            finally:
                self._post(lambda: self._names_btn.configure(state="normal"))
        threading.Thread(target=work, daemon=True).start()

    # ── Engine / model / catalog ─────────────────────────────────────

    def _on_engine_change(self, *args):
        sel = self.engine.get()
        for value, b in self._eng_btns.items():
            on = value == sel
            b.configure(bg=COLORS["accent"] if on else COLORS["bg_input"],
                        fg="#ffffff" if on else COLORS["text_dim"],
                        activebackground=COLORS["accent"] if on else COLORS["border"])
        state = "readonly" if sel == "claude" else "disabled"
        self._model_combo.configure(state=state)
        self._model_refresh_btn.configure(state="normal" if sel == "claude" else "disabled")
        self._refresh_cost()

    def _fill_model_combo(self):
        self._model_ids = [m["id"] for m in self.catalog.models]
        values = [self.catalog.label(mid) for mid in self._model_ids]
        self._model_combo.configure(values=values)
        cur = self.catalog.pick_default(self.claude_model.get())
        if cur != self.claude_model.get():
            self.claude_model.set(cur)
        idx = self._model_ids.index(cur) if cur in self._model_ids else 0
        if values:
            self._model_combo_var.set(values[idx])
        when = (datetime.fromtimestamp(self.catalog.models_fetched_at).strftime("%d %b %H:%M")
                if self.catalog.models_fetched_at else "never")
        pwhen = (datetime.fromtimestamp(self.catalog.prices_fetched_at).strftime("%d %b %H:%M")
                 if self.catalog.prices_fetched_at else "never")
        self._catalog_status.set(
            f"Models: {len(self._model_ids)} · {self.catalog.models_source} · updated {when}\n"
            f"Prices: {self.catalog.prices_source} · updated {pwhen}"
            + ("\nOverride: pricing.json is active" if self.catalog.override else ""))

    def _on_model_selected(self, event=None):
        idx = self._model_combo.current()
        if 0 <= idx < len(self._model_ids):
            self.claude_model.set(self._model_ids[idx])

    def _refresh_catalog(self, force: bool):
        def work():
            msgs = []
            if force or self.catalog.prices_stale():
                ok = self.catalog.refresh_prices()
                msgs.append("prices updated from anthropic.com" if ok else "price fetch failed (using cached/built-in)")
            if self._api_key.strip() and (force or self.catalog.models_stale()):
                try:
                    self.catalog.refresh_models(self._api_key)
                    msgs.append(f"{len(self.catalog.models)} models read from the API")
                except Exception as e:
                    msgs.append(f"model list fetch failed: {_err(e)}")
            elif not self._api_key.strip():
                msgs.append("no API key — model list not refreshed")

            def done():
                self._fill_model_combo()
                self._refresh_cost()
                self._log("Catalog: " + "; ".join(msgs), "info")
            self._post(done)
        self._catalog_status.set("refreshing…")
        threading.Thread(target=work, daemon=True).start()

    # ── Cost ─────────────────────────────────────────────────────────

    def _refresh_cost(self, exact: bool = False):
        if not hasattr(self, "_cost_main"):
            return
        if not self.source_blocks or self.engine.get() != "claude":
            self._cost_main.configure(text="free" if self.engine.get() != "claude" else "—", fg=COLORS["text_dim"])
            self._cost_detail.configure(text="MyMemory has no cost" if self.engine.get() != "claude" else "load a file")
            self._cost_method.configure(text="")
            return
        args = dict(blocks=self.source_blocks, model_id=self.claude_model.get(), catalog=self.catalog,
                    api_key=self._api_key, ctx_blocks=self.context_blocks,
                    glossary=self._glossary_terms(), batch_size=self._int(self.batch_size, 25, 5, 60),
                    translate_cues=self.translate_cues.get(), target_code=self.target_lang.get(),
                    src_label=_LANG_LABEL.get(self.source_lang.get(), self.source_lang.get()),
                    tgt_label=_LANG_LABEL.get(self.target_lang.get(), self.target_lang.get()))
        if exact:
            self._cost_method.configure(text="counting…")

            def work():
                est = estimate_cost(exact=True, **args)
                self._post(lambda: self._show_cost(est))
            threading.Thread(target=work, daemon=True).start()
        else:
            self._show_cost(estimate_cost(exact=False, **args))

    def _show_cost(self, est: dict):
        if not est:
            return
        total = est.get("total_cost")
        if total is None:
            self._cost_main.configure(text="price unknown", fg=COLORS["warning"])
        else:
            self._cost_main.configure(
                text="< $0.01" if total < 0.01 else f"~${total:.3f}",
                fg=COLORS["success"] if total < 0.05 else COLORS["warning"] if total < 0.50 else COLORS["error"])
        p = est["price"]
        price_s = (f"${p['input']:g} / ${p['output']:g} per MTok ({p['source']})"
                   if p["input"] is not None else "no price found")
        detail = f"{est['input_tokens']:,} in + {est['output_tokens']:,} out tokens  ·  {price_s}"
        if self.context_blocks:
            detail += "  +context"
        self._cost_detail.configure(text=detail)
        self._cost_method.configure(text="exact input count" if est.get("method") == "exact" else "approx.")

    # ── Settings dialog ──────────────────────────────────────────────

    def _dialog(self, title, w, h):
        dlg = tk.Toplevel(self)
        dlg.title(title)
        dlg.configure(bg=COLORS["bg_card"])
        dlg.transient(self)
        self.update_idletasks()
        dlg.geometry(f"{w}x{h}+{self.winfo_rootx() + max(0, (self.winfo_width() - w) // 2)}"
                     f"+{self.winfo_rooty() + max(0, (self.winfo_height() - h) // 2)}")
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        return dlg

    def _show_settings(self):
        if self._settings_dlg and self._settings_dlg.winfo_exists():
            self._settings_dlg.lift()
            return
        dlg = self._dialog("Settings", 560, 400)
        dlg.resizable(False, False)
        self._settings_dlg = dlg
        pad = {"padx": 20}

        def section(text):
            tk.Label(dlg, text=text, font=FONTS["badge"], fg=COLORS["accent"], bg=COLORS["bg_card"],
                     anchor="w").pack(fill="x", pady=(16, 4), **pad)

        section("CLAUDE API KEY")
        row = tk.Frame(dlg, bg=COLORS["bg_card"])
        row.pack(fill="x", **pad)
        self.key_display = tk.Label(row, text=self._mask_key(self._api_key), font=FONTS["mono_sm"],
                                    bg=COLORS["key_bg"], fg=COLORS["text_dim"], anchor="w", padx=8, pady=5,
                                    highlightbackground=COLORS["border"], highlightthickness=1)
        self.key_display.pack(side="left", fill="x", expand=True)
        self._flat_btn(row, "✎  Edit", self._edit_key, dim=True, font=FONTS["tiny"], padx=10, pady=5).pack(side="right", padx=(6, 0))
        tk.Label(dlg, text="Stored only on this computer, sent only to api.anthropic.com. "
                           "Get a key at console.anthropic.com.", font=FONTS["tiny"], fg=COLORS["text_dim"],
                 bg=COLORS["bg_card"], anchor="w", wraplength=520, justify="left").pack(fill="x", pady=(3, 0), **pad)
        self._flat_btn(dlg, "Open console.anthropic.com", lambda: webbrowser.open("https://console.anthropic.com"),
                       dim=True, font=FONTS["tiny"], pady=3).pack(anchor="w", pady=(4, 0), **pad)

        section("MODELS AND PRICES")
        row2 = tk.Frame(dlg, bg=COLORS["bg_card"])
        row2.pack(fill="x", **pad)
        tk.Label(row2, textvariable=self._catalog_status, font=FONTS["tiny"], fg=COLORS["text"],
                 bg=COLORS["bg_card"], anchor="w", justify="left").pack(side="left", fill="x", expand=True)
        self._flat_btn(row2, "⟳  Refresh now", lambda: self._refresh_catalog(force=True), dim=True,
                       font=FONTS["tiny"], pady=4).pack(side="right")
        tk.Label(dlg, text=f"Price override file (optional): {PRICING_OVERRIDE_PATH}",
                 font=FONTS["tiny"], fg=COLORS["text_dim"], bg=COLORS["bg_card"], anchor="w",
                 wraplength=520, justify="left").pack(fill="x", pady=(4, 0), **pad)

        section("FILES")
        tk.Label(dlg, text=f"Settings file: {CONFIG_PATH}", font=FONTS["tiny"], fg=COLORS["text_dim"],
                 bg=COLORS["bg_card"], anchor="w", wraplength=520, justify="left").pack(fill="x", **pad)
        tk.Label(dlg, textvariable=self._last_dir_var, font=FONTS["tiny"], fg=COLORS["text_dim"],
                 bg=COLORS["bg_card"], anchor="w", wraplength=520, justify="left").pack(fill="x", **pad)

        self._flat_btn(dlg, "  Close  ", dlg.destroy, primary=True, padx=20, pady=5).pack(side="bottom", pady=(0, 14))

    def _mask_key(self, key: str) -> str:
        k = key.strip()
        if not k:
            return "No key set — click Edit to add one"
        if len(k) <= 8:
            return "•" * len(k)
        return k[:7] + " ••••••••••••••••••••• " + k[-4:]

    def _edit_key(self):
        dlg = self._dialog("Edit Claude API Key", 460, 210)
        dlg.resizable(False, False)
        dlg.grab_set()
        tk.Label(dlg, text="Update Claude API Key", font=FONTS["heading"], fg=COLORS["text_bright"],
                 bg=COLORS["bg_card"]).pack(pady=(18, 2))
        tk.Label(dlg, text="Paste your key. Stored locally, sent only to api.anthropic.com.",
                 font=FONTS["tiny"], fg=COLORS["text_dim"], bg=COLORS["bg_card"]).pack()
        var = tk.StringVar(value=self._api_key)
        ent = tk.Entry(dlg, textvariable=var, show="•", font=FONTS["mono_sm"], bg=COLORS["bg_input"],
                       fg=COLORS["text"], insertbackground=COLORS["text"], relief="flat",
                       highlightbackground=COLORS["border"], highlightthickness=1, width=48)
        ent.pack(padx=20, pady=(10, 4), ipady=6)
        ent.focus_set()

        def toggle():
            ent.configure(show="" if ent.cget("show") else "•")
            sb2.configure(text="Hide" if not ent.cget("show") else "Show")
        sb2 = tk.Button(dlg, text="Show", font=FONTS["tiny"], bg=COLORS["bg_input"], fg=COLORS["text_dim"],
                        relief="flat", cursor="hand2", command=toggle)
        sb2.pack()

        def save():
            self._api_key = var.get().strip()
            try:
                self.key_display.configure(text=self._mask_key(self._api_key))
            except Exception:
                pass
            save_config({"api_key": self._api_key})
            dlg.destroy()
            self._refresh_catalog(force=True)
        br = tk.Frame(dlg, bg=COLORS["bg_card"])
        br.pack(pady=(10, 0))
        self._flat_btn(br, "Save", save, primary=True, padx=18).pack(side="left", padx=6)
        self._flat_btn(br, "Cancel", dlg.destroy, dim=True, padx=18).pack(side="left", padx=6)
        ent.bind("<Return>", lambda e: save())
        dlg.wait_window()

    # ── Help dialogs ─────────────────────────────────────────────────

    def _show_text_dialog(self, title, text, w=640, h=560):
        dlg = self._dialog(title, w, h)
        dlg.minsize(420, 320)
        txt = scrolledtext.ScrolledText(dlg, font=("Consolas", 9), bg=COLORS["bg_dark"], fg=COLORS["text"],
                                        relief="flat", wrap="word", padx=18, pady=14, highlightthickness=0)
        txt.pack(fill="both", expand=True)
        txt.insert("1.0", text)
        txt.tag_configure("hdr", foreground=COLORS["accent"], font=("Consolas", 9, "bold"))
        for m in re.finditer(r"^([A-Z][A-Z /()0-9.&-]{3,})\n-{3,}", text, re.MULTILINE):
            line_no = text[:m.start()].count("\n") + 1
            txt.tag_add("hdr", f"{line_no}.0", f"{line_no}.end")
        txt.configure(state="disabled")
        self._flat_btn(dlg, "  Close  ", dlg.destroy, primary=True, padx=20, pady=5).pack(pady=(0, 14))

    def _show_help(self):
        self._show_text_dialog(f"Help — {APP_TITLE}", HELP_TEXT, 700, 640)

    def _show_engine_help(self):
        self._show_text_dialog("Translation engines", ENGINE_HELP_TEXT, 640, 560)

    # ── File handling ────────────────────────────────────────────────

    def _browse(self):
        path = filedialog.askopenfilename(title="Select source SRT file",
                                          filetypes=[("SRT files", "*.srt"), ("All files", "*.*")])
        if path:
            self._load_source_file(path)

    def _browse_context(self):
        path = filedialog.askopenfilename(title="Select context SRT file (same film, different language)",
                                          filetypes=[("SRT files", "*.srt"), ("All files", "*.*")])
        if path:
            self._load_context_file(path)

    def _load_srt(self, path: str, what: str):
        path = path.strip()
        if not path.lower().endswith(".srt"):
            messagebox.showwarning("Wrong file type", "Please select an .srt subtitle file.")
            return None
        try:
            blocks, enc = parse_srt(path)
        except Exception as e:
            messagebox.showerror("Parse Error", f"Could not parse {what}:\n{e}")
            return None
        if not blocks:
            messagebox.showwarning("Empty File", f"No subtitle blocks found in {what}.")
            return None
        return path, blocks, enc.upper().replace("-SIG", "+BOM")

    def _update_file_info(self):
        if not self.source_blocks:
            return
        b = self.source_blocks
        avg = sum(len(" ".join(x["text_lines"])) for x in b) / len(b)
        n_cues = sum(1 for x in b for l in x["text_lines"] if is_cue(l))
        detected = _LANG_LABEL.get(self._detected_code, self._detected_code)
        out_name = default_output_name(self.input_path, self.target_lang.get())
        if len(out_name) > 52:
            out_name = "…" + out_name[-49:]
        self.file_info.configure(
            text=f"{len(b):,} blocks  ·  {self._enc_short}  ·  {detected}  ·  {n_cues} cue lines  ·  "
                 f"avg {avg:.0f} chars\nOutput: {out_name}")

    def _load_source_file(self, path: str):
        loaded = self._load_srt(path, "file")
        if not loaded:
            return
        path, blocks, enc_short = loaded
        self.source_blocks = blocks
        self.translated_blocks = []
        self.qc_issues = []
        self.input_path = path
        self._enc_short = enc_short
        self._detected_code = detect_language(blocks)
        self.file_label.configure(text=Path(path).name, fg=COLORS["text_bright"])
        sug = suggest_batch_size(blocks)
        self.batch_size.set(sug)
        self._set_src_combo(self._detected_code)
        self._update_file_info()
        self._src_drop.configure(highlightbackground=COLORS["success"], bg=COLORS["bg_input"])
        n_cues = sum(1 for b in blocks for l in b["text_lines"] if is_cue(l))
        self._log(f"Loaded: {Path(path).name} — {len(blocks):,} blocks  [{enc_short}]  •  {n_cues} cue lines", "accent")
        self._log(f"Detected: {_LANG_LABEL.get(self._detected_code, self._detected_code)}  •  auto batch={sug}", "info")

        sidecar = glossary_sidecar_path(path)
        if sidecar.exists():
            try:
                n = self._merge_glossary(parse_glossary(sidecar.read_text(encoding="utf-8")))
                self._gloss_status.configure(text=f"Loaded {sidecar.name} ({n} new names)")
                self._log(f"Names file: {sidecar.name} — {n} new names added", "info")
            except Exception as e:
                self._log(f"Could not read {sidecar.name}: {e}", "warn")
        self._show_preview()
        self._refresh_cost()
        self.status_text.set("Check the estimate, then press Start (or Sample to try the first blocks)")

    def _load_context_file(self, path: str):
        loaded = self._load_srt(path, "context file")
        if not loaded:
            return
        path, blocks, enc_short = loaded
        for b in blocks:
            b["_ms"] = timestamp_ms(b["timestamp"])
        self.context_blocks = blocks
        self.context_path = path
        self._ctx_label.configure(text=f"Context: {Path(path).name}  ({len(blocks):,} blocks)", fg=COLORS["success"])
        self._ctx_add_btn.pack_forget()
        self._ctx_clear_btn.pack(side="right")
        self._log(f"Context: {Path(path).name} — {len(blocks):,} blocks  [{enc_short}]", "info")
        self._refresh_cost()

    def _clear_context(self):
        self.context_blocks = []
        self.context_path = ""
        self._ctx_label.configure(text="Context: none", fg=COLORS["text_dim"])
        self._ctx_clear_btn.pack_forget()
        self._ctx_add_btn.pack(side="right")
        self._refresh_cost()

    def _show_preview(self):
        self.preview_text.configure(state="normal")
        self.preview_text.delete("1.0", "end")
        for b in self.source_blocks[:50]:
            self.preview_text.insert("end", f"{b['id']}\n", "id")
            self.preview_text.insert("end", f"{b['timestamp']}\n", "ts")
            for line in b["text_lines"]:
                self.preview_text.insert("end", f"{line}\n", "txt")
            self.preview_text.insert("end", "\n")
        if len(self.source_blocks) > 50:
            self.preview_text.insert("end", f"\n... and {len(self.source_blocks) - 50:,} more blocks\n", "ts")
        self.preview_text.configure(state="disabled")
        self.notebook.select(self.TAB_PREVIEW)

    # ── Translation ──────────────────────────────────────────────────

    def _resolve_output_path(self):
        default_name = default_output_name(self.input_path, self.target_lang.get())
        if self.same_folder.get():
            return str(Path(self.input_path).parent / default_name)
        output = filedialog.asksaveasfilename(
            title="Save translated file as", defaultextension=".srt", initialfile=default_name,
            initialdir=self._last_output_dir or str(Path(self.input_path).parent),
            filetypes=[("SRT files", "*.srt")])
        if not output:
            return None
        self._last_output_dir = str(Path(output).parent)
        self._last_dir_var.set(self._last_dir_display())
        return output

    def _start(self, sample: bool):
        if self.is_translating:
            return
        if not self.source_blocks:
            messagebox.showwarning("No File", "Please load an SRT file first.")
            self.status_text.set("Load a .srt file to begin")
            return
        engine = self.engine.get()
        if engine == "claude":
            if not self._api_key.strip():
                messagebox.showwarning("API Key", "No Claude API key set.\nOpen ⚙ Settings to add one.")
                return
            if _try_import("anthropic") is None:
                if ensure_dependencies(self):
                    return
        elif _try_import("requests") is None:
            if ensure_dependencies(self):
                return

        if sample:
            self.output_path = ""
            blocks = self.source_blocks[:SAMPLE_BLOCKS]
        else:
            output = self._resolve_output_path()
            if not output:
                return
            self.output_path = output
            blocks = self.source_blocks

        self.is_translating = True
        self.cancel_flag = False
        self.translated_blocks = []
        self.qc_issues = []
        self.progress_var.set(0)
        self.start_btn.configure(state="disabled")
        self.sample_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.notebook.select(self.TAB_LOG)
        self.status_text.set("Translating…")

        bsize = self._int(self.batch_size, 25, 5, 60)
        model_lbl = self.catalog.model(self.claude_model.get())["display_name"] if engine == "claude" else "MyMemory"
        glossary = self._glossary_terms()
        self._log("═" * 50, "info")
        self._log(f"{'SAMPLE RUN' if sample else 'Starting'}: {_LANG_LABEL.get(self.source_lang.get())} → "
                  f"{_LANG_LABEL.get(self.target_lang.get())}", "accent")
        self._log(f"Engine  : {model_lbl}", "info")
        self._log(f"Blocks  : {len(blocks):,}  │  Batch: {bsize}  │  Workers: {self._int(self.workers, 5, 1, 8)}  │  "
                  f"Cues: {'translate' if self.translate_cues.get() else 'keep'}", "info")
        self._log(f"Context : {Path(self.context_path).name if self.context_blocks and engine == 'claude' else 'none'}"
                  f"  │  Names : {len(glossary)}", "info")
        if not sample:
            self._log(f"Output  : {self.output_path}", "info")
        self._log("═" * 50, "info")
        # Snapshot every setting on the main thread: Tk variables must not be read from the worker
        run = {
            "engine": engine, "model_id": self.claude_model.get(), "bsize": bsize,
            "n_workers": self._int(self.workers, 5, 1, 8) if engine == "claude" else 1,
            "cues": self.translate_cues.get(),
            "src_code": self.source_lang.get(), "tgt_code": self.target_lang.get(),
            "api_key": self._api_key.strip(), "output_path": self.output_path,
            "ctx": self.context_blocks if engine == "claude" else [],
        }
        threading.Thread(target=self._worker, args=(blocks, sample, glossary, run), daemon=True).start()

    def _worker(self, blocks: list, sample: bool, glossary: list, run: dict):
        total     = len(blocks)
        engine    = run["engine"]
        src_code, tgt_code = run["src_code"], run["tgt_code"]
        src       = _LANG_LABEL.get(src_code, src_code)
        tgt       = _LANG_LABEL.get(tgt_code, tgt_code)
        model_id  = run["model_id"]
        model     = self.catalog.model(model_id)
        price     = self.catalog.price(model_id)
        bsize     = run["bsize"]
        n_workers = run["n_workers"]
        cues      = run["cues"]
        ctx       = run["ctx"]
        output_path = run["output_path"]
        usage     = UsageTotals()
        errors    = []
        client    = None
        if engine == "claude":
            client = _anthropic().Anthropic(api_key=run["api_key"], max_retries=3, timeout=180)

        batches   = [blocks[i:i + bsize] for i in range(0, total, bsize)]
        n_batches = len(batches)
        results   = [None] * n_batches
        done_cnt  = [0]
        lock      = threading.Lock()

        def ctx_for(batch, idx):
            if not ctx:
                return ""
            s = min(timestamp_ms(b["timestamp"])[0] for b in batch)
            e = max(timestamp_ms(b["timestamp"])[1] for b in batch)
            return context_window_text(ctx, s, e, idx / n_batches, (idx + 1) / n_batches)

        def translate(batch, idx):
            if engine == "claude":
                return claude_translate_batch(client, batch, src, tgt, model, glossary,
                                              ctx_for(batch, idx), cues, usage)
            return [{**b, "text_lines": translate_free(b["text_lines"], src_code, tgt_code, cues)}
                    for b in batch]

        def keep_original(batch):
            return [{**b, "text_lines": b["text_lines"][:], "_untranslated": bool(b["text_lines"])} for b in batch]

        def do_batch(idx, batch):
            if self.cancel_flag:
                return idx, keep_original(batch)
            for attempt in range(3):
                if self.cancel_flag:
                    return idx, keep_original(batch)
                try:
                    return idx, translate(batch, idx)
                except Exception as e:
                    fatal = _is_fatal(e)
                    if attempt < 2 and not fatal:
                        wait = 2 ** (attempt + 1)
                        self._log(f"Batch {idx + 1} attempt {attempt + 1} failed: {_err(e)}. Retry in {wait}s…", "warn")
                        time.sleep(wait)
                    else:
                        self._log(f"✗ Batch {idx + 1} failed: {_err(e)} — keeping originals", "error")
                        errors.append(f"Batch {idx + 1}: {_err(e)}")
                        return idx, keep_original(batch)
            return idx, keep_original(batch)

        def progress(n_done):
            pct = n_done / total * 100

            def ui():
                self.progress_var.set(pct)
                self.status_text.set(f"Translating…  batch {done_cnt[0]}/{n_batches}  ·  {n_done:,}/{total:,} blocks  ({pct:.0f}%)")
                self.pct_label.configure(text=f"{pct:.0f}%")
            self._post(ui)

        pool = concurrent.futures.ThreadPoolExecutor(max_workers=n_workers)
        futs = {pool.submit(do_batch, i, b): i for i, b in enumerate(batches)}
        blocks_done = 0
        try:
            for fut in concurrent.futures.as_completed(futs):
                if self.cancel_flag:
                    break
                bidx, bres = fut.result()
                results[bidx] = bres
                with lock:
                    done_cnt[0] += 1
                    blocks_done += len(bres)
                progress(blocks_done)
                self._log(f"  ✓ Batch {bidx + 1:3d}/{n_batches}  ({len(bres)} blocks)", "info")
        finally:
            pool.shutdown(wait=not self.cancel_flag, cancel_futures=True)

        if self.cancel_flag:
            self._log("Translation cancelled.", "warn")
            self._post(self._done)
            return

        out_blocks = [blk for br in results if br is not None for blk in br]
        if len(out_blocks) != total:
            self._log(f"✗ Internal error: {len(out_blocks)} of {total} blocks assembled", "error")
            self._post(self._done)
            return

        # ── Quality control + repair pass ─────────────────────────────
        issues = qc_report(blocks, out_blocks, glossary, cues)
        retry_idx = sorted({i for i, kind, _ in issues
                            if kind in ("untranslated", "unchanged", "empty_line", "placeholder", "name", "number")})
        if retry_idx and engine == "claude" and client is not None:
            self._log(f"\n─── QUALITY CONTROL ───  {len(retry_idx)} block(s) need a second pass", "accent")
            self._post(lambda: self.status_text.set(f"Quality control: retranslating {len(retry_idx)} block(s)…"))
            for k in range(0, len(retry_idx), 8):
                chunk = retry_idx[k:k + 8]
                sub = [{kk: v for kk, v in blocks[i].items()} for i in chunk]
                try:
                    fixed = claude_translate_batch(client, sub, src, tgt, model, glossary, "", cues, usage)
                    for i, fb in zip(chunk, fixed):
                        out_blocks[i] = fb
                except Exception as e:
                    self._log(f"  QC retry failed for blocks {chunk[0] + 1}-{chunk[-1] + 1}: {_err(e)}", "warn")
            issues = qc_report(blocks, out_blocks, glossary, cues)

        for b in out_blocks:
            b.pop("_untranslated", None)
        self.translated_blocks = out_blocks
        self.qc_issues = issues

        if issues:
            self._log(f"\nQC report: {len(issues)} issue(s) in {len({i for i, _, _ in issues})} block(s)", "warn")
            for i, kind, detail in issues[:40]:
                self._log(f"  [{blocks[i]['id']}] {kind}: {detail}", "warn")
            if len(issues) > 40:
                self._log(f"  … and {len(issues) - 40} more (see Comparison tab)", "warn")
        else:
            self._log("\nQC report: no issues found", "success")

        # ── Save + verify ─────────────────────────────────────────────
        if not sample:
            try:
                write_srt(out_blocks, output_path)
                self._log(f"\nFile saved: {output_path}", "success")
            except Exception as e:
                self._log(f"✗ Failed to write: {e}", "error")
                self._post(self._done)
                return
            try:
                ob, _ = parse_srt(output_path)
                checks = [
                    ("Block count",    len(ob) == total),
                    ("All IDs match",  all(ob[j]["id"] == blocks[j]["id"] for j in range(min(len(ob), total)))),
                    ("All timestamps", all(ob[j]["timestamp"] == blocks[j]["timestamp"] for j in range(min(len(ob), total)))),
                    ("All line counts", all(len(ob[j]["text_lines"]) == len(blocks[j]["text_lines"]) for j in range(min(len(ob), total)))),
                ]
                ok_all = all(ok for _, ok in checks)
                self._log("\n─── VERIFICATION ───", "accent")
                for nm, ok in checks:
                    self._log(f"  {'✓' if ok else '✗'} {nm}", "success" if ok else "error")
                self._log(f"\n{'✅ SUCCESS' if ok_all and not issues else '⚠ Completed with warnings'}"
                          f" — {total:,} blocks translated & verified", "success" if ok_all and not issues else "warn")
            except Exception as e:
                self._log(f"Verification error: {e}", "error")
        else:
            self._log(f"\nSample finished — {total} blocks (nothing saved)", "success")

        if engine == "claude":
            self._log(f"Actual cost: {usage.summary(price)}", "accent")
        if errors:
            self._log(f"\n{len(errors)} batch error(s):", "warn")
            for err in errors[:10]:
                self._log(f"  • {err}", "warn")

        self._post(lambda: self._show_comparison(blocks, out_blocks, issues, sample))
        self._post(self._done)

    def _done(self):
        self.is_translating = False
        self.start_btn.configure(state="normal")
        self.sample_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")
        if self.cancel_flag:
            self.status_text.set("Cancelled")
        elif self.translated_blocks:
            n = len({i for i, _, _ in self.qc_issues})
            self.status_text.set(f"Done — {n} block(s) flagged, see the Comparison tab" if n
                                 else "Done — quality control found no issues")
            self.notebook.select(self.TAB_COMPARE)
        else:
            self.status_text.set("Completed with errors — check the Activity Log")

    def _cancel(self):
        self.cancel_flag = True
        self.status_text.set("Cancelling…")

    def _show_comparison(self, src_blocks, out_blocks, issues, sample):
        flagged = {}
        for i, kind, detail in issues:
            flagged.setdefault(i, []).append(kind)
        self._cmp_title.configure(text=f"TRANSLATED{'  (sample)' if sample else ''}"
                                       + (f"  —  {len(flagged)} flagged" if flagged else ""))
        for w in (self.compare_orig, self.compare_trans):
            w.configure(state="normal")
            w.delete("1.0", "end")
        for i, (s, o) in enumerate(zip(src_blocks, out_blocks)):
            tag = "flaghdr" if i in flagged else "hdr"
            note = f"   ⚠ {', '.join(flagged[i])}" if i in flagged else ""
            self.compare_orig.insert("end", f"[{s['id']}] {s['timestamp']}\n", tag)
            self.compare_trans.insert("end", f"[{o['id']}] {o['timestamp']}{note}\n", tag)
            n = max(len(s["text_lines"]), len(o["text_lines"]))
            for k in range(n):
                a = s["text_lines"][k] if k < len(s["text_lines"]) else ""
                b = o["text_lines"][k] if k < len(o["text_lines"]) else ""
                self.compare_orig.insert("end", f"  {a}\n")
                self.compare_trans.insert("end", f"  {b}\n", "flag" if i in flagged else "")
            self.compare_orig.insert("end", "\n")
            self.compare_trans.insert("end", "\n")
        for w in (self.compare_orig, self.compare_trans):
            w.configure(state="disabled")
            w.yview_moveto(0.0)
        self.update_idletasks()

    # ── Logging ──────────────────────────────────────────────────────

    def _log(self, message, tag="info"):
        def _ins():
            self.log_text.configure(state="normal")
            self.log_text.insert("end", f"[{time.strftime('%H:%M:%S')}] {message}\n", tag)
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        self._post(_ins)


# ═══════════════════════════════════════════════════════════════════════
# ERROR HELPERS
# ═══════════════════════════════════════════════════════════════════════

def _err(e: Exception) -> str:
    msg = getattr(e, "message", None) or str(e)
    status = getattr(e, "status_code", None)
    return f"HTTP {status}: {msg}" if status else msg


def _is_fatal(e: Exception) -> bool:
    """Errors that will not get better by retrying (bad key, bad request, refusal)."""
    if isinstance(e, BatchRefused):
        return True
    status = getattr(e, "status_code", None)
    return status in (400, 401, 403, 404, 413, 422)


# ═══════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════

def main():
    root_probe = tk.Tk()
    root_probe.withdraw()
    missing = ensure_dependencies(root_probe)
    root_probe.destroy()
    app = App()
    if missing:
        app._log(f"Missing packages: {', '.join(missing)} — install with: "
                 f"python -m pip install {' '.join(missing)}", "warn")
    app.mainloop()


if __name__ == "__main__":
    main()
