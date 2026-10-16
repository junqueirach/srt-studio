#!/usr/bin/env python3
"""
╔═══════════════════════════════════════════════════════════╗
║          SRT Studio  v0.9.0 — Desktop GUI                 ║
║     (formerly SRT Subtitle Translator, renamed in 0.9.0)  ║
║  Subtitle translation and repair, structure preserved:    ║
║  SRT · ASS/SSA · WebVTT · MicroDVD · SAMI · TTML          ║
║  Engines: Claude API · MyMemory (free)                    ║
║  Author:  Luiz Junqueira & Claude AI                      ║
╚═══════════════════════════════════════════════════════════╝

v0.9.0 changes:
  • Renamed to SRT Studio; settings imported once from the old file
  • New layout: toolbar, adjustable left/right divider (proportional on
    resize), fixed left column with Options summary, one Subtitles table
    (filters, search, detail strip), status bar, app icon, DPI awareness
  • Every text subtitle format through pysubs2 (ASS styles/tags kept);
    output in the same format or always SRT; picture subtitles refused
  • Source check and repair (orphan text kept, timings, order, numbering,
    ad and credit lines) with Review / Repair / Save repaired copy
  • "Translated by AI" notice block in the target language
  • 32 languages, detection by script then by words ("unknown" not wrong)
  • Recent files, sample from the middle, estimate vs actual log + history,
    output encoding option, Save log, Open folder link, one cost format
  • Fixed: ",048" milliseconds read as 480 ms; text after a blank line
    inside a block was dropped

v0.8.1 changes (fixes):
  • Settings and subtitles are saved safely: locked, written to a temp file
    and then replaced; an unreadable settings file is kept as a .corrupt copy
  • "Translation finished" message with the full real cost (this run, the
    estimate, the total for this subtitle incl. sample and name detection)
    and where the prices came from; cost also shown after a failed save or a
    cancel; a failed save is no longer reported as "Done" (Save as… offered)
  • Names belong to one subtitle: loading a different file clears the list
    (asks to save unsaved names first); a run never clears it
  • Subtitles saved as UTF-16/UTF-32 ("Unicode" in Notepad) load; they
    were rejected with "No subtitle blocks found"
  • Shorter model labels (full details in the tooltip)
  • Built-in prices re-checked (Sonnet 5.5 cache read $0.10)

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
from tkinter import ttk, filedialog, messagebox, scrolledtext, simpledialog


# ═══════════════════════════════════════════════════════════════════════
# VERSION
# ═══════════════════════════════════════════════════════════════════════

APP_VERSION = "v0.9.0"
APP_NAME    = "SRT Studio"          # formerly "SRT Subtitle Translator" (renamed in v0.9.0)
APP_TITLE   = f"{APP_NAME}  {APP_VERSION}"
APP_ID      = "SRTStudio.App"       # Windows taskbar identity (icon grouping)
IS_FROZEN   = bool(getattr(sys, "frozen", False))
APP_DIR     = Path(sys.executable).parent if IS_FROZEN else Path(__file__).resolve().parent


# ═══════════════════════════════════════════════════════════════════════
# DEPENDENCIES  —  imported lazily, installed on demand (never at import)
# ═══════════════════════════════════════════════════════════════════════

REQUIRED_PACKAGES = [
    # (import name, pip name, why)
    ("requests",    "requests",    "MyMemory engine and pricing download"),
    ("anthropic",   "anthropic",   "Claude API engine"),
    ("pysubs2",     "pysubs2",     "subtitle formats other than SRT (ASS, SSA, WebVTT, MicroDVD…)"),
    ("tkinterdnd2", "tkinterdnd2", "drag and drop of files onto the window"),
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

CONFIG_PATH = Path.home() / ".srt_studio_config.json"
OLD_CONFIG_PATH = Path.home() / ".srt_translator_config.json"     # SRT Translator ≤ v0.8.1
CONFIG_VERSION = 3
_CONFIG_LOCK = threading.RLock()     # save_config runs on the main thread and on catalog threads
CONFIG_WARNINGS: list = []           # shown in the Activity Log at start


def _atomic_write_text(path: Path, text: str, encoding: str = "utf-8"):
    """Write to <path>.tmp, then replace the target: a failure never leaves a cut-off file."""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    try:
        with open(tmp, "w", encoding=encoding, newline="") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException as e:
        try:
            tmp.unlink()
        except OSError:
            pass
        if isinstance(e, OSError) and e.filename and str(e.filename).endswith(".tmp"):
            raise OSError(e.errno, e.strerror, str(path)) from e     # name the real file, not the temp one
        raise


def load_config() -> dict:
    """The saved settings. A file that is not valid JSON is copied to
    .srt_translator_config.json.corrupt-<date-time> (once) and {} is returned."""
    with _CONFIG_LOCK:
        if not CONFIG_PATH.exists():
            _import_old_config()
        if not CONFIG_PATH.exists():
            return {}
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception as e:
            backup = CONFIG_PATH.with_name(f"{CONFIG_PATH.name}.corrupt-{datetime.now():%Y%m%d-%H%M%S}")
            try:
                if not backup.exists():
                    backup.write_bytes(CONFIG_PATH.read_bytes())
                CONFIG_WARNINGS.append(f"Settings file could not be read ({e}). A copy was kept as "
                                       f"{backup.name}; the app started with default settings.")
            except OSError:
                CONFIG_WARNINGS.append(f"Settings file could not be read ({e}); default settings used.")
            return {}


def _import_old_config():
    """First start after the rename: copy the SRT Translator settings (API key, glossary, catalog…) into the
    new settings file. The old file is left untouched as a backup."""
    old = OLD_CONFIG_PATH
    if CONFIG_PATH.exists() or not old.exists() or old == CONFIG_PATH:
        return
    try:
        data = json.loads(old.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return
        data["config_version"] = CONFIG_VERSION
        data["imported_from"] = str(old)
        _atomic_write_text(CONFIG_PATH, json.dumps(data, indent=2))
        CONFIG_WARNINGS.append(f"Settings imported from {old.name} (SRT Translator). The old file was kept.")
    except Exception as e:
        CONFIG_WARNINGS.append(f"Could not import the settings of SRT Translator ({old.name}): {e}")


def save_config(data: dict):
    """Merge data into the saved settings (locked, written atomically)."""
    with _CONFIG_LOCK:
        try:
            existing = load_config()
            existing.update(data)
            existing["config_version"] = CONFIG_VERSION
            _atomic_write_text(CONFIG_PATH, json.dumps(existing, indent=2))
        except Exception as e:
            CONFIG_WARNINGS.append(f"Settings could not be saved: {e}")


# ═══════════════════════════════════════════════════════════════════════
# THEME & COLORS
# ═══════════════════════════════════════════════════════════════════════

COLORS = {   # v0.9.0 palette (approved mockup)
    "bg_dark":      "#121924",     # window and right side
    "bg_mid":       "#0f151f",     # status bar
    "bg_card":      "#1a2331",     # left column, tabs, dialogs
    "bg_input":     "#222d3e",     # fields, buttons
    "border":       "#2c384b",
    "text":         "#dfe6ef",
    "text_dim":     "#8d9aac",
    "text_bright":  "#f3f6fa",
    "accent":       "#3d8bfd",
    "accent_soft":  "#8ab8ff",
    "accent2":      "#bc8cff",
    "success":      "#5cc97a",
    "warning":      "#f2b33d",
    "error":        "#ff8b84",
    "yellow":       "#ffd166",
    "translated":   "#a8e0b6",
    "btn_primary":  "#2ea043",
    "btn_hover":    "#3fb950",
    "btn_danger":   "#b93a33",
    "key_bg":       "#172030",     # action card
    "drop_active":  "#1c3355",
    "drop_border":  "#34445b",
    "select":       "#1f3250",
    "head":         "#1d2737",
    "detail_bg":    "#182130",
    "chip_ok_fg":   "#6fd08a", "chip_ok_bg":   "#15281b", "chip_ok_bd":   "#1f5a2c",
    "chip_warn_bg": "#2d2716", "chip_warn_bd": "#6b5420",
    "chip_bad_bg":  "#2c1817", "chip_bad_bd":  "#6d2b28",
    "chip_sel_fg":  "#cfe0ff", "chip_sel_bg":  "#1c3355", "chip_sel_bd":  "#2f5ea8",
}

FONTS = {
    "title":   ("Segoe UI", 16, "bold"),
    "heading": ("Segoe UI", 12, "bold"),
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


_BOMS = [  # longest first: the UTF-32 LE mark starts with the UTF-16 LE mark
    (b"\xff\xfe\x00\x00", "utf-32"), (b"\x00\x00\xfe\xff", "utf-32"),
    (b"\xef\xbb\xbf", "utf-8-sig"), (b"\xff\xfe", "utf-16"), (b"\xfe\xff", "utf-16"),
]


def _sniff_utf16(raw: bytes):
    """UTF-16 without a byte-order mark: most ASCII characters leave a zero byte in every other position."""
    head = raw[:4096]
    if len(head) < 8:
        return None
    even, odd = head[0::2], head[1::2]
    if odd.count(0) > 0.3 * len(odd) and even.count(0) < 0.05 * len(even):
        return "utf-16-le"
    if even.count(0) > 0.3 * len(even) and odd.count(0) < 0.05 * len(odd):
        return "utf-16-be"
    return None


def decode_subtitle_bytes(raw: bytes) -> tuple:
    """(text, encoding_name). Byte-order marks first (UTF-8, UTF-16 and UTF-32, as Windows Notepad's
    "Unicode" saves), then UTF-16 without a mark, then UTF-8 and the Western codepages."""
    for bom, enc in _BOMS:
        if raw.startswith(bom):
            try:
                return raw.decode(enc).lstrip("﻿"), enc if enc == "utf-8-sig" else f"{enc}+bom"
            except UnicodeDecodeError:
                break
    enc = _sniff_utf16(raw)
    if enc:
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            pass
    for enc in _ENCODINGS:
        try:
            text = raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
        if "\x00" in text:          # binary or a UTF-16/32 variant we did not recognise: not this encoding
            continue
        return text, enc
    return raw.decode("latin-1", errors="replace").replace("\x00", ""), "latin-1 (lossy)"


def _read_text(filepath: str) -> tuple:
    """Read a subtitle file in whatever encoding it uses. Returns (text, encoding_name_used)."""
    with open(filepath, "rb") as f:
        return decode_subtitle_bytes(f.read())


def parse_srt_text(content: str) -> list:
    """Parse SRT text into blocks. Blocks with no text are kept (empty list). Text without a timing line is
    attached to the previous block (v0.9.0: it used to be dropped silently)."""
    blocks, _ = parse_srt_text_ex(content)
    for b in blocks:
        b.pop("_no_number", None)
    return blocks


def parse_srt(filepath: str) -> tuple:
    """Returns (blocks, encoding_used)."""
    content, enc = _read_text(filepath)
    return parse_srt_text(content), enc


def srt_text(blocks: list) -> str:
    parts = ["﻿"]
    for block in blocks:
        parts.append(f"{block['id']}\r\n{block['timestamp']}\r\n")
        for line in block["text_lines"]:
            parts.append(f"{line}\r\n")
        parts.append("\r\n")
    return "".join(parts)


def write_srt(blocks: list, filepath: str, encoding: str = "utf-8-sig"):
    """UTF-8 with BOM (default), CRLF. Written to a temp file first, so a failure never leaves half a subtitle."""
    write_subtitle_text(srt_text(blocks), filepath, encoding)


def timestamp_ms(timestamp: str) -> tuple:
    """'00:01:02,345 --> 00:01:04,000' → (62345, 64000). (0, 0) if unparsable."""
    m = _TS_RE.search(timestamp)
    if not m:
        return 0, 0
    g = m.groups()
    # Milliseconds from the digits as written: ",048" is 48 ms, ",5" is 500 ms (v0.9.0 fix: ",048" read as 480)
    start = ((int(g[0]) * 60 + int(g[1])) * 60 + int(g[2])) * 1000 + int(g[3].ljust(3, "0"))
    end   = ((int(g[4]) * 60 + int(g[5])) * 60 + int(g[6])) * 1000 + int(g[7].ljust(3, "0"))
    return start, end


def ms_to_srt_time(ms: int) -> str:
    ms = max(0, int(round(ms)))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, rem = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{rem:03d}"


def make_timestamp(start_ms: int, end_ms: int) -> str:
    return f"{ms_to_srt_time(start_ms)} --> {ms_to_srt_time(end_ms)}"


# ═══════════════════════════════════════════════════════════════════════
# SUBTITLE FORMATS  (v0.9.0 · F1)  —  SRT by the app's own parser, the rest by pysubs2
# ═══════════════════════════════════════════════════════════════════════

TEXT_FORMATS = {   # extension → (pysubs2 format id, label)
    ".srt":  ("srt", "SRT"),
    ".ass":  ("ass", "ASS"),
    ".ssa":  ("ssa", "SSA"),
    ".vtt":  ("vtt", "WebVTT"),
    ".sub":  ("microdvd", "MicroDVD"),
    ".smi":  ("sami", "SAMI"),
    ".sami": ("sami", "SAMI"),
    ".ttml": ("ttml", "TTML"),
    ".txt":  (None, "TXT (MPL2/TMP)"),
}
PICTURE_EXTS = {".sup": "PGS (Blu-ray)", ".idx": "VobSub (DVD)"}
OPEN_FILETYPES = [("Subtitles", " ".join(f"*{e}" for e in TEXT_FORMATS)), ("SRT", "*.srt"),
                  ("ASS / SSA", "*.ass *.ssa"), ("WebVTT", "*.vtt"), ("All files", "*.*")]
DEFAULT_FPS = 23.976
_ASS_DRAWING_RE = re.compile(r"\{[^}]*\\p[1-9]")


class SubtitleError(Exception):
    pass


class NeedsFrameRate(SubtitleError):
    """A frame-based file (MicroDVD) without a frame-rate line: ask the user."""


def _pysubs2():
    import pysubs2  # noqa: F401  (lazy: only needed for formats other than SRT)
    return pysubs2


def picture_subtitle_reason(path: str, raw: bytes = b""):
    """Text for a picture-based subtitle (needs OCR), None for a text subtitle."""
    ext = Path(path).suffix.lower()
    if ext in PICTURE_EXTS:
        return f"{PICTURE_EXTS[ext]} is a picture subtitle"
    if ext == ".sub" and (raw[:4] == b"\x00\x00\x01\xba" or Path(path).with_suffix(".idx").exists()):
        return "VobSub (DVD) .sub/.idx is a picture subtitle"
    return None


class SubDoc:
    """A loaded subtitle: the app's block list plus what is needed to write it back in its own format."""

    def __init__(self, path, fmt, label, encoding, blocks, ssa=None, fps=None, problems=None):
        self.path, self.fmt, self.label, self.encoding = path, fmt, label, encoding
        self.blocks, self.ssa, self.fps = blocks, ssa, fps
        self.problems = problems or []
        self.removed_events = set()      # ASS/VTT event indexes removed by the repair (ad lines)

    @property
    def is_srt(self) -> bool:
        return self.fmt == "srt"

    @property
    def ext(self) -> str:
        return Path(self.path).suffix.lower() or ".srt"


def _blocks_from_ssa(ssa) -> list:
    blocks = []
    for i, ev in enumerate(ssa.events):
        if ev.is_comment or _ASS_DRAWING_RE.search(ev.text or ""):
            continue              # comments and drawings are kept in the file, never translated
        lines = (ev.text or "").replace("\\n", "\\N").split("\\N")
        blocks.append({"id": str(len(blocks) + 1), "timestamp": make_timestamp(ev.start, ev.end),
                       "text_lines": [l.strip() for l in lines], "_ev": i})
    return blocks


def load_subtitle(path: str, fps: float = None) -> SubDoc:
    """Read any supported text subtitle. Raises SubtitleError (or NeedsFrameRate) with a clear message."""
    path = str(path).strip()
    ext = Path(path).suffix.lower()
    with open(path, "rb") as f:
        raw = f.read()
    reason = picture_subtitle_reason(path, raw)
    if reason:
        raise SubtitleError(f"{reason}: it needs text recognition (OCR), which is not supported. "
                            "Use a text subtitle (SRT, ASS, VTT…) of the same film.")
    if ext not in TEXT_FORMATS:
        raise SubtitleError(f"'{ext or 'no extension'}' is not a subtitle format the app reads. "
                            f"Supported: {', '.join(TEXT_FORMATS)}.")
    text, enc = decode_subtitle_bytes(raw)
    fmt, label = TEXT_FORMATS[ext]
    if fmt == "srt":
        blocks, problems = parse_srt_text_ex(text)
        return SubDoc(path, "srt", "SRT", enc, blocks, problems=problems)
    pysubs2 = _pysubs2()
    declared = fmt == "microdvd" and re.match(r"\s*\{1\}\{1\}\s*[\d.]+", text)
    if fmt == "microdvd" and fps is None and not declared:
        raise NeedsFrameRate("This MicroDVD file has no frame-rate line; choose the video's frame rate.")
    try:
        # A declared frame rate ({1}{1}23.976) is read by pysubs2 itself; passing one would turn that line into text
        ssa = pysubs2.SSAFile.from_string(text, format_=fmt, fps=None if declared else fps)
    except Exception as e:
        raise SubtitleError(f"Could not read the {label} file: {e}") from e
    if fmt == "microdvd":
        fps = getattr(ssa, "fps", None) or fps
    fmt = fmt or ssa.format or "srt"
    label = {"mpl2": "MPL2", "tmp": "TMP"}.get(fmt, label)
    return SubDoc(path, fmt, label, enc, _blocks_from_ssa(ssa), ssa=ssa, fps=fps)


def output_extension(doc: SubDoc, output_format: str) -> str:
    if output_format == "srt" or doc is None:
        return ".srt"
    return doc.ext


def render_subtitle(doc: SubDoc, blocks: list, output_format: str = "same") -> str:
    """The text of the translated file. SRT sources (or 'always SRT' from an SRT source) use the app's own
    writer; other formats are rebuilt from the source file so styles, comments and drawings stay as they were."""
    if doc is None or doc.is_srt:
        return srt_text(blocks)
    pysubs2 = _pysubs2()
    ssa = _copy_ssa(doc.ssa)
    by_ev = {b["_ev"]: b for b in blocks if "_ev" in b}
    for i, ev in enumerate(ssa.events):
        b = by_ev.get(i)
        if b is not None:
            ev.text = "\\N".join(b["text_lines"])
            if b.get("_repaired"):
                ev.start, ev.end = timestamp_ms(b["timestamp"])
    for i in sorted(doc.removed_events, reverse=True):
        del ssa.events[i]
    notices = [b for b in blocks if b.get("_notice")]
    for b in notices:
        s, e = timestamp_ms(b["timestamp"])
        style = "Default" if "Default" in ssa.styles else (next(iter(ssa.styles), "Default"))
        ev = pysubs2.SSAEvent(start=s, end=e, text="\\N".join(b["text_lines"]), style=style)
        if b.get("_notice") == "end":
            ssa.events.append(ev)
        else:
            ssa.events.insert(0, ev)
    fmt = "srt" if output_format == "srt" else doc.fmt
    kwargs = {"fps": doc.fps} if fmt == "microdvd" else {}
    out = ssa.to_string(fmt, **kwargs)
    if fmt == "microdvd":   # pysubs2 < 1.9 writes the frame-rate line as {0}{0}, which it cannot read back
        out = re.sub(r"\A\{0\}\{0\}", "{1}{1}", out)
    return out


def _copy_ssa(ssa):
    import copy
    return copy.deepcopy(ssa)


def output_encoding_for(choice: str, source_encoding: str, text: str, is_srt: bool) -> tuple:
    """(python encoding, note). choice: 'utf-8-sig' | 'utf-8' | 'same'. Falls back to UTF-8 with BOM when the
    source encoding cannot hold the translated text."""
    if choice == "utf-8":
        return "utf-8", ""
    if choice == "same":
        src = (source_encoding or "").lower().replace("+bom", "")
        if src.startswith("latin-1 ("):
            src = ""
        if src in ("utf-16", "utf-32"):
            return src, ""
        if src:
            try:
                text.encode(src)
                return src, ""
            except (UnicodeEncodeError, LookupError):
                return "utf-8-sig", (f"The translation has characters that {source_encoding} cannot hold; "
                                     "written as UTF-8 with BOM instead.")
    return "utf-8-sig", ""


def write_subtitle_text(text: str, path: str, encoding: str = "utf-8-sig"):
    """Atomic write; the SRT writer already starts with a BOM character, so it is not doubled."""
    _atomic_write_text(Path(path), text.lstrip("\ufeff"), encoding=encoding)   # the codec writes any BOM


# ═══════════════════════════════════════════════════════════════════════
# SOURCE CHECK & REPAIR  (v0.9.0 · R1)
# ═══════════════════════════════════════════════════════════════════════

_STRICT_TS_RE = re.compile(r"^\d\d:\d\d:\d\d,\d{3} --> \d\d:\d\d:\d\d,\d{3}$")
PROBLEM_LABELS = {
    "orphan_text":      "Text without a timing line",
    "bad_timestamp":    "Timing line cannot be read",
    "end_before_start": "Ends before it starts",
    "zero_duration":    "Zero duration",
    "overlap":          "Overlaps the next block",
    "out_of_order":     "Out of time order",
    "bad_number":       "Block number missing, repeated or out of sequence",
    "odd_format":       "Timing written in a non-standard way",
    "ad_line":          "Advertising or credit line",
}
AD_PATTERNS = [
    r"opensubtitles", r"\baddic7ed\b", r"\bpodnapisi\b", r"\bsubscene\b", r"\byifysubtitles\b",
    r"\bexplosiveskull\b", r"\bsubdl\b",
    r"advertise your product", r"support us and become vip", r"(?:^|\s)www\.[\w-]+\.\w{2,}",
    r"https?://",
    r"\bsubtitles?\s+(?:by|downloaded|ripped|synced|corrected|edited|provided|created)\b",
    r"\bsync(?:ed|hronized)?\s*(?:and|&)\s*correct", r"\bcorrected by\b", r"\bripped by\b",
    r"\bsubtitulad[oa]s?\s+por\b", r"\btraducci[oó]n(?:\s+y\s+sincronizaci[oó]n)?\s+(?:por|de)\b",
    r"\blegendas?\s+(?:por|by|feitas|sincronizadas)\b", r"^\s*tradu[cç][aã]o\s*:", r"\bsincroniza[cç][aã]o\s*:",
    r"\bsous-titres?\s+(?:par|réalisés)\b", r"\buntertitel\s+(?:von|by)\b", r"\bsottotitoli\s+(?:a cura|di|by)\b",
]
_AD_STRONG = re.compile("|".join(AD_PATTERNS[:11]), re.I)     # sites and URLs: anywhere in the film
_AD_CREDIT = re.compile("|".join(AD_PATTERNS[11:]), re.I)     # credit phrases: near the start or the end only
AD_EDGE_MS = (5 * 60_000, 10 * 60_000)                         # first 5 min, last 10 min


def parse_srt_text_ex(content: str) -> tuple:
    """(blocks, problems). Text without a timing line is attached to the previous block (never dropped)
    and reported as 'orphan_text'."""
    blocks, problems = [], []
    content = content.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    chunks, cur, cur_start = [], [], 0          # blank (or whitespace-only) lines separate blocks
    for no, raw_line in enumerate(content.split("\n"), 1):
        if raw_line.strip():
            if not cur:
                cur_start = no
            cur.append(raw_line.strip())
        elif cur:
            chunks.append((cur_start, cur))
            cur = []
    if cur:
        chunks.append((cur_start, cur))
    for start_line, lines in chunks:
        if len(lines) >= 2 and "-->" in lines[1]:
            blocks.append({"id": lines[0], "timestamp": lines[1], "text_lines": list(lines[2:])})
        elif len(lines) >= 1 and "-->" in lines[0]:
            # Missing index line: synthesise one so structure stays valid
            blocks.append({"id": str(len(blocks) + 1), "timestamp": lines[0], "text_lines": lines[1:],
                           "_no_number": True})
        elif blocks:
            blocks[-1]["text_lines"].extend(lines)
            problems.append({"kind": "orphan_text", "block": len(blocks) - 1, "line": start_line,
                             "detail": f"line {start_line}: \u201c{' / '.join(lines)[:60]}\u201d added to block "
                                       f"{blocks[-1]['id']}"})
        else:
            problems.append({"kind": "orphan_text", "block": None, "line": start_line,
                             "detail": f"line {start_line}: text before the first block: "
                                       f"\u201c{' / '.join(lines)[:60]}\u201d"})
    return blocks, problems


def is_ad_block(block: dict, start_ms: int, film_end_ms: int, extra_patterns=()) -> bool:
    text = " ".join(block.get("text_lines", []))
    if not text.strip() or len(block.get("text_lines", [])) > 4:
        return False
    if _AD_STRONG.search(text):
        return True
    for p in extra_patterns:
        try:
            if p.strip() and re.search(p, text, re.I):
                return True
        except re.error:
            if p.strip().lower() in text.lower():
                return True
    near_edge = start_ms <= AD_EDGE_MS[0] or start_ms >= film_end_ms - AD_EDGE_MS[1]
    return near_edge and bool(_AD_CREDIT.search(text))


def check_subtitle(doc_or_blocks, extra_ad_patterns=(), is_srt=True, parse_problems=()) -> list:
    """Problems in the loaded source: [{'kind','block','detail'}]. Non-SRT formats (ASS…) are checked for
    ad lines and impossible durations only: their events may overlap and are not sorted by design."""
    blocks = doc_or_blocks.blocks if isinstance(doc_or_blocks, SubDoc) else doc_or_blocks
    problems = [dict(p) for p in parse_problems]
    times = []
    for b in blocks:
        m = _TS_RE.search(b["timestamp"])
        times.append(timestamp_ms(b["timestamp"]) if m else None)
    film_end = max((t[1] for t in times if t), default=0)
    seen_ids, prev_num = set(), 0
    for i, b in enumerate(blocks):
        t = times[i]
        if t is None:
            problems.append({"kind": "bad_timestamp", "block": i, "detail": f"\u201c{b['timestamp'][:60]}\u201d"})
            continue
        s, e = t
        if is_ad_block(b, s, film_end, extra_ad_patterns):
            problems.append({"kind": "ad_line", "block": i, "detail": " / ".join(b["text_lines"])[:80]})
        if e < s:
            problems.append({"kind": "end_before_start", "block": i, "detail": b["timestamp"]})
        elif e == s:
            problems.append({"kind": "zero_duration", "block": i, "detail": b["timestamp"]})
        if not is_srt:
            continue
        if not _STRICT_TS_RE.match(b["timestamp"].strip()):
            problems.append({"kind": "odd_format", "block": i, "detail": b["timestamp"]})
        num = b["id"].strip()
        if b.get("_no_number") or not num.isdigit():
            problems.append({"kind": "bad_number", "block": i, "detail": f"number \u201c{num}\u201d"})
        else:
            n = int(num)
            if n in seen_ids:
                problems.append({"kind": "bad_number", "block": i, "detail": f"number {n} repeated"})
            elif n != prev_num + 1:
                problems.append({"kind": "bad_number", "block": i,
                                 "detail": (f"numbering starts at {n}, not 1" if prev_num == 0
                                            else f"number {n} follows {prev_num}")})
            seen_ids.add(n)
            prev_num = n
        j = i + 1
        while j < len(blocks) and times[j] is None:
            j += 1
        if j < len(blocks):
            ns, _ = times[j]
            if ns < s:
                problems.append({"kind": "out_of_order", "block": j,
                                 "detail": f"block {blocks[j]['id']} starts before block {b['id']}"})
            elif e - ns > 100:
                problems.append({"kind": "overlap", "block": i,
                                 "detail": f"{e - ns} ms into block {blocks[j]['id']}"})
    return problems


def repair_blocks(blocks: list, problems: list, remove_ads: bool = True, is_srt: bool = True) -> tuple:
    """(repaired_blocks, log_lines, removed_indexes). In memory only; the source file is not touched.
    SRT: drop ad blocks (optional), sort by start, renumber, standard timing, fix end<=start, trim overlaps.
    Other formats: drop ad lines and fix impossible durations only (no sorting, overlaps are allowed).
    Blocks whose timing cannot be read are kept exactly as they are."""
    log, removed = [], []
    ad_idx = {p["block"] for p in problems if p["kind"] == "ad_line"} if remove_ads else set()
    work = []
    for i, b in enumerate(blocks):
        if i in ad_idx:
            removed.append(i)
            log.append(f"removed ad/credit line: {' / '.join(b['text_lines'])[:70]}")
            continue
        nb = {**b, "text_lines": list(b["text_lines"])}
        nb.pop("_no_number", None)
        work.append((i, nb))
    if is_srt:
        def key(item):
            i, b = item
            return timestamp_ms(b["timestamp"])[0] if _TS_RE.search(b["timestamp"]) else None
        last, keyed = 0, []
        for item in work:                 # unreadable timings keep their place after the previous block
            k = key(item)
            last = k if k is not None else last
            keyed.append((last, item[0], item))
        ordered = [it for _, _, it in sorted(keyed, key=lambda x: (x[0], x[1]))]
        if [i for i, _ in ordered] != [i for i, _ in work]:
            log.append("blocks sorted by start time")
        work = ordered
    out = [b for _, b in work]
    for k, b in enumerate(out):
        if not _TS_RE.search(b["timestamp"]):
            continue
        s, e = timestamp_ms(b["timestamp"])
        nxt = next((timestamp_ms(x["timestamp"])[0] for x in out[k + 1:] if _TS_RE.search(x["timestamp"])), None)
        if e <= s:
            e2 = s + 1000
            if nxt is not None and nxt > s:
                e2 = min(e2, nxt - 1)
            log.append(f"block {b['id']}: end set to {ms_to_srt_time(e2)} (was {ms_to_srt_time(e)})")
            e = e2
        if is_srt and nxt is not None and e - nxt > 100 and nxt > s:
            log.append(f"block {b['id']}: overlap of {e - nxt} ms trimmed")
            e = nxt - 1
        new_ts = make_timestamp(s, e)
        if is_srt and new_ts != b["timestamp"].strip():
            if timestamp_ms(b["timestamp"]) == (s, e):
                log.append(f"block {b['id']}: timing rewritten in the standard form")
            b["timestamp"] = new_ts
            b["_repaired"] = True
        elif not is_srt and (s, e) != timestamp_ms(b["timestamp"]):
            b["timestamp"] = new_ts
            b["_repaired"] = True
    if is_srt:
        renum = sum(1 for k, b in enumerate(out) if b["id"].strip() != str(k + 1))
        for k, b in enumerate(out):
            b["id"] = str(k + 1)
        if renum:
            log.append(f"{renum} block number(s) corrected (1..{len(out)})")
    return out, log, removed


# ═══════════════════════════════════════════════════════════════════════
# "TRANSLATED BY AI" NOTICE  (v0.9.0 · N1)
# ═══════════════════════════════════════════════════════════════════════

NOTICE_TEXTS = {
    "en": "Subtitles translated by AI ({model})",
    "pt": "Legendas traduzidas por IA ({model})",
    "es": "Subtítulos traducidos por IA ({model})",
    "fr": "Sous-titres traduits par IA ({model})",
    "de": "Untertitel von KI übersetzt ({model})",
    "it": "Sottotitoli tradotti con IA ({model})",
    "nl": "Ondertiteling vertaald door AI ({model})",
    "sv": "Undertexter översatta av AI ({model})",
    "nb": "Undertekster oversatt av KI ({model})",
    "da": "Undertekster oversat af AI ({model})",
    "fi": "Tekstitys käännetty tekoälyllä ({model})",
    "pl": "Napisy przetłumaczone przez AI ({model})",
    "cs": "Titulky přeložila AI ({model})",
    "hu": "A feliratot MI fordította ({model})",
    "ro": "Subtitrare tradusă de IA ({model})",
    "tr": "Altyazılar yapay zekâ ile çevrildi ({model})",
    "el": "Υπότιτλοι μεταφρασμένοι από ΤΝ ({model})",
    "ru": "Субтитры переведены ИИ ({model})",
    "uk": "Субтитри перекладено ШІ ({model})",
    "he": "כתוביות תורגמו בבינה מלאכותית ({model})",
    "ar": "ترجمة الحوار بالذكاء الاصطناعي ({model})",
    "hi": "उपशीर्षक का अनुवाद एआई द्वारा ({model})",
    "th": "คำบรรยายแปลโดย AI ({model})",
    "vi": "Phụ đề được dịch bởi AI ({model})",
    "id": "Subtitle diterjemahkan oleh AI ({model})",
    "ja": "AIによる翻訳字幕（{model}）",
    "ko": "AI 번역 자막 ({model})",
    "zh-CN": "字幕由AI翻译（{model}）",
    "zh-TW": "字幕由AI翻譯（{model}）",
}
NOTICE_START_MS = 500
NOTICE_MIN_GAP_MS = 1500
NOTICE_CLEARANCE_MS = 200


def notice_text_for(target_code: str, model_label: str, custom: str = "") -> str:
    if custom.strip():
        return custom.strip().replace("{model}", model_label)
    t = NOTICE_TEXTS.get(target_code) or NOTICE_TEXTS.get(target_code.split("-")[0].lower()) or NOTICE_TEXTS["en"]
    return t.format(model=model_label)


def _notice_prefixes(custom: str = "") -> list:
    out = [t.split("{model}")[0].rstrip(" (（") for t in NOTICE_TEXTS.values()]
    if custom.strip():
        out.append(custom.split("{model}")[0].strip())
    return [p for p in out if p]


def has_ai_notice(blocks: list, custom: str = "") -> bool:
    prefixes = _notice_prefixes(custom)
    for b in blocks[:1] + blocks[-1:]:
        text = " ".join(b["text_lines"]).strip()
        if any(text.startswith(p) for p in prefixes):
            return True
    return False


def add_ai_notice(blocks: list, text: str, seconds: float = 4, custom: str = "") -> tuple:
    """(new_blocks, where): where = 'start' | 'end' | None (already present or empty input). Renumbers 1..N+1.
    The notice ends at least 200 ms before the first dialogue; with less than 1.5 s of room it goes at the end."""
    if not blocks or has_ai_notice(blocks, custom):
        return blocks, None
    dur = int(seconds * 1000)
    starts = [timestamp_ms(b["timestamp"]) for b in blocks if _TS_RE.search(b["timestamp"])]
    first = min((s for s, _ in starts), default=0)
    last_end = max((e for _, e in starts), default=0)
    room = first - NOTICE_CLEARANCE_MS - NOTICE_START_MS
    if first >= NOTICE_MIN_GAP_MS and room >= 800:
        end = NOTICE_START_MS + min(dur, room)
        notice = {"id": "0", "timestamp": make_timestamp(NOTICE_START_MS, end), "text_lines": [text],
                  "_notice": "start"}
        out, where = [notice] + [dict(b) for b in blocks], "start"
    else:
        s = last_end + 1000
        notice = {"id": "0", "timestamp": make_timestamp(s, s + dur), "text_lines": [text], "_notice": "end"}
        out, where = [dict(b) for b in blocks] + [notice], "end"
    for k, b in enumerate(out):
        b["id"] = str(k + 1)
    return out, where


# ═══════════════════════════════════════════════════════════════════════
# SMALL HELPERS  (v0.9.0 · M1)
# ═══════════════════════════════════════════════════════════════════════

RECENT_LIMIT = 8
COST_HISTORY_LIMIT = 50


def push_recent(recent: list, path: str, limit: int = RECENT_LIMIT) -> list:
    """Newest first, no duplicates (same file in another spelling counts as the same), at most `limit`."""
    out = [path] + [p for p in (recent or []) if not same_file(p, path)]
    return out[:limit]


def prune_recent(recent: list) -> list:
    return [p for p in (recent or []) if p and Path(p).exists()]


def middle_ellipsis(text: str, max_chars: int) -> str:
    """'Don't Let Go (2019) […] Horror].en.srt': keeps the start and the end (language tag, extension)."""
    if len(text) <= max_chars or max_chars < 8:
        return text
    keep = max_chars - 1
    tail = max(keep // 2, min(18, keep - 4))
    head = keep - tail
    return text[:head].rstrip() + "…" + text[-tail:].lstrip()


def pick_sample(blocks: list, n: int = 20, where: str = "middle") -> int:
    """Start index of the sample. 'start' = 0. 'middle' = the n consecutive blocks with the most words per
    minute after the first 10 % of the film (opening credits and music are usually at the start)."""
    if where != "middle" or len(blocks) <= n:
        return 0
    words = [len(re.findall(r"[^\W\d_]{2,}", " ".join(b["text_lines"]))) for b in blocks]
    times = [timestamp_ms(b["timestamp"]) for b in blocks]
    lo = max(0, len(blocks) // 10)
    best_i, best = lo, -1.0
    total = sum(words[lo:lo + n])
    for i in range(lo, len(blocks) - n + 1):
        if i > lo:
            total += words[i + n - 1] - words[i - 1]
        span = max(1, times[i + n - 1][1] - times[i][0])
        score = total / (span / 60000) if span > 1 else 0
        if score > best:
            best, best_i = score, i
    return best_i


def estimate_vs_actual(est: dict, usage, cost) -> str:
    """'Estimate ~$0.0186 · actual $0.0281 (+51 %) · in 29,810 → 82,260 · out 27,087 → 39,420'."""
    if not est or est.get("total_cost") is None or cost is None:
        return ""
    e = est["total_cost"]
    diff = f" ({(cost - e) / e * 100:+.0f} %)" if e else ""
    real_in = usage.input + usage.cache_read + usage.cache_write
    return (f"Estimate ~{format_usd(e)} · actual {format_usd(cost)}{diff} · input tokens "
            f"{est.get('input_tokens', 0):,} → {real_in:,} · output {est.get('output_tokens', 0):,} → {usage.output:,}")


def cost_history_entry(model_id: str, n_blocks: int, est: dict, usage, cost) -> dict:
    return {"date": datetime.now().strftime("%Y-%m-%d %H:%M"), "model": model_id, "blocks": n_blocks,
            "est_in": int((est or {}).get("input_tokens") or 0), "est_out": int((est or {}).get("output_tokens") or 0),
            "est_cost": (est or {}).get("total_cost"),
            "in": usage.input + usage.cache_read + usage.cache_write, "out": usage.output, "cost": cost}


def push_cost_history(history: list, entry: dict, limit: int = COST_HISTORY_LIMIT) -> list:
    return ((history or []) + [entry])[-limit:]


# ═══════════════════════════════════════════════════════════════════════
# LANGUAGE DETECTION & BATCH SIZE
# ═══════════════════════════════════════════════════════════════════════

_SCRIPTS = [   # (name, letters of the script)
    ("kana", r"[\u3040-\u30ff]"), ("hangul", r"[\uac00-\ud7af\u1100-\u11ff]"), ("han", r"[\u4e00-\u9fff]"),
    ("thai", r"[\u0e00-\u0e7f]"), ("hebrew", r"[\u0590-\u05ff]"), ("arabic", r"[\u0600-\u06ff]"),
    ("devanagari", r"[\u0900-\u097f]"), ("greek", r"[\u0370-\u03ff]"), ("cyrillic", r"[\u0400-\u04ff]"),
]
_SCRIPT_LANG = {"hangul": "ko-KR", "thai": "th-TH", "hebrew": "he-IL", "arabic": "ar-AR",
                "devanagari": "hi-IN", "greek": "el-GR"}
_TRAD_CHARS = set("這們個來說時會為還麼對見點後發開關國過話學們嗎聽讓謝")
_SIMP_CHARS = set("这们个来说时会为还么对见点后发开关国过话学吗听让谢")
# Words that are common in one Latin-script language and rare in the others (shared words left out).
_LATIN_WORDS = [
    ("en-US", "the and is are you have what this that with not but they was will would could how who where when why"),
    ("pt-BR", "não nao você voce está uma isso ele ela tem são sao muito então entao também fazer quando obrigado agora"),
    ("es-ES", "los las pero más muy usted tiene son puede hacer cuando gracias ahora estoy eso aquí"),
    ("fr-FR", "les des une est pas pour dans avec qui sur sont mais plus tout peut cette aussi faire comme je vous"),
    ("de-DE", "und der die das ist nicht ein eine ich sie wir auf mit den von hat für sind auch aber oder wenn"),
    ("it-IT", "che non una per sono come più questo anche della quello hanno essere fare tutto cosa"),
    ("nl-NL", "het een niet dat wat zijn voor maar hij zij ook naar weet goed hier"),
    ("sv-SE", "och att är jag inte vad hur varför mig dig det som har på kan"),
    ("nb-NO", "hva meg deg seg noe kanskje ikke jeg det er og har ikkje"),
    ("da-DK", "hvad mig dig sig noget måske ikke jeg det er og har"),
    ("fi-FI", "ja on ei se että mitä minä sinä tämä kun niin mutta hän olen"),
    ("pl-PL", "nie się że to jest jak co tak ale już mnie czy jestem"),
    ("cs-CZ", "je se že na co jak ale tak jsem není už mi to"),
    ("hu-HU", "és az hogy nem egy is van mit ez meg csak"),
    ("ro-RO", "și nu este că în pe ce cu un mai sunt"),
    ("tr-TR", "ve bir bu ne için değil ben sen ama çok var mı"),
    ("id-ID", "yang dan tidak ini itu saya kamu apa dengan untuk ada aku"),
    ("vi-VN", "và không là của tôi có một này được anh em"),
]
_LATIN_RE = [(code, re.compile(r"(?<!\w)(?:" + "|".join(map(re.escape, words.split())) + r")(?!\w)"))
             for code, words in _LATIN_WORDS]


def detect_language(blocks: list) -> str:
    """Language code of the subtitle, or "" when it cannot be told (the user then picks).
    First by script (Thai, Cyrillic, Greek, Hebrew, Arabic, Devanagari, Hangul, Kana, Han), then by common
    words for Latin-script languages. Never a confident wrong guess."""
    sample = " ".join(" ".join(b["text_lines"]) for b in blocks[:200]).lower()
    sample = _TAG_RE.sub(" ", sample)
    letters = len(re.findall(r"[^\W\d_]", sample))
    if not letters:
        return ""
    counts = {name: len(re.findall(rx, sample)) for name, rx in _SCRIPTS}
    cjk = counts["kana"] + counts["han"]
    if counts["kana"] >= 10 and counts["kana"] >= 0.1 * cjk:
        return "ja-JP"
    name, n = max(counts.items(), key=lambda kv: kv[1])
    if n >= 20 and n >= 0.3 * letters:
        if name == "han":
            trad = sum(1 for ch in sample if ch in _TRAD_CHARS)
            simp = sum(1 for ch in sample if ch in _SIMP_CHARS)
            return "zh-TW" if trad > simp else "zh-CN"
        if name == "cyrillic":
            return "uk-UA" if len(re.findall(r"[іїєґ]", sample)) >= 5 else "ru-RU"
        if name in _SCRIPT_LANG:
            return _SCRIPT_LANG[name]
    scores = sorted(((len(rx.findall(sample)), code) for code, rx in _LATIN_RE), reverse=True)
    (best, code), (second, _) = scores[0], scores[1]
    if best >= 8 and best >= 1.25 * second:
        return code
    return ""


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
    "sdh", "cc", "forced", "hi", "uk", "ukr", "ro", "ron", "rum", "id", "ind", "vie", "heb", "tha", "gre", "ell",
    "hun", "ces", "cze", "nob", "nno", "nb", "swe", "fin", "pob", "pb", "esp", "lat", "latam", "chs", "cht",
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


def default_output_name(input_path: str, target_code: str, ext: str = ".srt") -> str:
    return f"{strip_language_tag(Path(input_path).stem)}.{target_code}{ext}"


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


def same_file(a: str, b: str) -> bool:
    if not a or not b:
        return False
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def saved_names_for(cfg_value, path: str) -> str:
    """Names saved in the config for this subtitle file ('' for another file or the old v0.8.0 string)."""
    if isinstance(cfg_value, dict) and same_file(cfg_value.get("file", ""), path):
        return str(cfg_value.get("names") or "")
    return ""


def names_unsaved(current: list, saved: list) -> bool:
    """True when the list holds names that are not in the subtitle's .names.txt."""
    return bool({c.lower() for c in current} - {s.lower() for s in saved})


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

# $ per million tokens — verified 2026-10-15 against the official pricing page
# (v0.8.1: Sonnet 5.5 cache read corrected from $0.20 to $0.10).
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
    "sonnet 5.5": {"input": 2.0,  "output": 10.0, "cache_read": 0.10, "cache_write": 2.5},
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


def _short_price(x: float) -> str:
    """0.1 → '$0.10', 2.0 → '$2', 2.5 → '$2.5'."""
    return f"${x:.2f}" if x < 1 else f"${x:g}"


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

    def _label_parts(self, model_id: str) -> tuple:
        m, p = self.model(model_id), self.price(model_id)
        ctx = m.get("max_input_tokens")
        ctx_s = f"{ctx // 1000}K" if ctx and ctx < 1_000_000 else ("1M" if ctx else "?")
        return m, p, ctx_s

    def label(self, model_id: str) -> str:
        """Short drop-down label: 'Claude Haiku 5.5 · $0.10/$0.50 · 1M ★' (fits the column)."""
        m, p, ctx_s = self._label_parts(model_id)
        price_s = (f"{_short_price(p['input'])}/{_short_price(p['output'])}" if p["input"] is not None
                   else "price ?")
        tag = " ★" if model_id == DEFAULT_MODEL else (" (older)" if re.search(r"-\d{8}$", model_id) else "")
        return f"{m['display_name']} · {price_s} · {ctx_s}{tag}"

    def long_label(self, model_id: str) -> str:
        """Full description for the tooltip."""
        m, p, ctx_s = self._label_parts(model_id)
        price_s = (f"${p['input']:g} input / ${p['output']:g} output per million tokens ({p['source']} prices)"
                   if p["input"] is not None else "Price unknown")
        tag = ("\n★ Recommended: the cheapest current model" if model_id == DEFAULT_MODEL
               else ("\nOlder model" if re.search(r"-\d{8}$", model_id) else ""))
        return f"{m['display_name']}  ({model_id})\n{price_s}\nContext window: {ctx_s} tokens{tag}"


# ═══════════════════════════════════════════════════════════════════════
# COST ESTIMATE & USAGE
# ═══════════════════════════════════════════════════════════════════════

_OUTPUT_RATIO = {"ja": 0.9, "zh": 0.8, "ko": 0.9, "ar": 1.0, "de": 1.1, "pt": 1.15,
                 "es": 1.15, "fr": 1.15, "it": 1.1, "en": 1.0, "th": 1.6, "hi": 1.6, "ru": 1.3,
                 "uk": 1.3, "el": 1.4, "he": 1.0}


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


BUILTIN_PRICES_CHECKED = "15 Oct 2026"


def format_usd(x) -> str:
    """$0.0171 under one dollar, $1.23 from one dollar; 'unknown' for None."""
    if x is None:
        return "unknown"
    return f"${x:.4f}" if x < 1 else f"${x:,.2f}"


def price_source_text(catalog, price: dict) -> tuple:
    """(text, trustworthy) saying where the price used for a cost came from."""
    if price.get("input") is None:
        return "price unknown: tokens are shown, the cost could not be calculated", False
    src = price.get("source")
    if src == "override":
        return f"your {PRICING_OVERRIDE_PATH.name} file", True
    if src in ("live", "cache"):
        when = (datetime.fromtimestamp(catalog.prices_fetched_at).strftime("%d %b %Y")
                if getattr(catalog, "prices_fetched_at", 0) else "date unknown")
        return f"Anthropic pricing page, updated {when}", True
    return f"built-in prices (checked {BUILTIN_PRICES_CHECKED}); they may be out of date", False


class CostLedger:
    """Paid API use for the subtitle that is loaded now. Cleared when another file is loaded."""

    LABELS = {"translation": "run", "sample": "sample", "names": "names"}

    def __init__(self):
        self.entries = []

    def clear(self):
        self.entries = []

    def add(self, kind: str, model_id: str, usage: "UsageTotals", price: dict):
        cost = usage.cost(price)
        self.entries.append({"kind": kind, "model": model_id, "input": usage.input, "output": usage.output,
                             "cache_read": usage.cache_read, "cache_write": usage.cache_write,
                             "calls": usage.calls, "cost": cost})
        return cost

    def total(self):
        """Sum of all entries; None if any entry has an unknown price."""
        if any(e["cost"] is None for e in self.entries):
            return None
        return sum(e["cost"] for e in self.entries)

    def breakdown(self) -> str:
        """'run $0.0171 + sample $0.0031 + names $0.0011' (counts shown when a kind repeats)."""
        parts = []
        for kind in ("translation", "sample", "names"):
            es = [e for e in self.entries if e["kind"] == kind]
            if not es:
                continue
            costs = [e["cost"] for e in es]
            amount = format_usd(None if None in costs else sum(costs))
            label = self.LABELS[kind] + (f" ×{len(es)}" if len(es) > 1 else "")
            parts.append(f"{label} {amount}")
        return " + ".join(parts)


def finish_summary(result: dict) -> tuple:
    """(dialog, status_text) after a run.
    dialog: 'finished' (saved), 'save_failed', or None (sample, cancel, error)."""
    paid = result.get("engine") == "claude"
    cost = format_usd(result.get("cost")) if paid else "free"
    n_flag = result.get("flagged", 0)
    flags = f"{n_flag} block(s) flagged" if n_flag else "no blocks flagged"
    if result.get("cancelled"):
        return None, (f"Cancelled — cost so far {cost}" if paid else "Cancelled")
    if result.get("save_error"):
        return "save_failed", f"Not saved — {result['save_error']}"
    if not result.get("ok"):
        return None, "Completed with errors — check the Activity Log" + (f" · cost {cost}" if paid else "")
    if result.get("sample"):
        return None, f"Sample done — {result.get('total', 0)} blocks · {flags} · cost {cost}"
    name = Path(result.get("saved_path") or "").name
    return "finished", f"Done — saved {name} · {flags} · cost {cost}"


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
            "ko-KR": "ko", "zh-CN": "zh-CN", "zh-TW": "zh-TW", "ar-AR": "ar", "nb-NO": "no",
            "th-TH": "th", "ru-RU": "ru", "uk-UA": "uk", "pl-PL": "pl", "nl-NL": "nl", "sv-SE": "sv",
            "da-DK": "da", "fi-FI": "fi", "cs-CZ": "cs", "hu-HU": "hu", "ro-RO": "ro", "el-GR": "el",
            "tr-TR": "tr", "he-IL": "he", "hi-IN": "hi", "id-ID": "id", "vi-VN": "vi"}


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
    ("zh-TW",    "Chinese — Traditional",    "🇹🇼"),
    ("cs-CZ",    "Czech",                    "🇨🇿"),
    ("da-DK",    "Danish",                   "🇩🇰"),
    ("nl-NL",    "Dutch",                    "🇳🇱"),
    ("en-GB",    "English — UK",             "🇬🇧"),
    ("en-US",    "English — US",             "🇺🇸"),
    ("fi-FI",    "Finnish",                  "🇫🇮"),
    ("fr-FR",    "French",                   "🇫🇷"),
    ("de-DE",    "German",                   "🇩🇪"),
    ("el-GR",    "Greek",                    "🇬🇷"),
    ("he-IL",    "Hebrew",                   "🇮🇱"),
    ("hi-IN",    "Hindi",                    "🇮🇳"),
    ("hu-HU",    "Hungarian",                "🇭🇺"),
    ("id-ID",    "Indonesian",               "🇮🇩"),
    ("it-IT",    "Italian",                  "🇮🇹"),
    ("ja-JP",    "Japanese",                 "🇯🇵"),
    ("ko-KR",    "Korean",                   "🇰🇷"),
    ("nb-NO",    "Norwegian",                "🇳🇴"),
    ("pl-PL",    "Polish",                   "🇵🇱"),
    ("pt-BR",    "Portuguese — Brazilian",   "🇧🇷"),
    ("pt-PT",    "Portuguese — European",    "🇵🇹"),
    ("ro-RO",    "Romanian",                 "🇷🇴"),
    ("ru-RU",    "Russian",                  "🇷🇺"),
    ("es-LATAM", "Spanish — Latin American", "🇲🇽"),
    ("es-ES",    "Spanish — European",       "🇪🇸"),
    ("sv-SE",    "Swedish",                  "🇸🇪"),
    ("th-TH",    "Thai",                     "🇹🇭"),
    ("tr-TR",    "Turkish",                  "🇹🇷"),
    ("uk-UA",    "Ukrainian",                "🇺🇦"),
    ("vi-VN",    "Vietnamese",               "🇻🇳"),
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
Subtitle translator and repair tool (formerly "SRT Subtitle Translator").

WHAT IT DOES
------------
Opens a text subtitle (SRT, ASS/SSA, WebVTT, MicroDVD, SAMI, TTML),
checks it for problems, translates every dialogue block into the
chosen language and saves a new subtitle with the same structure:
timings and line counts are kept, ASS styles and positions too.

THE WINDOW
----------
Toolbar        Open… (Ctrl+O), Recent ▾ (the last 8 files), Settings,
               Help.
Left side      The job: SOURCE (file, format, encoding, blocks,
               language, Repair status, Context file), LANGUAGES,
               ENGINE (provider and model), OPTIONS (summary and
               Edit…), then the estimated cost and Start / Sample /
               Cancel.
Right side     Subtitles, Names and Log tabs (Ctrl+1, 2, 3).
Divider        Drag the divider between the two sides to make either
               side wider; when the window is resized both sides keep
               their proportion. Double-click the divider (or
               Settings → General → Reset layout) to go back to the
               default. The position is remembered.
Status bar     What is happening, the progress bar, the last cost and
               an "Open folder" link after a saved run.
Keyboard       Ctrl+O open · Ctrl+Enter start · Esc cancel a run ·
               Ctrl+1/2/3 tabs · Ctrl+S save the log (Log tab).

NEW IN v0.9.0
-------------
New name       SRT Studio (formerly SRT Subtitle Translator). Your
               settings, API key and names are imported once from the
               old settings file, which is kept as it was.
New layout     Toolbar, adjustable divider, one Subtitles table
               (source and translation side by side), status bar.
               Nothing scrolls in the left column.
All formats    SRT, ASS/SSA, WebVTT (.vtt), MicroDVD (.sub, asks for
               the frame rate if the file does not say it), SAMI
               (.smi), TTML, MPL2/TMP (.txt). Output: the same format
               as the source (ASS stays ASS, styles intact) or always
               SRT (Settings → Output). Picture subtitles (.sup PGS,
               VobSub .idx/.sub) need OCR and are refused.
Repair         On load the subtitle is checked: text without a timing
               line (kept, never dropped), unreadable timings, ends
               before it starts, zero duration, overlaps, wrong order,
               block numbers, non-standard timing, and ad or credit
               lines ("Subtitles by …", "www.OpenSubtitles.org",
               "Subtitulado por …"). SOURCE › Repair › Review… lists
               them; Repair fixes them in the app (the file on disk is
               not changed unless you "Save repaired copy…", which
               writes a .bak first when it replaces the original).
               ASS files may overlap by design: only ad lines and
               impossible durations are checked there.
AI notice      A full run adds one short block in the target language
               at the start, e.g. "Legendas traduzidas por IA (Claude
               Haiku 5.5)", ending at least 0.2 s before the first
               dialogue (at the end if there is no room). Options or
               Settings → Output: on/off, your own text, seconds.
Languages      32 languages, incl. Thai, Russian, Ukrainian, Greek,
               Hebrew, Hindi, Polish, Dutch, Swedish, Norwegian,
               Danish, Finnish, Czech, Hungarian, Romanian, Turkish,
               Indonesian, Vietnamese, Chinese Traditional. Detection
               by alphabet first, then by common words; "language ?"
               when it cannot tell (pick it in LANGUAGES).
Sample from    Sample (20 blocks) from the middle (busiest dialogue
               after the opening) or from the start.
Encoding       Settings → Output: UTF-8 with BOM (default), UTF-8
               without BOM, or the same as the source (falls back to
               UTF-8 with BOM when the source encoding cannot hold the
               translation).
Estimate vs    After every Claude run the Log shows the estimate next
actual         to the real cost and tokens; the last 50 runs are kept
               to improve the estimate later.
Save log…      Log tab: saves the Activity Log as a text file.
Drag and drop  Drop a subtitle anywhere on the window (needs the
               tkinterdnd2 package; the app offers to install it).

SUBTITLES TAB
-------------
One row per block: number, time, source, translation, ⚑ flag.
Show: All · Flagged (quality-control warnings) · Repaired. Search
finds text or a block number. The strip under the table shows the
selected block in full. The translation column fills while a run is
going.

NEW IN v0.8.1
-------------
Finish message When a translation is saved, a "Translation finished"
               message shows the file, the flagged blocks, the real
               cost of this run next to the estimate, the total for
               this subtitle (run + sample runs + name detection) and
               where the prices came from. Turn it off in Settings →
               OUTPUT ("Show a message when a translation finishes").
               If saving fails, the message says why, shows what the
               run cost, and offers Save as… so the work is not lost.
Names per file The names list belongs to the subtitle that is loaded.
               Loading a different subtitle clears it (and loads that
               subtitle's own .names.txt). If the list has names that
               are not saved, the app asks first.
Unicode files  Subtitles saved as UTF-16 or UTF-32 load.
Model labels   "Claude Haiku 5.5 · $0.10/$0.50 · 1M ★" (input /
               output price per million tokens, context, ★ =
               recommended). Hover for the full details.
Safe saving    Settings and subtitles are written to a temporary file
               first and then swapped in.

NAMES
-----
Names tab: one per line (people, schools, companies, brands).
"Auto-detect" asks Claude to list them from the file for you to
review. A <file>.names.txt next to the subtitle is loaded
automatically and can be saved with "Save next to the subtitle".

CONTEXT FILE
------------
SOURCE › Context › + add: the same film in another language (any
format). Only the lines around each batch (by time) are sent, so the
extra cost is small. Claude only.

QUALITY CONTROL
---------------
Each block is checked after the run: unchanged text, missing lines,
lost tags and missing names are flagged. Unchanged blocks are
retranslated once automatically. The QC report is in the Log;
flagged blocks are marked ⚑ in the Subtitles tab.

COST
----
Before a run the estimate shows the expected cost (approx., or exact
input count with ↻ exact). After a run the real cost comes from the
token counts the API reports: input, output and cached tokens, each
at its own price. The finish message shows the cost of this run, the
estimate, the total for this subtitle and where the prices came from.
Prices come from Anthropic's pricing page (refreshed daily); a
pricing.json next to the app overrides them; a built-in table is the
fallback.

SETTINGS (⚙)
------------
General   Claude API key (stored only on this computer, sent only to
          api.anthropic.com), models and prices with Refresh now,
          Reset layout.
Output    Show a message when a translation finishes; Output format
          (same as the source / always SRT); Encoding; AI notice
          (on/off, text, seconds).
Repair    Remove ad and credit lines when repairing; extra patterns.
Files     Where the settings file (~/.srt_studio_config.json) and the
          last output folder are.

OPTIONS (Edit…)
---------------
Batch size (blocks per API call), workers (simultaneous calls),
translate hearing-impaired cues, save next to the source file, AI
notice on/off, Sample from (middle / start).

TRANSLATION ENGINES
-------------------
Claude (recommended): needs an API key from console.anthropic.com.
Understands tone, humour, slang and context.
MyMemory (free): no key, literal, limited daily volume.
"""


ENGINE_HELP_TEXT = """\
TRANSLATION ENGINES
-------------------
The app can translate with two different services. Pick one in
ENGINE › Provider. Everything else (file loading, repair, structure
checks, output naming) works the same way for both.

CLAUDE (ANTHROPIC)  (recommended)
---------------------------------
What it is   Anthropic's Claude language models, called through
             your own API key from console.anthropic.com.

How it works The subtitle is cut into batches of blocks (Options →
             batch size). Each batch is sent with instructions
             about tone, names and line structure; several batches
             run at the same time (workers). The reply is checked
             block by block, anything missing or unchanged is sent
             again, and the real cost is reported.

Quality      Understands context, humour, slang, register and
             hearing-impaired cues. Keeps names from the Names
             list. Can use a context file in another language.

Cost         Pay per token. The estimate shows the price before
             you start; a 90-minute film costs a few cents with
             Haiku 5.5 and well under a dollar with the larger
             models. Prices come from Anthropic's pricing page and
             are refreshed daily.

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
try the app without an account or to check that a file opens.
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
# SMALL UI HELPERS
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
    """Stop the mouse wheel from changing a combobox/spinbox under the pointer."""
    widget.bind("<MouseWheel>", lambda e: "break")


# ═══════════════════════════════════════════════════════════════════════
# MAIN APP  (v0.9.0 · G1 layout: toolbar · adjustable left/right division · Subtitles table · status bar)
# ═══════════════════════════════════════════════════════════════════════

_GEOMETRY_RE = re.compile(r"^(\d{3,4})x(\d{3,4})([+-]\d+)([+-]\d+)$")
DEFAULT_GEOMETRY = "1280x800"
MIN_SIZE = (1100, 700)
DEFAULT_LEFT_PX = 460            # at the default width: long language names fit in full
LEFT_MIN_PX, RIGHT_MIN_PX, LEFT_MAX_SHARE = 420, 420, 0.60
SAMPLE_WHERE = [("middle", "middle"), ("start", "start")]
OUTPUT_FORMATS = [("same", "Same as the source (ASS stays ASS)"), ("srt", "Always SRT")]
OUTPUT_ENCODINGS = [("utf-8-sig", "UTF-8 with BOM (recommended)"), ("utf-8", "UTF-8 without BOM"),
                    ("same", "Same as the source")]
ENGINES = [("claude", "Claude (Anthropic)"), ("free", "MyMemory (free)")]


def clamp_left(width_px: int, left_px: int) -> int:
    """The divider position allowed for a window body of `width_px`."""
    hi = min(int(width_px * LEFT_MAX_SHARE), width_px - RIGHT_MIN_PX)
    return max(LEFT_MIN_PX, min(left_px, max(LEFT_MIN_PX, hi)))


def _set_dpi_awareness():
    """Sharp text on 125 % / 150 % displays (Windows). Must run before the first Tk window."""
    if os.name != "nt":
        return
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass


def asset_path(name: str) -> Path:
    """assets/ next to the app, or inside the frozen exe (PyInstaller's _MEIPASS)."""
    base = Path(getattr(sys, "_MEIPASS", "")) if IS_FROZEN and getattr(sys, "_MEIPASS", None) else APP_DIR
    return base / "assets" / name


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        cfg = load_config()
        self._cfg = cfg
        try:
            self._scale = float(self.tk.call("tk", "scaling")) / (96 / 72)
        except Exception:
            self._scale = 1.0
        win = cfg.get("window") if isinstance(cfg.get("window"), dict) else {}
        geo = win.get("geometry") or cfg.get("window_geometry", "")
        self.geometry(geo if _GEOMETRY_RE.match(geo or "") else self._geo_default())
        self.minsize(self.px(MIN_SIZE[0]), self.px(MIN_SIZE[1]))
        self.configure(bg=COLORS["bg_dark"])
        self._set_icon()

        self.catalog = Catalog(cfg)

        # State
        self.doc               = None
        self.source_blocks     = []
        self.translated_blocks = []      # what was written (incl. the AI notice)
        self._tr_lines         = {}      # source index → translated lines (for the table)
        self._flags            = {}      # source index → [qc kinds]
        self.context_blocks    = []
        self.qc_issues         = []
        self.problems          = []
        self._repair_log       = []
        self.input_path        = ""
        self.context_path      = ""
        self.output_path       = ""
        self._last_saved       = ""
        self._last_output_dir  = cfg.get("last_output_dir", "")
        self._api_key          = cfg.get("api_key") or os.environ.get("ANTHROPIC_API_KEY", "")
        self._settings_dlg     = None
        self._detected_code    = ""
        self._enc_short        = ""
        self._recent           = prune_recent(cfg.get("recent_files") or [])
        self._cost_history     = cfg.get("cost_history") or []
        self._left_ratio       = float(win.get("left_ratio") or 0) or None

        # Vars
        self.source_lang    = tk.StringVar(value=cfg.get("source_lang", "en-US"))
        self.target_lang    = tk.StringVar(value=cfg.get("target_lang", "pt-BR"))
        self.engine         = tk.StringVar(value=cfg.get("engine", "claude"))
        self.claude_model   = tk.StringVar(value=self.catalog.pick_default(cfg.get("claude_model", "")))
        self.same_folder    = tk.BooleanVar(value=cfg.get("same_folder", False))
        self.translate_cues = tk.BooleanVar(value=cfg.get("translate_cues", True))
        self.batch_size     = tk.IntVar(value=int(cfg.get("batch_size", 25)))
        self.workers        = tk.IntVar(value=int(cfg.get("workers", 5)))
        self.finish_message = tk.BooleanVar(value=cfg.get("finish_message", True))
        self.output_format  = tk.StringVar(value=cfg.get("output_format", "same"))
        self.output_enc     = tk.StringVar(value=cfg.get("output_encoding", "utf-8-sig"))
        notice = cfg.get("ai_notice") if isinstance(cfg.get("ai_notice"), dict) else {}
        self.notice_on      = tk.BooleanVar(value=notice.get("enabled", True))
        self.notice_text    = tk.StringVar(value=notice.get("text", ""))
        self.notice_secs    = tk.IntVar(value=int(notice.get("seconds", 4)))
        self.remove_ads     = tk.BooleanVar(value=cfg.get("remove_ads", True))
        self._ad_extra      = list(cfg.get("ad_patterns_extra") or [])
        self.sample_from    = tk.StringVar(value=cfg.get("sample_from", "middle"))
        self.progress_var   = tk.DoubleVar(value=0)
        self.status_text    = tk.StringVar(value="Open a subtitle to begin  (Ctrl+O, or drop a file on the window)")
        self._catalog_status = tk.StringVar(value="")
        self._names_count   = tk.StringVar(value="0 names")
        self.is_translating = False
        self.cancel_flag    = False
        self.cost_ledger    = CostLedger()
        self._last_est      = {}
        self._saved_glossary = cfg.get("glossary", "")
        self._filter        = tk.StringVar(value="all")
        self._search        = tk.StringVar(value="")

        self._ui_queue = queue.Queue()
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(40, self._drain_ui_queue)

        self.claude_model.trace_add("write", lambda *_: self._refresh_cost())
        self.target_lang.trace_add("write", lambda *_: (self._update_output_line(), self._refresh_cost(),
                                                         self._update_table_headings()))
        self.source_lang.trace_add("write", lambda *_: self._update_table_headings())
        for v in (self.translate_cues, self.batch_size):
            v.trace_add("write", lambda *_: (self._update_options_summary(), self._refresh_cost()))
        for v in (self.workers, self.same_folder, self.notice_on, self.sample_from, self.output_format):
            v.trace_add("write", lambda *_: (self._update_options_summary(), self._update_output_line()))
        self.engine.trace_add("write", self._on_engine_change)
        self._filter.trace_add("write", lambda *_: self._fill_table())
        self._search.trace_add("write", lambda *_: self._fill_table())
        self._on_engine_change()
        self._update_options_summary()
        self._update_names_count()
        self._show_empty_state()
        self._bind_keys()
        self.after(300, self._startup_refresh)

    # ── scaling helpers ──────────────────────────────────────────────

    def px(self, n: float) -> int:
        return int(round(n * self._scale))

    def _geo_default(self) -> str:
        w, h = self.px(1280), self.px(800)
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h = min(w, sw - 40), min(h, sh - 80)
        return f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 3)}"

    def _set_icon(self):
        self._icons = {}
        try:
            ico = asset_path("icon.ico")
            if os.name == "nt" and ico.exists():
                self.iconbitmap(default=str(ico))
            pngs = [asset_path(f"icon-{s}.png") for s in (16, 32, 48, 256)]
            imgs = [tk.PhotoImage(file=str(p)) for p in pngs if p.exists()]
            if imgs:
                self.iconphoto(True, *imgs)
            for s in (20, 64):
                p = asset_path(f"icon-{s}.png")
                if p.exists():
                    self._icons[s] = tk.PhotoImage(file=str(p))
        except Exception:
            pass

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

    def _settings_snapshot(self) -> dict:
        return {
            "api_key":           self._api_key,
            "claude_model":      self.claude_model.get(),
            "source_lang":       self.source_lang.get(),
            "target_lang":       self.target_lang.get(),
            "engine":            self.engine.get(),
            "batch_size":        self._int(self.batch_size, 25, 5, 60),
            "workers":           self._int(self.workers, 5, 1, 8),
            "same_folder":       self.same_folder.get(),
            "translate_cues":    self.translate_cues.get(),
            "last_output_dir":   self._last_output_dir,
            "glossary":          {"file": self.input_path, "names": self._glossary_text()},
            "finish_message":    self.finish_message.get(),
            "output_format":     self.output_format.get(),
            "output_encoding":   self.output_enc.get(),
            "ai_notice":         {"enabled": self.notice_on.get(), "text": self.notice_text.get(),
                                  "seconds": self._int(self.notice_secs, 4, 2, 10)},
            "remove_ads":        self.remove_ads.get(),
            "ad_patterns_extra": self._ad_extra,
            "sample_from":       self.sample_from.get(),
            "recent_files":      self._recent,
            "window":            {"geometry": self.winfo_geometry(), "left_ratio": self._left_ratio,
                                  "tab": self._current_tab_name()},
        }

    def _on_close(self):
        save_config(self._settings_snapshot())
        self.destroy()

    def _startup_refresh(self):
        for w in CONFIG_WARNINGS:
            self._log(w, "warn")
        CONFIG_WARNINGS.clear()
        if isinstance(self._saved_glossary, str) and self._saved_glossary.strip():
            self._log("The names list saved by v0.8.0 was not restored: names now belong to one subtitle "
                      "and are restored when that file is loaded again.", "info")
        if not self._dnd_ok:
            self._log("Drag and drop is off: the tkinterdnd2 package is missing "
                      "(python -m pip install tkinterdnd2). Use Open… instead.", "warn")
        self._log(f"Models: {len(self.catalog.models)} ({self.catalog.models_source})  •  "
                  f"Prices: {self.catalog.prices_source}"
                  + ("  •  pricing.json override active" if self.catalog.override else ""), "info")
        if self.catalog.override:
            self._log(f"Price override file: {PRICING_OVERRIDE_PATH}", "info")
        if self.catalog.prices_stale() or (self.catalog.models_stale() and self._api_key.strip()):
            self._refresh_catalog(force=False)

    # ── Styles & small widget helpers ────────────────────────────────

    def _style(self):
        style = ttk.Style()
        style.theme_use("default")
        C = COLORS
        style.configure("Lang.TCombobox", fieldbackground=C["bg_input"], background=C["bg_input"],
                        foreground=C["text"], selectbackground=C["bg_input"], selectforeground=C["text_bright"],
                        arrowcolor=C["text_dim"], bordercolor=C["border"], lightcolor=C["border"],
                        darkcolor=C["border"], padding=(6, 3))
        style.map("Lang.TCombobox", fieldbackground=[("readonly", C["bg_input"]), ("disabled", C["bg_card"])],
                  foreground=[("readonly", C["text"]), ("disabled", C["text_dim"])])
        self.option_add("*TCombobox*Listbox.background", C["bg_input"])
        self.option_add("*TCombobox*Listbox.foreground", C["text"])
        self.option_add("*TCombobox*Listbox.selectBackground", C["select"])
        self.option_add("*TCombobox*Listbox.font", FONTS["small"])
        style.configure("T.TNotebook", background=C["bg_dark"], borderwidth=0, tabmargins=(12, 6, 0, 0))
        style.configure("T.TNotebook.Tab", background=C["bg_dark"], foreground=C["text_dim"],
                        padding=[14, 6], font=FONTS["small"], borderwidth=0)
        style.map("T.TNotebook.Tab", background=[("selected", C["bg_card"])],
                  foreground=[("selected", C["text_bright"])])
        style.configure("P.Horizontal.TProgressbar", troughcolor=C["border"], background=C["accent"],
                        borderwidth=0, thickness=8)
        style.configure("Subs.Treeview", background=C["bg_card"], fieldbackground=C["bg_card"],
                        foreground=C["text"], rowheight=self.px(24), font=FONTS["small"], borderwidth=0)
        style.map("Subs.Treeview", background=[("selected", C["select"])],
                  foreground=[("selected", C["text_bright"])])
        style.configure("Subs.Treeview.Heading", background=C["head"], foreground=C["text_dim"],
                        font=FONTS["tiny"], relief="flat", borderwidth=0, padding=(6, 4))
        style.map("Subs.Treeview.Heading", background=[("active", C["head"])])
        style.configure("D.Vertical.TScrollbar", background=C["bg_input"], troughcolor=C["bg_card"],
                        arrowcolor=C["text_dim"], bordercolor=C["bg_card"])

    def _flat_btn(self, parent, text, cmd, primary=False, danger=False, dim=False, font=None, **kw):
        C = COLORS
        bg = kw.pop("bg", None) or (C["btn_primary"] if primary else C["btn_danger"] if danger else C["bg_input"])
        fg = "#ffffff" if (primary or danger) else C["text_dim"] if dim else C["text"]
        return tk.Button(parent, text=text, font=font or FONTS["small"], bg=bg, fg=fg, relief="flat", bd=0,
                         activebackground=C["btn_hover"] if primary else C["border"],
                         activeforeground=C["text_bright"], cursor="hand2", highlightthickness=0,
                         padx=kw.pop("padx", 12), pady=kw.pop("pady", 4), command=cmd, **kw)

    def _link(self, parent, text, cmd, bg=None, font=None):
        lbl = tk.Label(parent, text=text, font=font or FONTS["tiny"], fg=COLORS["accent"],
                       bg=bg or COLORS["bg_card"], cursor="hand2")
        lbl.bind("<Button-1>", lambda e: cmd())
        return lbl

    def _heading(self, parent, text, right=None):
        fr = tk.Frame(parent, bg=COLORS["bg_card"])
        tk.Label(fr, text=text, font=FONTS["badge"], fg=COLORS["accent"], bg=COLORS["bg_card"]).pack(side="left")
        if right:
            right(fr).pack(side="right")
        return fr

    def _chip(self, parent, text="", kind=""):
        C = COLORS
        fg, bg, bd = {"ok": (C["chip_ok_fg"], C["chip_ok_bg"], C["chip_ok_bd"]),
                      "warn": (C["warning"], C["chip_warn_bg"], C["chip_warn_bd"]),
                      "bad": (C["error"], C["chip_bad_bg"], C["chip_bad_bd"])}.get(
            kind, (C["text"], C["bg_input"], C["border"]))
        return tk.Label(parent, text=text, font=FONTS["tiny"], fg=fg, bg=bg, padx=7, pady=0,
                        highlightbackground=bd, highlightthickness=1)

    # ── UI build ─────────────────────────────────────────────────────

    def _build_ui(self):
        self._style()
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self._build_toolbar()
        self._paned = tk.PanedWindow(self, orient="horizontal", bg=COLORS["border"], sashwidth=self.px(6),
                                     sashrelief="flat", bd=0, opaqueresize=True, sashcursor="sb_h_double_arrow")
        self._paned.grid(row=1, column=0, sticky="nsew")
        left = tk.Frame(self._paned, bg=COLORS["bg_card"])
        right = tk.Frame(self._paned, bg=COLORS["bg_dark"])
        self._paned.add(left, minsize=self.px(LEFT_MIN_PX), stretch="always")
        self._paned.add(right, minsize=self.px(RIGHT_MIN_PX), stretch="always")
        self._left_frame, self._right_frame = left, right
        self._build_left(left)
        self._build_right(right)
        self._build_statusbar()
        self._paned.bind("<Configure>", self._on_paned_configure)
        self._paned.bind("<ButtonRelease-1>", self._on_sash_release)
        self._paned.bind("<Double-Button-1>", self._on_sash_double)
        Tooltip(self._paned, "Drag the divider to make either side wider. Double-click it to reset.")
        self._dnd_ok = False
        for w in (self._drop_zone, self._source_card, self.tree):
            self._dnd_ok = _try_enable_dnd(w, self._on_drop) or self._dnd_ok
        self._update_drop_text()

    # TOOLBAR ─────────────────────────────────────────────────────────
    def _build_toolbar(self):
        C = COLORS
        bar = tk.Frame(self, bg=C["bg_card"], height=self.px(44))
        bar.grid(row=0, column=0, sticky="ew")
        bar.pack_propagate(False)
        tk.Frame(self, bg=C["border"], height=1).grid(row=0, column=0, sticky="sew")
        brand = tk.Frame(bar, bg=C["bg_card"])
        brand.pack(side="left", padx=(self.px(12), self.px(18)))
        if 20 in self._icons:
            tk.Label(brand, image=self._icons[20], bg=C["bg_card"]).pack(side="left", padx=(0, 8))
        tk.Label(brand, text=APP_NAME, font=FONTS["heading"], fg=C["text_bright"], bg=C["bg_card"]).pack(side="left")
        tk.Label(brand, text=APP_VERSION.lstrip("v"), font=FONTS["tiny"], fg=C["text_dim"],
                 bg=C["bg_card"]).pack(side="left", padx=(6, 0), pady=(4, 0))
        b = self._flat_btn(bar, "Open…", self._browse, padx=12, pady=3, bg=C["bg_card"])
        b.configure(highlightbackground=C["border"], highlightthickness=1)
        b.pack(side="left", pady=self.px(8))
        Tooltip(b, "Open a subtitle: SRT, ASS/SSA, WebVTT, MicroDVD, SAMI, TTML  (Ctrl+O)")
        self._recent_btn = tk.Menubutton(bar, text="Recent ▾", font=FONTS["small"], bg=C["bg_card"], fg=C["text"],
                                         activebackground=C["border"], activeforeground=C["text_bright"],
                                         relief="flat", cursor="hand2", padx=12, pady=3, bd=0)
        self._recent_menu = tk.Menu(self._recent_btn, tearoff=False, bg=C["bg_input"], fg=C["text"],
                                    activebackground=C["select"], activeforeground=C["text_bright"],
                                    postcommand=self._fill_recent_menu)
        self._recent_btn.configure(menu=self._recent_menu)
        self._recent_btn.pack(side="left", padx=(6, 0))
        self._flat_btn(bar, "?  Help", self._show_help, bg=C["bg_card"], padx=12, pady=3).pack(side="right", padx=(4, 12))
        s = self._flat_btn(bar, "⚙  Settings", self._show_settings, bg=C["bg_card"], padx=12, pady=3)
        s.pack(side="right")
        Tooltip(s, "API key, prices, output format and encoding, AI notice, repair rules")

    # LEFT COLUMN ─────────────────────────────────────────────────────
    def _build_left(self, parent):
        C = COLORS
        self._build_action_card(parent)          # bottom first, so it is always visible
        col = tk.Frame(parent, bg=C["bg_card"])
        col.pack(side="top", fill="both", expand=True, padx=self.px(16), pady=(self.px(14), 0))
        self._left_col = col
        gap = self.px(14)

        # SOURCE
        card = tk.Frame(col, bg=C["bg_card"])
        card.pack(fill="x", expand=True, anchor="n")       # cards share the spare height evenly
        self._source_card = card
        self._heading(card, "SOURCE").pack(fill="x", pady=(0, 6))
        self.file_label = tk.Label(card, text="No subtitle loaded", font=FONTS["body"], fg=C["text_dim"],
                                   bg=C["bg_input"], anchor="w", padx=10, pady=6, cursor="hand2",
                                   highlightbackground=C["border"], highlightthickness=1)
        self.file_label.pack(fill="x")
        self.file_label.bind("<Button-1>", lambda e: self._browse())
        self.file_label.bind("<Configure>", lambda e: self._update_file_label())
        self._file_tip = Tooltip(self.file_label, "Click to open a subtitle, or drop one on the window")
        self._chips = tk.Frame(card, bg=C["bg_card"])
        self._chips.pack(fill="x", pady=(8, 0))
        self._hint = tk.Label(card, text="Open a subtitle (SRT, ASS, VTT, SUB…) with Open… or Ctrl+O.",
                              font=FONTS["tiny"], fg=C["text_dim"], bg=C["bg_card"], anchor="w", justify="left")
        self._hint.pack(fill="x", pady=(6, 0))

        def stat_row(label):
            r = tk.Frame(card, bg=C["bg_card"])
            tk.Label(r, text=label, width=8, anchor="w", font=FONTS["tiny"], fg=C["text_dim"],
                     bg=C["bg_card"]).pack(side="left")
            return r
        self._repair_row = stat_row("Repair")
        self._repair_chip = self._chip(self._repair_row)
        self._repair_chip.pack(side="left")
        self._repair_note = tk.Label(self._repair_row, text="", font=FONTS["tiny"], fg=C["text_dim"], bg=C["bg_card"])
        self._repair_note.pack(side="left", padx=(6, 0))
        self._repair_link = self._link(self._repair_row, "Review…", self._show_repair)
        self._repair_link.pack(side="right")
        self._ctx_row = stat_row("Context")
        self._ctx_label = tk.Label(self._ctx_row, text="none", font=FONTS["tiny"], fg=C["text_dim"],
                                   bg=C["bg_card"], anchor="w")
        self._ctx_label.pack(side="left", fill="x", expand=True)
        self._ctx_link = self._link(self._ctx_row, "+ add", self._ctx_action)
        self._ctx_link.pack(side="right")
        Tooltip(self._ctx_row, "Optional, Claude only: the same film in another language. Only the lines\n"
                               "around each batch (by time) are sent, so the extra cost is small.")

        # LANGUAGES
        card = tk.Frame(col, bg=C["bg_card"])
        card.pack(fill="x", pady=(gap, 0), expand=True, anchor="n")
        self._heading(card, "LANGUAGES").pack(fill="x", pady=(0, 6))
        row = tk.Frame(card, bg=C["bg_card"])
        row.pack(fill="x")
        row.columnconfigure(0, weight=1)
        row.columnconfigure(2, weight=1)
        self._src_combo, self._src_codes, self._src_combo_var = self._make_dropdown(row, self.source_lang)
        self._src_combo.grid(row=0, column=0, sticky="ew")
        swap = self._flat_btn(row, "⇄", self._swap_languages, font=FONTS["body"], padx=8, pady=1)
        swap.grid(row=0, column=1, padx=6)
        Tooltip(swap, "Swap source and target language")
        self._tgt_combo, self._tgt_codes, self._tgt_combo_var = self._make_dropdown(row, self.target_lang)
        self._tgt_combo.grid(row=0, column=2, sticky="ew")
        Tooltip(self._src_combo, "Language of the subtitle, detected from the file (by alphabet, then by\n"
                                 "common words). If it says 'not detected', pick it here.")
        Tooltip(self._tgt_combo, "Language to translate into. Remembered between sessions.")

        # ENGINE
        card = tk.Frame(col, bg=C["bg_card"])
        card.pack(fill="x", pady=(gap, 0), expand=True, anchor="n")
        self._heading(card, "ENGINE", lambda fr: self._link(fr, "? which one", self._show_engine_help)).pack(
            fill="x", pady=(0, 6))

        def labelled(text):
            r = tk.Frame(card, bg=C["bg_card"])
            r.pack(fill="x", pady=(0, 6))
            tk.Label(r, text=text, width=8, anchor="w", font=FONTS["tiny"], fg=C["text_dim"],
                     bg=C["bg_card"]).pack(side="left")
            return r
        r = labelled("Provider")
        self._engine_var = tk.StringVar(value=dict(ENGINES).get(self.engine.get(), ENGINES[0][1]))
        self._engine_combo = ttk.Combobox(r, textvariable=self._engine_var, values=[l for _, l in ENGINES],
                                          state="readonly", style="Lang.TCombobox", font=FONTS["small"])
        self._engine_combo.pack(side="left", fill="x", expand=True)
        self._engine_combo.bind("<<ComboboxSelected>>",
                                lambda e: self.engine.set(ENGINES[self._engine_combo.current()][0]))
        _no_wheel(self._engine_combo)
        Tooltip(self._engine_combo, "Claude: best quality, needs your API key (Settings).\n"
                                    "MyMemory: free, literal, no key, limited daily volume.")
        r = labelled("Model")
        self._model_combo_var = tk.StringVar()
        self._model_combo = ttk.Combobox(r, textvariable=self._model_combo_var, state="readonly",
                                         style="Lang.TCombobox", font=FONTS["small"])
        self._model_combo.pack(side="left", fill="x", expand=True)
        self._model_combo.bind("<<ComboboxSelected>>", self._on_model_selected)
        _no_wheel(self._model_combo)
        self._model_refresh_btn = self._flat_btn(r, "↻", lambda: self._refresh_catalog(force=True),
                                                 font=FONTS["small"], padx=8, pady=1)
        self._model_refresh_btn.pack(side="right", padx=(6, 0))
        self._model_tip = Tooltip(self._model_combo, "")
        Tooltip(self._model_refresh_btn, "Re-read the model list from the API and the prices from anthropic.com")
        self._fill_model_combo()

        # OPTIONS
        card = tk.Frame(col, bg=C["bg_card"])
        card.pack(fill="x", pady=(gap, 0), expand=True, anchor="n")
        self._heading(card, "OPTIONS", lambda fr: self._link(fr, "Edit…", self._show_options)).pack(
            fill="x", pady=(0, 4))
        self._opt_summary = tk.Label(card, text="", font=FONTS["tiny"], fg=C["text_dim"], bg=C["bg_card"],
                                     anchor="w", justify="left")
        self._opt_summary.pack(fill="x")
        self._out_line = tk.Label(card, text="", font=FONTS["tiny"], fg=C["text_dim"], bg=C["bg_card"],
                                  anchor="w", justify="left")
        self._out_line.pack(fill="x", pady=(2, 0))
        card.bind("<Configure>", lambda e: self._wrap_left_labels(e.width))

    def _wrap_left_labels(self, width):
        for w in (self._opt_summary, self._out_line, self._hint, self._cost_detail):
            try:
                w.configure(wraplength=max(200, width - 4))
            except tk.TclError:
                pass

    def _make_dropdown(self, parent, textvariable):
        values = [label for _, label, _ in LANGUAGES]      # Windows shows flag emoji as two letters: left out
        codes  = [code for code, _, _ in LANGUAGES]
        try:
            cur_idx = codes.index(textvariable.get())
        except ValueError:
            cur_idx = 0
        combo_var = tk.StringVar(value=values[cur_idx])
        combo = ttk.Combobox(parent, textvariable=combo_var, values=values, state="readonly",
                             style="Lang.TCombobox", font=FONTS["small"], height=20)
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

    # ACTION CARD ─────────────────────────────────────────────────────
    def _build_action_card(self, parent):
        C = COLORS
        bar = tk.Frame(parent, bg=C["key_bg"])
        bar.pack(side="bottom", fill="x")
        tk.Frame(bar, bg=C["border"], height=1).pack(fill="x")
        inner = tk.Frame(bar, bg=C["key_bg"])
        inner.pack(fill="x", padx=self.px(16), pady=(self.px(10), self.px(14)))
        top = tk.Frame(inner, bg=C["key_bg"])
        top.pack(fill="x")
        tk.Label(top, text="Estimated cost", font=FONTS["tiny"], fg=C["text_dim"], bg=C["key_bg"]).pack(side="left")
        self._cost_main = tk.Label(top, text="—", font=("Consolas", 15, "bold"), fg=C["text_dim"], bg=C["key_bg"])
        self._cost_main.pack(side="left", padx=(10, 0))
        self._cost_method = tk.Label(top, text="", font=FONTS["tiny"], fg=C["text_dim"], bg=C["key_bg"])
        self._cost_method.pack(side="left", padx=8)
        exact = self._link(top, "↻ exact", lambda: self._refresh_cost(exact=True), bg=C["key_bg"])
        exact.pack(side="right")
        Tooltip(exact, "Count the real input tokens with the free count_tokens endpoint (needs the API key)")
        self._cost_detail = tk.Label(inner, text="", font=FONTS["tiny"], fg=C["text_dim"], bg=C["key_bg"],
                                     anchor="w", justify="left")
        self._cost_detail.pack(fill="x", pady=(2, 8))
        self.start_btn = tk.Button(inner, text="▶  Start translation", font=FONTS["heading"],
                                   bg=C["btn_primary"], fg="#ffffff", relief="flat", bd=0,
                                   activebackground=C["btn_hover"], activeforeground="#ffffff",
                                   disabledforeground="#6f9a7a", cursor="hand2", pady=self.px(8),
                                   command=lambda: self._start(sample=False))
        self.start_btn.pack(fill="x")
        Tooltip(self.start_btn, "Translate the whole subtitle  (Ctrl+Enter)")
        row = tk.Frame(inner, bg=C["key_bg"])
        row.pack(fill="x", pady=(8, 0))
        row.columnconfigure(0, weight=1)
        row.columnconfigure(2, weight=1)
        self.sample_btn = self._flat_btn(row, f"◐  Sample ({SAMPLE_BLOCKS})", lambda: self._start(sample=True), pady=5)
        self.sample_btn.grid(row=0, column=0, sticky="ew")
        self._sample_where = ttk.Combobox(row, values=["from the middle", "from the start"], state="readonly",
                                          width=14, style="Lang.TCombobox", font=FONTS["tiny"])
        self._sample_where.current(0 if self.sample_from.get() == "middle" else 1)
        self._sample_where.bind("<<ComboboxSelected>>", lambda e: self.sample_from.set(
            "middle" if self._sample_where.current() == 0 else "start"))
        self._sample_where.grid(row=0, column=1, padx=6, sticky="ns")
        _no_wheel(self._sample_where)
        Tooltip(self.sample_btn, f"Translate {SAMPLE_BLOCKS} blocks only, show them in the table with the real\n"
                                 "cost, save nothing. 'From the middle' picks the busiest dialogue after the\n"
                                 "opening (credits and music are usually at the start).")
        self.cancel_btn = self._flat_btn(row, "✕  Cancel", self._cancel, pady=5)
        self.cancel_btn.grid(row=0, column=2, sticky="ew")
        self._set_cancel_state(False)

    def _set_cancel_state(self, active: bool):
        C = COLORS
        self.cancel_btn.configure(state="normal" if active else "disabled",
                                  bg=C["chip_bad_bg"] if active else C["key_bg"],
                                  fg=C["error"] if active else C["text_dim"])

    # RIGHT SIDE ──────────────────────────────────────────────────────
    def _build_right(self, parent):
        C = COLORS
        nb = ttk.Notebook(parent, style="T.TNotebook")
        nb.pack(fill="both", expand=True)
        self.notebook = nb
        self.TAB_SUBS, self.TAB_NAMES, self.TAB_LOG = 0, 1, 2
        self.TAB_COMPARE = self.TAB_PREVIEW = self.TAB_SUBS        # names used before v0.9.0

        t1 = tk.Frame(nb, bg=C["bg_card"])
        nb.add(t1, text="  Subtitles  ")
        self._build_subtitles_tab(t1)
        t2 = tk.Frame(nb, bg=C["bg_card"])
        nb.add(t2, text="  Names  ")
        self._build_names_tab(t2)
        t3 = tk.Frame(nb, bg=C["bg_card"])
        nb.add(t3, text="  Log  ")
        self._build_log_tab(t3)
        tab = (self._cfg.get("window") or {}).get("tab") if isinstance(self._cfg.get("window"), dict) else None
        if tab in ("names", "log"):
            nb.select({"names": 1, "log": 2}[tab])

    def _current_tab_name(self) -> str:
        try:
            return ["subtitles", "names", "log"][self.notebook.index(self.notebook.select())]
        except Exception:
            return "subtitles"

    # SUBTITLES TAB ───────────────────────────────────────────────────
    def _build_subtitles_tab(self, t):
        C = COLORS
        self._subs_host = t
        # empty state: a large drop zone with Open and the recent files
        dz = tk.Frame(t, bg=C["bg_card"])
        self._drop_zone = dz
        box = tk.Frame(dz, bg=C["bg_card"], highlightbackground=C["drop_border"], highlightthickness=2)
        box.pack(fill="both", expand=True, padx=self.px(26), pady=self.px(26))
        mid = tk.Frame(box, bg=C["bg_card"])
        mid.place(relx=0.5, rely=0.45, anchor="center")
        if 64 in self._icons:
            tk.Label(mid, image=self._icons[64], bg=C["bg_card"]).pack()
        self._drop_title = tk.Label(mid, text="", font=FONTS["heading"], fg=C["text_bright"], bg=C["bg_card"])
        self._drop_title.pack(pady=(12, 2))
        tk.Label(mid, text="SRT · ASS/SSA · WebVTT · MicroDVD (.sub) · SAMI · TTML", font=FONTS["small"],
                 fg=C["text_dim"], bg=C["bg_card"]).pack()
        self._flat_btn(mid, "Open subtitle…", self._browse, primary=True, padx=18, pady=6,
                       bg=C["accent"]).pack(pady=(14, 0))
        self._recent_box = tk.Frame(mid, bg=C["bg_card"])
        self._recent_box.pack(pady=(18, 0), fill="x")

        # table view
        tv = tk.Frame(t, bg=C["bg_card"])
        self._table_view = tv
        bar = tk.Frame(tv, bg=C["bg_card"])
        bar.pack(fill="x", padx=self.px(12), pady=(self.px(8), self.px(6)))
        tk.Label(bar, text="Show", font=FONTS["tiny"], fg=C["text_dim"], bg=C["bg_card"]).pack(side="left", padx=(0, 6))
        self._filter_btns = {}
        for key in ("all", "flagged", "repaired"):
            b = tk.Label(bar, text=key, font=FONTS["tiny"], padx=9, pady=1, cursor="hand2",
                         highlightthickness=1)
            b.pack(side="left", padx=(0, 6))
            b.bind("<Button-1>", lambda e, k=key: self._filter.set(k))
            self._filter_btns[key] = b
        se = tk.Entry(bar, textvariable=self._search, font=FONTS["tiny"], bg=C["bg_input"], fg=C["text"],
                      insertbackground=C["text"], relief="flat", highlightbackground=C["border"],
                      highlightthickness=1, width=26)
        se.pack(side="right", ipady=2)
        tk.Label(bar, text="Search", font=FONTS["tiny"], fg=C["text_dim"], bg=C["bg_card"]).pack(side="right", padx=6)

        detail = tk.Frame(tv, bg=C["detail_bg"], height=self.px(118))
        detail.pack(side="bottom", fill="x")
        detail.pack_propagate(False)
        tk.Frame(detail, bg=C["border"], height=1).pack(fill="x")
        self._detail_meta = tk.Label(detail, text="", font=FONTS["mono_sm"], fg=C["text_dim"], bg=C["detail_bg"],
                                     anchor="w")
        self._detail_meta.pack(fill="x", padx=self.px(14), pady=(6, 2))
        self._detail_text = tk.Text(detail, font=FONTS["small"], bg=C["detail_bg"], fg=C["text"], relief="flat",
                                    wrap="word", height=4, highlightthickness=0, padx=self.px(12), pady=0)
        self._detail_text.pack(fill="both", expand=True)
        self._detail_text.tag_configure("dst", foreground=C["translated"])
        self._detail_text.tag_configure("dim", foreground=C["text_dim"])
        self._detail_text.configure(state="disabled")

        frame = tk.Frame(tv, bg=C["bg_card"])
        frame.pack(fill="both", expand=True)
        cols = ("num", "time", "src", "dst", "flag")
        self.tree = ttk.Treeview(frame, columns=cols, show="headings", style="Subs.Treeview", selectmode="browse")
        widths = {"num": 54, "time": 180, "src": 300, "dst": 300, "flag": 34}
        for c in cols:
            self.tree.column(c, width=self.px(widths[c]), stretch=c in ("src", "dst"),
                             anchor="center" if c == "flag" else "w", minwidth=self.px(30))
        self.tree.heading("num", text="#", anchor="w")
        self.tree.heading("time", text="Time", anchor="w")
        self.tree.heading("flag", text="⚑")
        self._update_table_headings()
        sb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview, style="D.Vertical.TScrollbar")
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.tag_configure("flagged", foreground=C["warning"])
        self.tree.tag_configure("repaired", foreground=C["accent_soft"])
        self.tree.tag_configure("notr", foreground=C["text"])
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._show_detail())
        self._update_filter_buttons()

    def _update_table_headings(self):
        if not hasattr(self, "tree"):
            return
        src = _LANG_LABEL.get(self.source_lang.get(), self.source_lang.get())
        tgt = _LANG_LABEL.get(self.target_lang.get(), self.target_lang.get())
        self.tree.heading("src", text=f"Source · {src}", anchor="w")
        self.tree.heading("dst", text=f"Translation · {tgt}", anchor="w")

    def _show_empty_state(self):
        self._table_view.pack_forget()
        self._drop_zone.pack(fill="both", expand=True)
        for w in self._recent_box.winfo_children():
            w.destroy()
        self._recent = prune_recent(self._recent)
        for p in self._recent[:4]:
            r = tk.Frame(self._recent_box, bg=COLORS["bg_input"], highlightbackground=COLORS["border"],
                         highlightthickness=1, cursor="hand2")
            r.pack(fill="x", pady=2)
            name = tk.Label(r, text=middle_ellipsis(Path(p).name, 60), font=FONTS["small"], fg=COLORS["text"],
                            bg=COLORS["bg_input"], anchor="w", padx=10, pady=4, cursor="hand2")
            name.pack(side="left", fill="x", expand=True)
            when = datetime.fromtimestamp(Path(p).stat().st_mtime).strftime("%d %b") if Path(p).exists() else ""
            tk.Label(r, text=when, font=FONTS["tiny"], fg=COLORS["text_dim"], bg=COLORS["bg_input"],
                     padx=10).pack(side="right")
            for w in (r, name):
                w.bind("<Button-1>", lambda e, path=p: self._load_source_file(path))

    def _show_table(self):
        self._drop_zone.pack_forget()
        self._table_view.pack(fill="both", expand=True)

    def _update_drop_text(self):
        self._drop_title.configure(text="Drop a subtitle here" if self._dnd_ok else "Open a subtitle")

    def _update_filter_buttons(self):
        C = COLORS
        n_all = len(self.source_blocks)
        n_flag = len(self._flags)
        n_rep = sum(1 for b in self.source_blocks if b.get("_repaired"))
        labels = {"all": f"All {n_all:,}", "flagged": f"Flagged {n_flag}", "repaired": f"Repaired {n_rep}"}
        for key, b in self._filter_btns.items():
            on = self._filter.get() == key
            b.configure(text=labels[key], fg=C["chip_sel_fg"] if on else C["text"],
                        bg=C["chip_sel_bg"] if on else C["bg_card"],
                        highlightbackground=C["chip_sel_bd"] if on else C["border"])

    def _row_values(self, i, b):
        s, e = timestamp_ms(b["timestamp"]) if _TS_RE.search(b["timestamp"]) else (None, None)
        if s is None:
            tcol = b["timestamp"][:22]
        else:
            start, end = ms_to_srt_time(s), ms_to_srt_time(e)
            # the end is shortened to what differs: "00:01:59.329 → 02:02.123", "00:02:43.414 → 46.084"
            cut = 6 if start[:6] == end[:6] else 3 if start[:3] == end[:3] else 0
            tcol = f"{start.replace(',', '.')} → {end[cut:].replace(',', '.')}"
        src = " / ".join(l for l in b["text_lines"] if l.strip())
        dst = " / ".join(l for l in self._tr_lines.get(i, []) if l.strip()) if i in self._tr_lines else ""
        flag = "⚠" if i in self._flags else ""
        return (b["id"], tcol, src, dst, flag)

    def _fill_table(self):
        if not hasattr(self, "tree"):
            return
        self._update_filter_buttons()
        sel = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        f, q = self._filter.get(), self._search.get().strip().lower()
        for i, b in enumerate(self.source_blocks):
            if f == "flagged" and i not in self._flags:
                continue
            if f == "repaired" and not b.get("_repaired"):
                continue
            vals = self._row_values(i, b)
            if q and q not in " ".join(vals).lower():
                continue
            tags = ("flagged",) if i in self._flags else ("repaired",) if b.get("_repaired") else ()
            self.tree.insert("", "end", iid=str(i), values=vals, tags=tags)
        if sel and self.tree.exists(sel[0]):
            self.tree.selection_set(sel[0])
            self.tree.see(sel[0])
        self._show_detail()

    def _show_detail(self):
        sel = self.tree.selection()
        t = self._detail_text
        t.configure(state="normal")
        t.delete("1.0", "end")
        if not sel:
            self._detail_meta.configure(text="Select a row to see the whole block. The translation column fills "
                                             "during a run." if self.source_blocks else "")
            t.configure(state="disabled")
            return
        i = int(sel[0])
        b = self.source_blocks[i]
        flags = ", ".join(self._flags.get(i, []))
        self._detail_meta.configure(text=f"#{b['id']}   {b['timestamp']}" + (f"    ⚠ {flags}" if flags else "")
                                    + ("    repaired" if b.get("_repaired") else ""),
                                    fg=COLORS["warning"] if flags else COLORS["text_dim"])
        t.insert("end", "\n".join(b["text_lines"]) + "\n")
        if i in self._tr_lines:
            t.insert("end", "\n".join(self._tr_lines[i]), "dst")
        t.configure(state="disabled")

    # NAMES TAB ───────────────────────────────────────────────────────
    def _build_names_tab(self, t):
        C = COLORS
        top = tk.Frame(t, bg=C["bg_card"])
        top.pack(fill="x", padx=self.px(14), pady=(self.px(12), 4))
        tk.Label(top, text="PRESERVE NAMES — never translated", font=FONTS["badge"], fg=C["accent"],
                 bg=C["bg_card"]).pack(side="left")
        tk.Label(top, textvariable=self._names_count, font=FONTS["tiny"], fg=C["text_dim"],
                 bg=C["bg_card"]).pack(side="right")
        tk.Label(t, text="One name per line: people, companies, schools, institutions, brands, titles. Countries "
                         "and cities are translated normally. The list belongs to the subtitle that is loaded; a "
                         "<file>.names.txt next to it is loaded automatically.",
                 font=FONTS["tiny"], fg=C["text_dim"], bg=C["bg_card"], anchor="w", justify="left",
                 wraplength=self.px(640)).pack(fill="x", padx=self.px(14))
        self._gloss_text = tk.Text(t, font=FONTS["mono"], bg=C["bg_input"], fg=C["text"],
                                   insertbackground=C["text"], relief="flat", wrap="word",
                                   highlightbackground=C["border"], highlightthickness=1, padx=8, pady=6)
        self._gloss_text.pack(fill="both", expand=True, padx=self.px(14), pady=(8, 6))
        self._gloss_text.bind("<KeyRelease>", lambda e: self._update_names_count())
        row = tk.Frame(t, bg=C["bg_card"])
        row.pack(fill="x", padx=self.px(14), pady=(0, 6))
        self._names_btn = self._flat_btn(row, "✦  Auto-detect names (Claude)", self._auto_detect_names,
                                         font=FONTS["tiny"], pady=4)
        self._names_btn.pack(side="left")
        Tooltip(self._names_btn, "Ask the cheapest Claude model to list the proper names in the loaded file.\n"
                                 "Costs a fraction of a cent. Review the list before you start.")
        self._flat_btn(row, "Save next to the subtitle", self._save_glossary_sidecar, dim=True,
                       font=FONTS["tiny"], pady=4).pack(side="left", padx=(6, 0))
        self._flat_btn(row, "Load from file…", self._load_glossary_file, dim=True, font=FONTS["tiny"],
                       pady=4).pack(side="left", padx=(6, 0))
        self._flat_btn(row, "Clear", self._clear_glossary, dim=True, font=FONTS["tiny"], pady=4).pack(side="right")
        self._gloss_status = tk.Label(t, text="", font=FONTS["tiny"], fg=C["text_dim"], bg=C["bg_card"], anchor="w")
        self._gloss_status.pack(fill="x", padx=self.px(14), pady=(0, 10))

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
            self.notebook.tab(self.TAB_NAMES, text=f"  Names {n}  " if n else "  Names  ")
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
        path = filedialog.askopenfilename(title="Load names list",
                                          filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if not path:
            return
        try:
            n = self._merge_glossary(parse_glossary(Path(path).read_text(encoding="utf-8")))
            self._gloss_status.configure(text=f"Loaded {Path(path).name}: {n} new names")
        except Exception as e:
            messagebox.showerror("Load failed", str(e))

    def _save_glossary_sidecar(self):
        if not self.input_path:
            messagebox.showwarning("No file", "Open a subtitle first.")
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
            messagebox.showwarning("No file", "Open a subtitle first.")
            return
        if not self._api_key.strip():
            messagebox.showwarning("API Key", "Auto-detect needs a Claude API key (Settings).")
            return
        mid = DEFAULT_MODEL if self.catalog.has_model(DEFAULT_MODEL) else self.claude_model.get()
        model_info = self.catalog.model(mid)
        self._names_btn.configure(state="disabled")
        self._gloss_status.configure(text=f"Detecting names with {model_info['display_name']}…")
        file_at_start = self.input_path
        blocks = self.source_blocks
        src_label = _LANG_LABEL.get(self.source_lang.get(), self.source_lang.get())

        def work():
            try:
                client = _anthropic().Anthropic(api_key=self._api_key.strip(), max_retries=2, timeout=180)
                names, usage = extract_names(client, blocks, model_info, src_label)
                price = self.catalog.price(mid)
                cost = usage.summary(price)

                def done():
                    if not same_file(file_at_start, self.input_path):
                        self._log(f"Auto-detect names finished for a file that is no longer loaded  ·  {cost}", "warn")
                        return
                    self.cost_ledger.add("names", mid, usage, price)
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

    # LOG TAB ─────────────────────────────────────────────────────────
    def _build_log_tab(self, t):
        C = COLORS
        row = tk.Frame(t, bg=C["bg_card"])
        row.pack(side="bottom", fill="x", padx=self.px(10), pady=(0, self.px(8)))
        b = self._flat_btn(row, "Save log…", self._save_log, dim=True, font=FONTS["tiny"], pady=3)
        b.pack(side="right")
        Tooltip(b, "Save the Activity Log as a text file  (Ctrl+S on this tab)")
        self.log_text = scrolledtext.ScrolledText(t, font=FONTS["mono_sm"], bg=C["bg_card"], fg=C["text_dim"],
                                                  insertbackground=C["text"], selectbackground=C["select"],
                                                  relief="flat", state="disabled", wrap="word", highlightthickness=0)
        self.log_text.pack(fill="both", expand=True, padx=self.px(10), pady=self.px(8))
        for tag, color in [("info", C["text_dim"]), ("success", C["success"]), ("warn", C["warning"]),
                           ("error", C["error"]), ("accent", C["accent"])]:
            self.log_text.tag_configure(tag, foreground=color)

    def _save_log(self):
        stem = strip_language_tag(Path(self.input_path).stem) if self.input_path else "srt-studio"
        out = filedialog.asksaveasfilename(title="Save log", defaultextension=".txt",
                                           initialfile=f"{stem}.log.txt",
                                           initialdir=str(Path(self.input_path).parent) if self.input_path else "",
                                           filetypes=[("Text files", "*.txt")])
        if not out:
            return
        try:
            _atomic_write_text(Path(out), self.log_text.get("1.0", "end"))
            self.status_text.set(f"Log saved: {Path(out).name}")
        except Exception as e:
            messagebox.showerror("Save failed", str(e))

    # STATUS BAR ──────────────────────────────────────────────────────
    def _build_statusbar(self):
        C = COLORS
        bar = tk.Frame(self, bg=C["bg_mid"], height=self.px(30))
        bar.grid(row=2, column=0, sticky="ew")
        bar.pack_propagate(False)
        tk.Label(bar, textvariable=self.status_text, font=FONTS["tiny"], fg=C["text"], bg=C["bg_mid"],
                 anchor="w", padx=self.px(12)).pack(side="left", fill="x", expand=True)
        self._last_cost_lbl = tk.Label(bar, text="", font=FONTS["mono_sm"], fg=C["text_dim"], bg=C["bg_mid"],
                                       padx=self.px(12))
        self._last_cost_lbl.pack(side="right")
        self._open_link = self._link(bar, "Open folder", lambda: self._open_folder(self._last_saved), bg=C["bg_mid"])
        Tooltip(self._open_link, "Show the translated file in Explorer")
        self.pct_label = tk.Label(bar, text="", font=FONTS["mono_sm"], fg=C["text_dim"], bg=C["bg_mid"], width=5)
        self.pct_label.pack(side="right")
        self._pbar = ttk.Progressbar(bar, variable=self.progress_var, maximum=100, length=self.px(240),
                                     style="P.Horizontal.TProgressbar")
        self._pbar.pack(side="right", padx=(0, 6))
        self._pbar_shown = True
        self._show_progress(False)

    def _show_progress(self, on: bool):
        if on and not self._pbar_shown:
            self._pbar.pack(side="right", padx=(0, 6), before=self.pct_label)
            self._pbar_shown = True
        elif not on and self._pbar_shown:
            self._pbar.pack_forget()
            self.pct_label.configure(text="")
            self._pbar_shown = False

    def _show_open_link(self, on: bool):
        if on:
            self._open_link.pack(side="right", padx=(0, 6), before=self._last_cost_lbl)
        else:
            self._open_link.pack_forget()

    # ── Divider (G1 11b) ─────────────────────────────────────────────

    def _body_width(self) -> int:
        return max(1, self._paned.winfo_width())

    def _default_left(self, width: int) -> int:
        return clamp_left(width, int(width * DEFAULT_LEFT_PX / 1280))

    def _place_sash(self, left: int):
        try:
            self._paned.sash_place(0, left, 1)
        except tk.TclError:
            pass

    def _on_paned_configure(self, event):
        w = event.width
        if w < 50:
            return
        if self._left_ratio is None:
            left = self._default_left(w)
        else:
            left = int(self._left_ratio * w)
        left = int(clamp_left(w / self._scale, left / self._scale) * self._scale)
        self.after_idle(lambda: self._place_sash(left))

    def _on_sash_release(self, event=None):
        w = self._body_width()
        try:
            x = self._paned.sash_coord(0)[0]
        except tk.TclError:
            return
        x2 = int(clamp_left(w / self._scale, x / self._scale) * self._scale)
        if x2 != x:
            self._place_sash(x2)
        self._left_ratio = round(x2 / w, 4)

    def _on_sash_double(self, event):
        try:
            hit = self._paned.identify(event.x, event.y)
        except tk.TclError:
            hit = ""
        if hit and "sash" in str(hit):
            self.reset_layout()

    def reset_layout(self):
        self._left_ratio = None
        w = self._body_width()
        self._place_sash(int(self._default_left(int(w / self._scale)) * self._scale))
        self.after_idle(self._on_sash_release)

    # ── Keyboard ─────────────────────────────────────────────────────

    def _bind_keys(self):
        self.bind_all("<Control-o>", lambda e: self._browse())
        self.bind_all("<Control-Return>", lambda e: self._start(sample=False))
        self.bind_all("<Escape>", lambda e: self._cancel() if self.is_translating else None)
        for i in range(3):
            self.bind_all(f"<Control-Key-{i + 1}>", lambda e, k=i: self.notebook.select(k))
        self.bind_all("<Control-s>", lambda e: self._save_log() if self._current_tab_name() == "log" else None)

    # ── Engine / model / catalog ─────────────────────────────────────

    def _on_engine_change(self, *args):
        sel = self.engine.get()
        try:
            self._engine_combo.current([k for k, _ in ENGINES].index(sel))
        except ValueError:
            pass
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
        self._update_model_tip()
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
        self._update_model_tip()

    def _update_model_tip(self):
        if getattr(self, "_model_tip", None):
            self._model_tip.text = (self.catalog.long_label(self.claude_model.get())
                                    + "\n\nLabel: price per million tokens input/output · context · ★ recommended")

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

    # ── Options summary / output line ────────────────────────────────

    def _update_options_summary(self):
        if not hasattr(self, "_opt_summary"):
            return
        parts = [f"batch {self._int(self.batch_size, 25, 5, 60)}", f"{self._int(self.workers, 5, 1, 8)} workers",
                 f"cues {'on' if self.translate_cues.get() else 'off'}",
                 f"AI notice {'on' if self.notice_on.get() else 'off'}",
                 "save next to source" if self.same_folder.get() else "ask where to save"]
        self._opt_summary.configure(text=" · ".join(parts))

    def _output_name(self) -> str:
        if not self.input_path:
            return ""
        return default_output_name(self.input_path, self.target_lang.get(),
                                   output_extension(self.doc, self.output_format.get()))

    def _update_output_line(self):
        if not hasattr(self, "_out_line"):
            return
        name = self._output_name()
        self._out_line.configure(text=f"Output: {middle_ellipsis(name, 64)}" if name else "")

    # ── Cost ─────────────────────────────────────────────────────────

    def _refresh_cost(self, exact: bool = False):
        if not hasattr(self, "_cost_main"):
            return
        if not self.source_blocks or self.engine.get() != "claude":
            self._cost_main.configure(text="free" if self.engine.get() != "claude" else "—", fg=COLORS["text_dim"])
            self._cost_detail.configure(text="MyMemory has no cost" if self.engine.get() != "claude"
                                        else "open a subtitle")
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
        self._last_est = est
        total = est.get("total_cost")
        if total is None:
            self._cost_main.configure(text="price unknown", fg=COLORS["warning"])
        else:
            self._cost_main.configure(
                text=f"~{format_usd(total)}",
                fg=COLORS["yellow"] if total < 0.50 else COLORS["error"])
        p = est["price"]
        price_s = (f"{_short_price(p['input'])}/{_short_price(p['output'])} per MTok ({p['source']})"
                   if p["input"] is not None else "no price found")
        detail = f"{est['input_tokens']:,} in · {est['output_tokens']:,} out tokens · {price_s}"
        if self.context_blocks:
            detail += " · +context"
        self._cost_detail.configure(text=detail)
        self._cost_method.configure(text="exact input" if est.get("method") == "exact" else "approx.")

    # ── Dialogs ──────────────────────────────────────────────────────

    def _dialog(self, title, w, h):
        dlg = tk.Toplevel(self)
        dlg.title(title)
        dlg.configure(bg=COLORS["bg_card"])
        dlg.transient(self)
        w, h = self.px(w), self.px(h)
        self.update_idletasks()
        dlg.geometry(f"{w}x{h}+{self.winfo_rootx() + max(0, (self.winfo_width() - w) // 2)}"
                     f"+{self.winfo_rooty() + max(0, (self.winfo_height() - h) // 2)}")
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        return dlg

    def _section(self, parent, text, top=16):
        tk.Label(parent, text=text, font=FONTS["badge"], fg=COLORS["accent"], bg=COLORS["bg_card"],
                 anchor="w").pack(fill="x", pady=(top, 4), padx=20)

    def _check(self, parent, text, var, tip=None, command=None):
        c = tk.Checkbutton(parent, text=text, variable=var, font=FONTS["small"], fg=COLORS["text"],
                           bg=COLORS["bg_card"], selectcolor=COLORS["bg_input"], activebackground=COLORS["bg_card"],
                           activeforeground=COLORS["text_bright"], anchor="w", cursor="hand2", command=command)
        c.pack(fill="x", padx=16)
        if tip:
            Tooltip(c, tip)
        return c

    def _choice(self, parent, label, var, options, width=34):
        r = tk.Frame(parent, bg=COLORS["bg_card"])
        r.pack(fill="x", padx=20, pady=3)
        tk.Label(r, text=label, width=16, anchor="w", font=FONTS["small"], fg=COLORS["text_dim"],
                 bg=COLORS["bg_card"]).pack(side="left")
        keys = [k for k, _ in options]
        cb = ttk.Combobox(r, values=[l for _, l in options], state="readonly", width=width,
                          style="Lang.TCombobox", font=FONTS["small"])
        cb.current(keys.index(var.get()) if var.get() in keys else 0)
        cb.bind("<<ComboboxSelected>>", lambda e: var.set(keys[cb.current()]))
        cb.pack(side="left")
        _no_wheel(cb)
        return cb

    def _show_options(self):
        dlg = self._dialog("Options", 540, 440)
        dlg.resizable(False, False)
        C = COLORS
        self._section(dlg, "TRANSLATION")
        r1 = tk.Frame(dlg, bg=C["bg_card"])
        r1.pack(fill="x", padx=20, pady=(0, 6))

        def spin(parent, var, lo, hi, inc):
            s = tk.Spinbox(parent, from_=lo, to=hi, increment=inc, textvariable=var, width=4,
                           font=FONTS["small"], bg=C["bg_input"], fg=C["text"], buttonbackground=C["bg_mid"],
                           insertbackground=C["text"], relief="flat", highlightbackground=C["border"],
                           highlightthickness=1)
            _no_wheel(s)
            return s
        tk.Label(r1, text="Batch size", font=FONTS["small"], fg=C["text"], bg=C["bg_card"]).pack(side="left")
        sp1 = spin(r1, self.batch_size, 5, 60, 5)
        sp1.pack(side="left", padx=(6, 18))
        tk.Label(r1, text="Workers", font=FONTS["small"], fg=C["text"], bg=C["bg_card"]).pack(side="left")
        sp2 = spin(r1, self.workers, 1, 8, 1)
        sp2.pack(side="left", padx=(6, 0))
        Tooltip(sp1, "Blocks per API call (5–60). Suggested automatically from the average line length.")
        Tooltip(sp2, "Simultaneous API calls (1–8). More is faster but can hit rate limits; the app retries.")
        self._check(dlg, "Translate hearing-impaired cues  [door slams]  (laughs)  APPLAUSE", self.translate_cues,
                    "Cue lines are translated and keep their bracket or capital style. Untick to leave them as they are.")
        self._section(dlg, "OUTPUT")
        self._check(dlg, "Save next to the source file (skip the Save dialog)", self.same_folder,
                    "Output name: source name without its language tag + target code, e.g. Movie.pt-BR.srt.\n"
                    "Unticked: a Save dialog opens in the last folder you used.")
        self._check(dlg, "Add a 'translated by AI' line at the start of the subtitle", self.notice_on,
                    "A short block in the target language, e.g. 'Legendas traduzidas por IA (Claude Haiku 5.5)'.\n"
                    "Text and duration: Settings → Output.")
        self._section(dlg, "SAMPLE")
        self._choice(dlg, "Sample from", self.sample_from, [("middle", "the middle (busiest dialogue)"),
                                                           ("start", "the start")], width=28)
        self._flat_btn(dlg, "  Close  ", lambda: (dlg.destroy(), self._sync_sample_combo()), primary=True,
                       padx=20, pady=5).pack(side="bottom", pady=14)

    def _sync_sample_combo(self):
        self._sample_where.current(0 if self.sample_from.get() == "middle" else 1)

    def _show_settings(self):
        if self._settings_dlg and self._settings_dlg.winfo_exists():
            self._settings_dlg.lift()
            return
        C = COLORS
        dlg = self._dialog("Settings", 620, 500)
        dlg.minsize(self.px(560), self.px(440))
        self._settings_dlg = dlg
        nb = ttk.Notebook(dlg, style="T.TNotebook")
        nb.pack(fill="both", expand=True, padx=0, pady=(6, 0))

        def page(title):
            f = tk.Frame(nb, bg=C["bg_card"])
            nb.add(f, text=f"  {title}  ")
            return f

        # GENERAL
        p = page("General")
        self._section(p, "CLAUDE API KEY")
        row = tk.Frame(p, bg=C["bg_card"])
        row.pack(fill="x", padx=20)
        self.key_display = tk.Label(row, text=self._mask_key(self._api_key), font=FONTS["mono_sm"],
                                    bg=C["key_bg"], fg=C["text_dim"], anchor="w", padx=8, pady=5,
                                    highlightbackground=C["border"], highlightthickness=1)
        self.key_display.pack(side="left", fill="x", expand=True)
        self._flat_btn(row, "✎  Edit", self._edit_key, font=FONTS["tiny"], padx=10, pady=5).pack(side="right", padx=(6, 0))
        tk.Label(p, text="Stored only on this computer, sent only to api.anthropic.com.", font=FONTS["tiny"],
                 fg=C["text_dim"], bg=C["bg_card"], anchor="w").pack(fill="x", padx=20, pady=(3, 0))
        self._link(p, "Get a key at console.anthropic.com",
                   lambda: webbrowser.open("https://console.anthropic.com")).pack(anchor="w", padx=20, pady=(2, 0))
        self._section(p, "MODELS AND PRICES")
        row2 = tk.Frame(p, bg=C["bg_card"])
        row2.pack(fill="x", padx=20)
        tk.Label(row2, textvariable=self._catalog_status, font=FONTS["tiny"], fg=C["text"], bg=C["bg_card"],
                 anchor="w", justify="left").pack(side="left", fill="x", expand=True)
        self._flat_btn(row2, "↻  Refresh now", lambda: self._refresh_catalog(force=True), font=FONTS["tiny"],
                       pady=4).pack(side="right")
        tk.Label(p, text=f"Price override file (optional): {PRICING_OVERRIDE_PATH}", font=FONTS["tiny"],
                 fg=C["text_dim"], bg=C["bg_card"], anchor="w", wraplength=self.px(560),
                 justify="left").pack(fill="x", padx=20, pady=(6, 0))
        self._section(p, "WINDOW")
        self._link(p, "Reset layout (divider back to the default position)", self.reset_layout,
                   font=FONTS["small"]).pack(anchor="w", padx=20)

        # OUTPUT
        p = page("Output")
        self._section(p, "FINISHED TRANSLATION")
        self._check(p, "Show a message when a translation finishes", self.finish_message,
                    "The message shows the saved file, flagged blocks and the real cost.\n"
                    "A failed save is always reported, even with this off.")
        self._section(p, "FILE")
        self._choice(p, "Output format", self.output_format, OUTPUT_FORMATS)
        self._choice(p, "Encoding", self.output_enc, OUTPUT_ENCODINGS)
        tk.Label(p, text="UTF-8 with BOM works with every player and TV. 'Same as the source' falls back to it "
                         "when the source encoding cannot hold the translated text (e.g. Thai into cp1252).",
                 font=FONTS["tiny"], fg=C["text_dim"], bg=C["bg_card"], anchor="w", justify="left",
                 wraplength=self.px(560)).pack(fill="x", padx=20, pady=(2, 0))
        self._section(p, "AI NOTICE")
        self._check(p, "Add a 'translated by AI' line to the subtitle", self.notice_on)
        r = tk.Frame(p, bg=C["bg_card"])
        r.pack(fill="x", padx=20, pady=(4, 0))
        tk.Label(r, text="Text", width=16, anchor="w", font=FONTS["small"], fg=C["text_dim"],
                 bg=C["bg_card"]).pack(side="left")
        tk.Entry(r, textvariable=self.notice_text, font=FONTS["small"], bg=C["bg_input"], fg=C["text"],
                 insertbackground=C["text"], relief="flat", highlightbackground=C["border"],
                 highlightthickness=1).pack(side="left", fill="x", expand=True, ipady=2)
        r = tk.Frame(p, bg=C["bg_card"])
        r.pack(fill="x", padx=20, pady=(4, 0))
        tk.Label(r, text="Seconds on screen", width=16, anchor="w", font=FONTS["small"], fg=C["text_dim"],
                 bg=C["bg_card"]).pack(side="left")
        tk.Spinbox(r, from_=2, to=10, textvariable=self.notice_secs, width=4, font=FONTS["small"],
                   bg=C["bg_input"], fg=C["text"], buttonbackground=C["bg_mid"], relief="flat",
                   highlightbackground=C["border"], highlightthickness=1).pack(side="left")
        tk.Label(p, text="Empty text = the built-in text in the target language, e.g. "
                         f"“{notice_text_for(self.target_lang.get(), 'Claude Haiku 5.5')}”. "
                         "{model} is replaced by the model name.",
                 font=FONTS["tiny"], fg=C["text_dim"], bg=C["bg_card"], anchor="w", justify="left",
                 wraplength=self.px(560)).pack(fill="x", padx=20, pady=(4, 0))

        # REPAIR
        p = page("Repair")
        self._section(p, "AD AND CREDIT LINES")
        self._check(p, "Remove ad and credit lines when repairing", self.remove_ads,
                    "Blocks such as 'Subtitles by …', 'www.OpenSubtitles.org' or 'Subtitulado por …'.")
        tk.Label(p, text="Extra patterns, one per line (plain words or regular expressions):", font=FONTS["tiny"],
                 fg=C["text_dim"], bg=C["bg_card"], anchor="w").pack(fill="x", padx=20, pady=(8, 2))
        pat = tk.Text(p, height=6, font=FONTS["mono_sm"], bg=C["bg_input"], fg=C["text"],
                      insertbackground=C["text"], relief="flat", highlightbackground=C["border"],
                      highlightthickness=1)
        pat.pack(fill="x", padx=20)
        pat.insert("1.0", "\n".join(self._ad_extra))

        def save_patterns(_e=None):
            self._ad_extra = [l.strip() for l in pat.get("1.0", "end").splitlines() if l.strip()]
        pat.bind("<KeyRelease>", save_patterns)

        # FILES
        p = page("Files")
        self._section(p, "FILES")
        for text in (f"Settings file: {CONFIG_PATH}", self._last_dir_display()):
            tk.Label(p, text=text, font=FONTS["tiny"], fg=C["text_dim"], bg=C["bg_card"], anchor="w",
                     wraplength=self.px(560), justify="left").pack(fill="x", padx=20, pady=2)

        def close():
            save_patterns()
            save_config(self._settings_snapshot())
            dlg.destroy()
        dlg.protocol("WM_DELETE_WINDOW", close)
        self._flat_btn(dlg, "  Close  ", close, primary=True, padx=20, pady=5).pack(side="bottom", pady=12)

    def _last_dir_display(self) -> str:
        d = self._last_output_dir
        return "Last output folder: " + (d if d else "(none yet)")

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
        self._show_text_dialog(f"Help — {APP_TITLE}", HELP_TEXT, 720, 680)

    def _show_engine_help(self):
        self._show_text_dialog("Translation engines", ENGINE_HELP_TEXT, 640, 560)

    # ── Recent files ─────────────────────────────────────────────────

    def _fill_recent_menu(self):
        m = self._recent_menu
        m.delete(0, "end")
        self._recent = prune_recent(self._recent)
        if not self._recent:
            m.add_command(label="(no recent files)", state="disabled")
            return
        for p in self._recent:
            m.add_command(label=middle_ellipsis(Path(p).name, 70), command=lambda path=p: self._load_source_file(path))
        m.add_separator()
        m.add_command(label="Clear list", command=self._clear_recent)

    def _clear_recent(self):
        self._recent = []
        save_config({"recent_files": []})
        if not self.source_blocks:
            self._show_empty_state()

    # ── File handling ────────────────────────────────────────────────

    def _browse(self):
        path = filedialog.askopenfilename(title="Open subtitle", filetypes=OPEN_FILETYPES)
        if path:
            self._load_source_file(path)

    def _ctx_action(self):
        if self.context_blocks:
            self._clear_context()
        else:
            path = filedialog.askopenfilename(title="Open context subtitle (same film, another language)",
                                              filetypes=OPEN_FILETYPES)
            if path:
                self._load_context_file(path)

    def _on_drop(self, path: str):
        p = Path(path)
        if p.suffix.lower() in TEXT_FORMATS or p.suffix.lower() in PICTURE_EXTS:
            self._load_source_file(str(p))
        else:
            messagebox.showwarning("Not a subtitle", f"{p.name} is not a subtitle file the app can open.\n\n"
                                                      f"Supported: {', '.join(TEXT_FORMATS)}")

    def _read_doc(self, path: str, what: str):
        """SubDoc or None (the reason has been shown)."""
        try:
            try:
                doc = load_subtitle(path)
            except NeedsFrameRate as e:
                fps = simpledialog.askfloat("Frame rate", f"{e}\n\nFrame rate of the video (e.g. 23.976, 25):",
                                            initialvalue=DEFAULT_FPS, minvalue=10, maxvalue=120, parent=self)
                if not fps:
                    return None
                doc = load_subtitle(path, fps=fps)
        except SubtitleError as e:
            messagebox.showwarning("Cannot open", f"{Path(path).name}\n\n{e}")
            return None
        except ImportError:
            messagebox.showwarning("Package missing", "Reading this format needs the pysubs2 package:\n"
                                                      "python -m pip install pysubs2")
            return None
        except Exception as e:
            messagebox.showerror("Cannot open", f"Could not read {what}:\n{e}")
            return None
        if not doc.blocks:
            messagebox.showwarning("No subtitles found",
                                   f"No subtitle blocks were found in {what}:\n{Path(path).name}\n\n"
                                   f"The file was read as {doc.encoding} ({doc.label}). An SRT block needs a "
                                   "timing line such as\n00:01:02,345 --> 00:01:04,000")
            self._log(f"No subtitle blocks found in {Path(path).name} (read as {doc.encoding})", "warn")
            return None
        return doc

    def _confirm_names_switch(self) -> bool:
        """Before another subtitle replaces the current one: offer to save unsaved names.
        False = the user cancelled (keep the current file)."""
        terms = self._glossary_terms()
        if not terms or not self.input_path:
            return True
        sidecar = glossary_sidecar_path(self.input_path)
        try:
            saved = parse_glossary(sidecar.read_text(encoding="utf-8")) if sidecar.exists() else []
        except Exception:
            saved = []
        if not names_unsaved(terms, saved):
            return True
        ans = messagebox.askyesnocancel(
            "Names list",
            f"The names list has {len(terms)} name(s) for {Path(self.input_path).name} that are not saved.\n\n"
            f"Save them to {sidecar.name} before loading the new file?\n\n"
            "Yes: save them   ·   No: discard them   ·   Cancel: keep the current file",
            parent=self)
        if ans is None:
            return False
        if ans:
            self._save_glossary_sidecar()
        return True

    def _load_source_file(self, path: str):
        if self.is_translating:
            messagebox.showwarning("Translation running", "Wait for the translation to finish (or cancel it) "
                                                          "before loading another subtitle.")
            return
        path = str(path).strip()
        doc = self._read_doc(path, "the file")
        if not doc:
            return
        if not same_file(path, self.input_path):
            if not self._confirm_names_switch():
                return
            self._gloss_text.delete("1.0", "end")
            self._gloss_status.configure(text="")
            self._update_names_count()
            self.cost_ledger.clear()
        self.doc = doc
        self.source_blocks = doc.blocks
        self.translated_blocks, self._tr_lines, self._flags, self.qc_issues = [], {}, {}, []
        self._repair_log = []
        self.input_path = path
        self._enc_short = doc.encoding.upper().replace("-SIG", "+BOM")
        self._detected_code = detect_language(doc.blocks)
        self.problems = check_subtitle(doc, self._ad_extra, is_srt=doc.is_srt, parse_problems=doc.problems)
        sug = suggest_batch_size(doc.blocks)
        self.batch_size.set(sug)
        if self._detected_code:
            self._set_src_combo(self._detected_code)
        self._recent = push_recent(self._recent, path)
        save_config({"recent_files": self._recent})
        self._show_open_link(False)
        self._last_cost_lbl.configure(text="")
        self._update_file_info()
        n_cues = sum(1 for b in doc.blocks for l in b["text_lines"] if is_cue(l))
        self._log(f"Loaded: {Path(path).name} — {doc.label}, {len(doc.blocks):,} blocks  [{self._enc_short}]  •  "
                  f"{n_cues} cue lines", "accent")
        lang = _LANG_LABEL.get(self._detected_code, "not detected (pick it in LANGUAGES)")
        self._log(f"Detected: {lang}  •  auto batch={sug}", "info" if self._detected_code else "warn")
        if self.problems:
            self._log(f"Source check: {len(self.problems)} problem(s) — see Repair › Review…", "warn")

        sidecar = glossary_sidecar_path(path)
        if sidecar.exists():
            try:
                n = self._merge_glossary(parse_glossary(sidecar.read_text(encoding="utf-8")))
                self._gloss_status.configure(text=f"Loaded {sidecar.name} ({n} new names)")
                self._log(f"Names file: {sidecar.name} — {n} new names added", "info")
            except Exception as e:
                self._log(f"Could not read {sidecar.name}: {e}", "warn")
        elif not self._glossary_terms():
            restored = parse_glossary(saved_names_for(self._saved_glossary, path))
            if restored:
                self._merge_glossary(restored)
                self._gloss_status.configure(text=f"Restored {len(restored)} names from the last session")
                self._log(f"Names: {len(restored)} restored from the last session for this file", "info")
        self._filter.set("all")
        self._show_table()
        self._fill_table()
        self.notebook.select(self.TAB_SUBS)
        self._refresh_cost()
        self.status_text.set("Check the estimate, then press Start (or Sample to try 20 blocks)")

    def _update_file_label(self):
        if not self.input_path:
            return
        name = Path(self.input_path).name
        try:
            import tkinter.font as tkfont
            f = tkfont.Font(font=self.file_label.cget("font"))
            avail = max(80, self.file_label.winfo_width() - 24)
            n = len(name)
            while n > 12 and f.measure(middle_ellipsis(name, n)) > avail:
                n -= 2
            self.file_label.configure(text=middle_ellipsis(name, n))
        except Exception:
            self.file_label.configure(text=middle_ellipsis(name, 48))

    def _update_file_info(self):
        C = COLORS
        if not self.source_blocks:
            return
        self.file_label.configure(fg=C["text_bright"])
        self._file_tip.text = f"{self.input_path}\n\nClick to open another subtitle."
        self._update_file_label()
        for w in self._chips.winfo_children():
            w.destroy()
        lang = _LANG_LABEL.get(self._detected_code)
        for text, kind in ((self.doc.label, ""), (self._enc_short, ""), (f"{len(self.source_blocks):,} blocks", ""),
                           (lang.split(" — ")[0] if lang else "language ?", "" if lang else "warn")):
            self._chip(self._chips, text, kind).pack(side="left", padx=(0, 6))
        self._hint.pack_forget()
        self._repair_row.pack(fill="x", pady=(8, 0), after=self._chips)
        self._ctx_row.pack(fill="x", pady=(4, 0), after=self._repair_row)
        self._update_repair_row()
        self._update_output_line()

    def _update_repair_row(self):
        C = COLORS
        if self._repair_log:
            self._repair_chip.configure(text="✓ repaired", fg=C["chip_ok_fg"], bg=C["chip_ok_bg"],
                                        highlightbackground=C["chip_ok_bd"])
            self._repair_note.configure(text=f"{len(self._repair_log)} change(s)")
            self._repair_link.configure(text="Details…")
        elif self.problems:
            kinds = {}
            for p in self.problems:
                kinds[p["kind"]] = kinds.get(p["kind"], 0) + 1
            top = ", ".join(f"{n} {k.replace('_', ' ')}" for k, n in list(kinds.items())[:2])
            self._repair_chip.configure(text=f"⚠ {len(self.problems)} found", fg=C["warning"], bg=C["chip_warn_bg"],
                                        highlightbackground=C["chip_warn_bd"])
            self._repair_note.configure(text=top)
            self._repair_link.configure(text="Review…")
        else:
            self._repair_chip.configure(text="✓ no problems", fg=C["chip_ok_fg"], bg=C["chip_ok_bg"],
                                        highlightbackground=C["chip_ok_bd"])
            self._repair_note.configure(text="")
            self._repair_link.configure(text="")

    def _load_context_file(self, path: str):
        doc = self._read_doc(path, "the context file")
        if not doc:
            return
        for b in doc.blocks:
            b["_ms"] = timestamp_ms(b["timestamp"])
        self.context_blocks = doc.blocks
        self.context_path = path
        self._ctx_label.configure(text=middle_ellipsis(f"{Path(path).name}", 40) + f"  ({len(doc.blocks):,})",
                                  fg=COLORS["success"])
        self._ctx_link.configure(text="✕")
        self._log(f"Context: {Path(path).name} — {doc.label}, {len(doc.blocks):,} blocks", "info")
        self._refresh_cost()

    def _clear_context(self):
        self.context_blocks = []
        self.context_path = ""
        self._ctx_label.configure(text="none", fg=COLORS["text_dim"])
        self._ctx_link.configure(text="+ add")
        self._refresh_cost()

    # ── Repair (R1) ──────────────────────────────────────────────────

    def _show_repair(self):
        if not self.source_blocks or (not self.problems and not self._repair_log):
            return
        C = COLORS
        dlg = self._dialog("Source check", 760, 480)
        dlg.minsize(self.px(560), self.px(360))
        head = ("The subtitle file has these problems. Repair fixes them in the app only; the file on disk is not "
                "changed unless you save a repaired copy." if self.problems and not self._repair_log else
                "Repair done. What was changed:")
        tk.Label(dlg, text=head, font=FONTS["small"], fg=C["text"], bg=C["bg_card"], anchor="w", justify="left",
                 wraplength=self.px(720)).pack(fill="x", padx=20, pady=(16, 8))
        frame = tk.Frame(dlg, bg=C["bg_card"])
        frame.pack(fill="both", expand=True, padx=20)
        if self._repair_log:
            txt = scrolledtext.ScrolledText(frame, font=FONTS["mono_sm"], bg=C["bg_input"], fg=C["text"],
                                            relief="flat", height=10, highlightthickness=0)
            txt.pack(fill="both", expand=True)
            txt.insert("1.0", "\n".join(self._repair_log))
            txt.configure(state="disabled")
        else:
            tv = ttk.Treeview(frame, columns=("block", "kind", "detail"), show="headings", style="Subs.Treeview")
            for c, w, t in (("block", 70, "Block"), ("kind", 230, "Problem"), ("detail", 420, "Detail")):
                tv.heading(c, text=t)
                tv.column(c, width=self.px(w), stretch=c == "detail")
            sb = ttk.Scrollbar(frame, orient="vertical", command=tv.yview, style="D.Vertical.TScrollbar")
            tv.configure(yscrollcommand=sb.set)
            sb.pack(side="right", fill="y")
            tv.pack(fill="both", expand=True)
            for p in self.problems:
                blk = self.source_blocks[p["block"]]["id"] if p.get("block") is not None else "–"
                tv.insert("", "end", values=(blk, PROBLEM_LABELS.get(p["kind"], p["kind"]), p["detail"]))
        opts = tk.Frame(dlg, bg=C["bg_card"])
        opts.pack(fill="x", pady=(6, 0))
        if not self._repair_log:
            self._check(opts, "Remove ad and credit lines (they are never translated)", self.remove_ads)
        br = tk.Frame(dlg, bg=C["bg_card"])
        br.pack(fill="x", padx=20, pady=12)
        if self._repair_log:
            self._flat_btn(br, "Save repaired copy…", lambda: (dlg.destroy(), self._save_repaired_copy()),
                           padx=14, pady=5).pack(side="left")
            self._flat_btn(br, "Close", dlg.destroy, primary=True, padx=18, pady=5).pack(side="right")
        else:
            self._flat_btn(br, "Repair", lambda: (dlg.destroy(), self._repair_now()), primary=True,
                           padx=18, pady=5).pack(side="right")
            self._flat_btn(br, "Ignore", dlg.destroy, dim=True, padx=18, pady=5).pack(side="right", padx=(0, 6))

    def _repair_now(self):
        doc = self.doc
        fixed, log, removed = repair_blocks(self.source_blocks, self.problems, self.remove_ads.get(), doc.is_srt)
        if not doc.is_srt:
            doc.removed_events |= {self.source_blocks[i]["_ev"] for i in removed if "_ev" in self.source_blocks[i]}
        self.source_blocks = fixed
        doc.blocks = fixed
        self._repair_log = log or ["nothing needed changing"]
        self.problems = []
        for line in log:
            self._log(f"Repair: {line}", "info")
        self._log(f"Repair done: {len(log)} change(s). The file on disk is unchanged.", "success")
        self._update_file_info()
        self._fill_table()
        self._refresh_cost()

    def _save_repaired_copy(self):
        doc = self.doc
        src = Path(self.input_path)
        out = filedialog.asksaveasfilename(title="Save repaired subtitle", initialfile=src.name,
                                           initialdir=str(src.parent), defaultextension=src.suffix,
                                           filetypes=OPEN_FILETYPES)
        if not out:
            return
        try:
            if same_file(out, self.input_path):
                bak = next(src.with_name(src.name + (".bak" if k == 1 else f".bak{k}"))
                           for k in range(1, 1000)
                           if not src.with_name(src.name + (".bak" if k == 1 else f".bak{k}")).exists())
                bak.write_bytes(src.read_bytes())
                self._log(f"Backup written: {bak.name}", "info")
            text = render_subtitle(doc, self.source_blocks, "same")
            enc, note = output_encoding_for(self.output_enc.get(), doc.encoding, text, doc.is_srt)
            write_subtitle_text(text, out, enc)
            if note:
                self._log(note, "warn")
            self._log(f"Repaired copy saved: {out}", "success")
            self.status_text.set(f"Repaired copy saved: {Path(out).name}")
        except Exception as e:
            messagebox.showerror("Save failed", f"Could not save:\n{out}\n\n{e}")

    # ── Translation ──────────────────────────────────────────────────

    def _resolve_output_path(self):
        default_name = self._output_name()
        ext = Path(default_name).suffix
        if self.same_folder.get():
            return str(Path(self.input_path).parent / default_name)
        output = filedialog.asksaveasfilename(
            title="Save translated file as", defaultextension=ext, initialfile=default_name,
            initialdir=self._last_output_dir or str(Path(self.input_path).parent),
            filetypes=[(f"{ext.lstrip('.').upper()} files", f"*{ext}"), ("All files", "*.*")])
        if not output:
            return None
        self._last_output_dir = str(Path(output).parent)
        return output

    def _start(self, sample: bool):
        if self.is_translating:
            return
        if not self.source_blocks:
            messagebox.showwarning("No File", "Please open a subtitle first.")
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

        offset = 0
        if sample:
            self.output_path = ""
            offset = pick_sample(self.source_blocks, SAMPLE_BLOCKS, self.sample_from.get())
            blocks = self.source_blocks[offset:offset + SAMPLE_BLOCKS]
        else:
            output = self._resolve_output_path()
            if not output:
                return
            self.output_path = output
            blocks = self.source_blocks

        self.is_translating = True
        self.cancel_flag = False
        self.translated_blocks, self.qc_issues = [], []
        self._tr_lines, self._flags = {}, {}
        self._fill_table()
        self.progress_var.set(0)
        self._show_progress(True)
        self._show_open_link(False)
        self.start_btn.configure(state="disabled")
        self.sample_btn.configure(state="disabled")
        self._set_cancel_state(True)
        self.status_text.set("Translating…")

        bsize = self._int(self.batch_size, 25, 5, 60)
        model_lbl = self.catalog.model(self.claude_model.get())["display_name"] if engine == "claude" else "MyMemory"
        glossary = self._glossary_terms()
        self._log("═" * 50, "info")
        where = (f" (blocks {offset + 1}–{offset + len(blocks)}, from the {self.sample_from.get()})" if sample else "")
        self._log(f"{'SAMPLE RUN' + where if sample else 'Starting'}: {_LANG_LABEL.get(self.source_lang.get())} → "
                  f"{_LANG_LABEL.get(self.target_lang.get())}", "accent")
        self._log(f"Engine  : {model_lbl}", "info")
        self._log(f"Blocks  : {len(blocks):,}  │  Batch: {bsize}  │  Workers: {self._int(self.workers, 5, 1, 8)}  │  "
                  f"Cues: {'translate' if self.translate_cues.get() else 'keep'}", "info")
        self._log(f"Context : {Path(self.context_path).name if self.context_blocks and engine == 'claude' else 'none'}"
                  f"  │  Names : {len(glossary)}", "info")
        if not sample:
            self._log(f"Output  : {self.output_path}", "info")
        self._log("═" * 50, "info")
        notice_text = notice_text_for(self.target_lang.get(),
                                      model_lbl if engine == "claude" else "MyMemory, machine translation",
                                      self.notice_text.get())
        # Snapshot every setting on the main thread: Tk variables must not be read from the worker
        run = {
            "engine": engine, "model_id": self.claude_model.get(), "bsize": bsize,
            "n_workers": self._int(self.workers, 5, 1, 8) if engine == "claude" else 1,
            "cues": self.translate_cues.get(),
            "src_code": self.source_lang.get(), "tgt_code": self.target_lang.get(),
            "api_key": self._api_key.strip(), "output_path": self.output_path,
            "ctx": self.context_blocks if engine == "claude" else [],
            "file": self.input_path, "offset": offset, "doc": self.doc,
            "estimate": self._run_estimate(blocks, sample, bsize, glossary) if engine == "claude" else None,
            "output_format": self.output_format.get(), "output_encoding": self.output_enc.get(),
            "notice": self.notice_on.get() and not sample, "notice_text": notice_text,
            "notice_secs": self._int(self.notice_secs, 4, 2, 10), "notice_custom": self.notice_text.get(),
        }
        threading.Thread(target=self._worker, args=(blocks, sample, glossary, run), daemon=True).start()

    def _run_estimate(self, blocks, sample, bsize, glossary) -> dict:
        """The estimate to compare with the real cost: the exact one shown for the whole
        file if there is one, otherwise an approximate estimate of exactly these blocks."""
        if not sample and self._last_est.get("method") == "exact":
            return self._last_est
        try:
            return estimate_cost(blocks, self.claude_model.get(), self.catalog, ctx_blocks=self.context_blocks,
                                 glossary=glossary, batch_size=bsize, translate_cues=self.translate_cues.get(),
                                 target_code=self.target_lang.get(),
                                 src_label=_LANG_LABEL.get(self.source_lang.get(), self.source_lang.get()),
                                 tgt_label=_LANG_LABEL.get(self.target_lang.get(), self.target_lang.get()))
        except Exception:
            return {}

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
        doc       = run["doc"]
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

        def progress(n_done, bidx, bres):
            pct = n_done / total * 100
            first = run["offset"] + bidx * bsize
            part = {first + k: list(b["text_lines"]) for k, b in enumerate(bres)}

            def ui():
                self.progress_var.set(pct)
                self.status_text.set(f"Translating…  batch {done_cnt[0]} of {n_batches}  ·  "
                                     f"{n_done:,} of {total:,} blocks")
                self.pct_label.configure(text=f"{pct:.0f}%")
                self._tr_lines.update(part)
                for i, lines in part.items():
                    if self.tree.exists(str(i)):
                        vals = list(self.tree.item(str(i), "values"))
                        vals[3] = " / ".join(l for l in lines if l.strip())
                        self.tree.item(str(i), values=vals)
                cost = usage.cost(price) if engine == "claude" else None
                if cost is not None:
                    self._last_cost_lbl.configure(text=f"Cost so far {format_usd(cost)}")
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
                progress(blocks_done, bidx, bres)
                self._log(f"  ✓ Batch {bidx + 1:3d}/{n_batches}  ({len(bres)} blocks)", "info")
        finally:
            pool.shutdown(wait=not self.cancel_flag, cancel_futures=True)

        result = {"engine": engine, "sample": sample, "file": run["file"], "model_id": model_id,
                  "model_name": model.get("display_name", model_id), "usage": usage, "price": price,
                  "estimate": run.get("estimate"), "total": total, "ok": False, "cancelled": False,
                  "saved_path": "", "save_error": "", "flagged": 0, "verified": None, "errors": errors,
                  "offset": run["offset"]}

        def finish():
            result["cost"] = usage.cost(price) if engine == "claude" else None
            if engine == "claude":
                self._log(f"Actual cost: {usage.summary(price)}", "accent")
                line = estimate_vs_actual(run.get("estimate") or {}, usage, result["cost"])
                if line:
                    self._log(line, "info")
            self._post(lambda: self._done(result))

        if self.cancel_flag:
            self._log("Translation cancelled.", "warn")
            result["cancelled"] = True
            finish()
            return

        out_blocks = [blk for br in results if br is not None for blk in br]
        if len(out_blocks) != total:
            self._log(f"✗ Internal error: {len(out_blocks)} of {total} blocks assembled", "error")
            finish()
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
        self.qc_issues = issues
        result["flagged"] = len({i for i, _, _ in issues})
        off = run["offset"]
        flags = {}
        for i, kind, _ in issues:
            flags.setdefault(off + i, []).append(kind)
        tr = {off + k: list(b["text_lines"]) for k, b in enumerate(out_blocks)}

        if issues:
            self._log(f"\nQC report: {len(issues)} issue(s) in {len({i for i, _, _ in issues})} block(s)", "warn")
            for i, kind, detail in issues[:40]:
                self._log(f"  [{blocks[i]['id']}] {kind}: {detail}", "warn")
            if len(issues) > 40:
                self._log(f"  … and {len(issues) - 40} more (Subtitles tab › Flagged)", "warn")
        else:
            self._log("\nQC report: no issues found", "success")

        # ── AI notice (output only, full runs) ────────────────────────
        final_blocks, expected = out_blocks, [dict(b) for b in blocks]
        if run["notice"]:
            final_blocks, where_n = add_ai_notice(out_blocks, run["notice_text"], run["notice_secs"],
                                                  run["notice_custom"])
            if where_n:
                expected, _ = add_ai_notice(expected, run["notice_text"], run["notice_secs"], run["notice_custom"])
                self._log(f"AI notice added at the {where_n}: “{run['notice_text']}”", "info")
        self.translated_blocks = final_blocks
        self._post(lambda: self._apply_results(tr, flags))

        # ── Save + verify ─────────────────────────────────────────────
        if not sample:
            try:
                text = render_subtitle(doc, final_blocks, run["output_format"])
                out_is_srt = output_path.lower().endswith(".srt")
                enc, note = output_encoding_for(run["output_encoding"], doc.encoding if doc else "", text, out_is_srt)
                if not out_is_srt and enc == "utf-8-sig" and run["output_encoding"] == "utf-8-sig":
                    enc = "utf-8"            # BOM only for SRT; ASS/VTT readers expect plain UTF-8
                write_subtitle_text(text, output_path, enc)
                if note:
                    self._log(note, "warn")
                self._log(f"\nFile saved: {output_path}  [{enc}]", "success")
                result["saved_path"] = output_path
            except Exception as e:
                self._log(f"✗ Failed to write: {e}", "error")
                result["save_error"] = str(e) or e.__class__.__name__
                finish()
                return
            try:
                written = load_subtitle(output_path, fps=doc.fps if doc else None)
                ob = written.blocks
                exp_t = [timestamp_ms(b["timestamp"]) for b in expected]
                tol = 50 if doc and doc.fmt == "microdvd" else 10       # MicroDVD is frame-exact only
                got_t = [timestamp_ms(b["timestamp"]) for b in ob]
                checks = [
                    ("Block count", len(ob) == len(expected)),
                    ("All timings", len(ob) == len(expected) and all(
                        abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol for a, b in zip(exp_t, got_t))),
                    ("All line counts", len(ob) == len(expected) and all(
                        len(ob[j]["text_lines"]) == len(expected[j]["text_lines"]) for j in range(len(ob)))),
                ]
                if written.is_srt and doc and doc.is_srt:
                    checks.insert(1, ("All block numbers", [b["id"] for b in ob] == [b["id"] for b in expected]))
                ok_all = all(ok for _, ok in checks)
                result["verified"] = ok_all
                self._log("\n─── VERIFICATION ───", "accent")
                for nm, ok in checks:
                    self._log(f"  {'✓' if ok else '✗'} {nm}", "success" if ok else "error")
                self._log(f"\n{'✅ SUCCESS' if ok_all and not issues else '⚠ Completed with warnings'}"
                          f" — {total:,} blocks translated & verified", "success" if ok_all and not issues else "warn")
            except Exception as e:
                self._log(f"Verification error: {e}", "error")
        else:
            self._log(f"\nSample finished — {total} blocks (nothing saved)", "success")

        if errors:
            self._log(f"\n{len(errors)} batch error(s):", "warn")
            for err in errors[:10]:
                self._log(f"  • {err}", "warn")

        result["ok"] = True
        finish()

    def _apply_results(self, tr: dict, flags: dict):
        self._tr_lines = tr
        self._flags = flags
        self._fill_table()

    def _done(self, result: dict = None):
        result = result or {}
        self.is_translating = False
        self.start_btn.configure(state="normal")
        self.sample_btn.configure(state="normal")
        self._set_cancel_state(False)
        self._show_progress(False)
        if result.get("engine") == "claude" and result.get("usage") is not None:
            if same_file(result.get("file", ""), self.input_path):
                self.cost_ledger.add("sample" if result.get("sample") else "translation",
                                     result["model_id"], result["usage"], result["price"])
            if result.get("ok") and result.get("cost") is not None:
                self._cost_history = push_cost_history(
                    self._cost_history, cost_history_entry(result["model_id"], result.get("total", 0),
                                                           result.get("estimate") or {}, result["usage"],
                                                           result["cost"]))
                save_config({"cost_history": self._cost_history})
        if result.get("engine") == "claude" and result.get("cost") is not None:
            self._last_cost_lbl.configure(text=f"Last run {format_usd(result['cost'])}")
        elif result.get("engine") == "free":
            self._last_cost_lbl.configure(text="Last run free")
        dialog, status = finish_summary(result)
        self.status_text.set(status)
        if result.get("saved_path"):
            self._last_saved = result["saved_path"]
            self._show_open_link(True)
        if (result.get("ok") or result.get("save_error")) and self._tr_lines:
            self.notebook.select(self.TAB_SUBS)
            if result.get("sample"):
                first = str(result.get("offset", 0))
                if self.tree.exists(first):
                    self.tree.see(first)
                    self.tree.selection_set(first)
        if dialog == "save_failed":
            self._show_save_failed(result)
        elif dialog == "finished" and self.finish_message.get():
            self._show_finished(result)

    # ── Finish messages (v0.8.1) ─────────────────────────────────────

    def _cost_rows(self, result: dict) -> list:
        """[(label, text, colour)] for the cost part of the finish messages."""
        if result.get("engine") != "claude":
            return [("Cost", "free (MyMemory)", COLORS["text"])]
        u = result["usage"]
        rows = [("Cost of this run",
                 f"{format_usd(result.get('cost'))}   ·   {result.get('model_name', '')}   ·   {u.input:,} in · "
                 f"{u.output:,} out · {u.cache_read:,} cached", COLORS["yellow"])]
        est = result.get("estimate") or {}
        if est.get("total_cost") is not None:
            rows.append(("Estimate was", f"~{format_usd(est['total_cost'])}  "
                                         f"({'exact input count' if est.get('method') == 'exact' else 'approx.'})",
                         COLORS["text_dim"]))
        if same_file(result.get("file", ""), self.input_path) and len(self.cost_ledger.entries) > 1:
            rows.append(("Total for this subtitle",
                         f"{format_usd(self.cost_ledger.total())}   ({self.cost_ledger.breakdown()})", COLORS["yellow"]))
        src_text, trusted = price_source_text(self.catalog, result["price"])
        rows.append(("Prices", src_text, COLORS["text_dim"] if trusted else COLORS["warning"]))
        return rows

    def _message_dialog(self, title, headline, rows, buttons, w=620):
        dlg = self._dialog(title, w, 120 + 26 * len(rows))
        dlg.resizable(False, False)
        head = tk.Frame(dlg, bg=COLORS["bg_card"])
        head.pack(fill="x", padx=20, pady=(16, 8))
        if 20 in self._icons and title == "Translation finished":
            tk.Label(head, image=self._icons[20], bg=COLORS["bg_card"]).pack(side="left", padx=(0, 10))
        tk.Label(head, text=headline, font=FONTS["heading"], fg=COLORS["text_bright"], bg=COLORS["bg_card"],
                 anchor="w").pack(side="left")
        grid = tk.Frame(dlg, bg=COLORS["bg_card"])
        grid.pack(fill="x", padx=20)
        grid.columnconfigure(1, weight=1)
        for r, (label, text, colour) in enumerate(rows):
            tk.Label(grid, text=label, font=FONTS["tiny"], fg=COLORS["text_dim"], bg=COLORS["bg_card"],
                     anchor="nw").grid(row=r, column=0, sticky="nw", padx=(0, 14), pady=2)
            tk.Label(grid, text=text, font=FONTS["small"], fg=colour, bg=COLORS["bg_card"], anchor="w",
                     justify="left", wraplength=self.px(w - 210)).grid(row=r, column=1, sticky="w", pady=2)
        br = tk.Frame(dlg, bg=COLORS["bg_card"])
        br.pack(side="bottom", fill="x", padx=20, pady=(8, 16))
        for text, cmd, primary in reversed(buttons):
            self._flat_btn(br, text, (lambda c=cmd: (dlg.destroy(), c())), primary=primary, dim=not primary,
                           padx=14, pady=5).pack(side="right", padx=(6, 0))
        dlg.update_idletasks()
        dlg.geometry(f"{self.px(w)}x{max(dlg.winfo_reqheight(), self.px(160))}")
        try:
            if self.state() == "iconic":
                self.deiconify()
            if self.focus_displayof() is None:
                self.bell()
            dlg.lift()
            dlg.focus_force()
        except tk.TclError:
            pass
        return dlg

    def _show_finished(self, result: dict):
        path = result.get("saved_path", "")
        n_flag = result.get("flagged", 0)
        verified = result.get("verified")
        rows = [("Saved", Path(path).name, COLORS["text_bright"]),
                ("Folder", str(Path(path).parent), COLORS["text_dim"]),
                ("Blocks", f"{result.get('total', 0):,} translated · "
                           + (f"{n_flag} flagged" if n_flag else "none flagged") + " · "
                           + ("structure verified ✓" if verified else "structure check FAILED ✗ (see Log)"
                              if verified is False else "structure not checked"),
                 COLORS["success"] if verified and not n_flag else COLORS["warning"])]
        rows += self._cost_rows(result)
        buttons = [("Open folder", lambda: self._open_folder(path), False)]
        if n_flag:
            buttons.append(("Show flagged blocks", self._show_first_flagged, False))
        buttons.append(("OK", lambda: None, True))
        self._message_dialog("Translation finished", "Translation finished", rows, buttons)

    def _show_save_failed(self, result: dict):
        rows = [("Could not save", self.output_path, COLORS["text_bright"]),
                ("Reason", result.get("save_error", ""), COLORS["error"])]
        rows += self._cost_rows(result)
        rows.append(("Your translation", "is still in the app (Subtitles tab). Use Save as… to save it "
                                         "somewhere else.", COLORS["text"]))
        self._message_dialog("Translation not saved", "⚠  The translation could not be saved", rows,
                             [("Save as…", self._save_translation_as, True), ("Close", lambda: None, False)])

    def _save_translation_as(self):
        if not self.translated_blocks:
            return
        default_name = (Path(self.output_path).name if self.output_path else self._output_name())
        ext = Path(default_name).suffix or ".srt"
        out = filedialog.asksaveasfilename(title="Save translated file as", defaultextension=ext,
                                           initialfile=default_name,
                                           initialdir=str(Path(self.input_path).parent) if self.input_path else "",
                                           filetypes=[(f"{ext.lstrip('.').upper()} files", f"*{ext}"),
                                                      ("All files", "*.*")])
        if not out:
            return
        try:
            fmt = "srt" if out.lower().endswith(".srt") else "same"
            text = render_subtitle(self.doc, self.translated_blocks, fmt)
            enc, _ = output_encoding_for(self.output_enc.get(), self.doc.encoding if self.doc else "", text,
                                         fmt == "srt")
            write_subtitle_text(text, out, enc)
        except Exception as e:
            messagebox.showerror("Save failed", f"Could not save:\n{out}\n\n{e}")
            return
        self.output_path = out
        self._last_saved = out
        self._last_output_dir = str(Path(out).parent)
        self._show_open_link(True)
        self._log(f"File saved: {out}", "success")
        self.status_text.set(f"Saved {Path(out).name}")

    def _open_folder(self, path: str):
        if not path:
            return
        try:
            if os.name == "nt":
                subprocess.Popen(["explorer", "/select,", str(Path(path))])
            else:
                webbrowser.open(Path(path).parent.as_uri())
        except Exception as e:
            self._log(f"Could not open the folder: {e}", "warn")

    def _show_first_flagged(self):
        self.notebook.select(self.TAB_SUBS)
        self._filter.set("flagged")
        kids = self.tree.get_children()
        if kids:
            self.tree.selection_set(kids[0])
            self.tree.see(kids[0])

    def _cancel(self):
        self.cancel_flag = True
        self.status_text.set("Cancelling…")

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
    _set_dpi_awareness()
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
