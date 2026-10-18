"""
SRT Studio — timing core for sync (v0.10.0 · S1).

Pure functions, no Tk: everything here is unit-tested in tests/test_sync.py.

A block is the app's dict {"id", "timestamp": "HH:MM:SS,mmm --> HH:MM:SS,mmm", "text_lines": [...]}.
Every function returns NEW blocks; the old ones are left as they were (the preview and Undo need them).

A time map turns an old time (ms) into a new one. It is a list of segments, each one linear:
    new = old * ratio + offset            for  old >= segment start
so a shift, a frame-rate change, a two-point fix and a piecewise fix (cuts, S2/S4) are all the same thing.
"""

import re
from datetime import datetime

_TS_RE = re.compile(r"(\d+):(\d\d):(\d\d)[,.](\d{1,3})\s*-->\s*(\d+):(\d\d):(\d\d)[,.](\d{1,3})")
_CLOCK_RE = re.compile(r"^\s*([+-])?\s*(?:(\d+):)?(\d{1,2}):(\d{1,2})(?:[,.](\d{1,3}))?\s*$")
_SECONDS_RE = re.compile(r"^\s*([+-])?\s*(\d+(?:[.,]\d*)?|[.,]\d+)\s*(?:s|sec|seconds?)?\s*$", re.I)

RATIO_MIN, RATIO_MAX = 0.5, 2.0          # anything outside is a typing mistake, not a frame-rate change

# Frame-rate presets: (subtitle made for, video). ratio = from / to (a 25 fps subtitle on a 23.976 video runs 4 % short)
FPS_PRESETS = [(23.976, 25), (25, 23.976), (24, 25), (25, 24), (23.976, 24), (24, 23.976),
               (29.97, 23.976), (23.976, 29.97)]


# ── times ────────────────────────────────────────────────────────────

def to_ms(text) -> int:
    """'01:02:03,450' / '1:02:03.45' / '02:03' (mm:ss) / '+2.35' / '-0,5 s' / 2.35 → milliseconds (int).
    Raises ValueError for anything else. Hours above 99 are fine."""
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        return int(round(float(text) * 1000))
    s = str(text or "").strip()
    m = _CLOCK_RE.match(s)
    if m:
        sign, h, mi, se, frac = m.groups()
        if int(se) > 59 or (h is not None and int(mi) > 59):
            raise ValueError(f"not a time: {text!r}")
        ms = ((int(h or 0) * 60 + int(mi)) * 60 + int(se)) * 1000 + int((frac or "0").ljust(3, "0"))
        return -ms if sign == "-" else ms
    m = _SECONDS_RE.match(s)
    if m:
        sign, num = m.groups()
        ms = int(round(float(num.replace(",", ".")) * 1000))
        return -ms if sign == "-" else ms
    raise ValueError(f"not a time: {text!r}")


def fmt_ms(ms) -> str:
    """Milliseconds → 'HH:MM:SS,mmm'. Negative times are shown as 0; hours above 99 get more digits."""
    ms = max(0, int(round(ms)))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, rem = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{rem:03d}"


def fmt_offset(ms) -> str:
    """+2350 → '+2.350 s', -1000 → '−1.000 s' (a real minus sign), 0 → '0.000 s'."""
    ms = int(round(ms))
    if ms == 0:
        return "0.000 s"
    return f"{'+' if ms > 0 else '−'}{abs(ms) / 1000:.3f} s"


def fmt_seconds(ms) -> str:
    """-1250 → '-1.250' (for the Shift field: plain ASCII, so it can be typed back)."""
    ms = int(round(ms))
    return f"{'-' if ms < 0 else ''}{abs(ms) // 1000}.{abs(ms) % 1000:03d}"


def parse_timestamp(ts: str):
    """'00:01:02,345 --> 00:01:04,000' → (62345, 64000); None if it is not a timing line."""
    m = _TS_RE.search(ts or "")
    if not m:
        return None
    g = m.groups()
    start = ((int(g[0]) * 60 + int(g[1])) * 60 + int(g[2])) * 1000 + int(g[3].ljust(3, "0"))
    end = ((int(g[4]) * 60 + int(g[5])) * 60 + int(g[6])) * 1000 + int(g[7].ljust(3, "0"))
    return start, end


def make_timestamp(start_ms, end_ms) -> str:
    return f"{fmt_ms(start_ms)} --> {fmt_ms(end_ms)}"


def block_times(blocks) -> list:
    """[(start, end)] for every block; (0, 0) for a block without a readable timing line."""
    return [parse_timestamp(b.get("timestamp", "")) or (0, 0) for b in blocks]


# ── time maps ────────────────────────────────────────────────────────

class TimeMap:
    """A piecewise-linear old → new time function. segments: [(from_ms, ratio, offset_ms)], sorted by from_ms;
    the first segment also covers everything before its start."""

    def __init__(self, segments, kind="", label=""):
        segs = sorted((int(a), float(r), float(o)) for a, r, o in segments)
        if not segs:
            raise ValueError("a time map needs at least one segment")
        for _, r, _ in segs:
            if not (RATIO_MIN <= r <= RATIO_MAX):
                raise ValueError(f"speed ratio {r:.4f} is out of range ({RATIO_MIN}–{RATIO_MAX})")
        self.segments, self.kind, self.label = segs, kind, label
        self._starts = [a for a, _, _ in segs]

    def segment_for(self, t) -> tuple:
        import bisect
        k = bisect.bisect_right(self._starts, t) - 1
        return self.segments[max(0, k)]

    def __call__(self, t) -> int:
        _, r, o = self.segment_for(t)
        return int(round(t * r + o))

    @property
    def is_identity(self) -> bool:
        return all(abs(r - 1) < 1e-9 and abs(o) < 0.5 for _, r, o in self.segments)

    @property
    def is_linear(self) -> bool:
        return len(self.segments) == 1

    @property
    def ratio(self) -> float:
        return self.segments[0][1]

    def offset_at(self, t) -> int:
        """How much the time t moves: new − old."""
        return self(t) - int(round(t))

    def __repr__(self):
        return f"TimeMap({self.segments!r}, kind={self.kind!r})"


def map_shift(ms) -> TimeMap:
    return TimeMap([(0, 1.0, ms)], kind="shift", label=f"Shift {fmt_offset(ms)}")


def map_scale(ratio, anchor_ms=0) -> TimeMap:
    """new = anchor + (old − anchor) × ratio. ratio > 1 makes the subtitle slower (longer)."""
    ratio = float(ratio)
    return TimeMap([(0, ratio, anchor_ms * (1 - ratio))], kind="scale",
                   label=f"Frame rate {describe_ratio(ratio)}")


def fps_ratio(fps_from, fps_to) -> float:
    """Ratio for a subtitle timed for fps_from used on a video at fps_to."""
    return float(fps_from) / float(fps_to)


def map_two_point(a, b) -> TimeMap:
    """a, b = (old_ms, new_ms): the straight line through both points (fixes offset and speed together)."""
    (sa, da), (sb, db) = a, b
    if sb == sa:
        raise ValueError("the two points need different times")
    ratio = (db - da) / (sb - sa)
    if not (RATIO_MIN <= ratio <= RATIO_MAX):
        raise ValueError(f"these two points give a speed ratio of {ratio:.4f}, which cannot be right: "
                         "check the times (the second block must come after the first)")
    return TimeMap([(0, ratio, da - ratio * sa)], kind="two_point",
                   label=f"Two points (offset {fmt_offset(da - sa)}, speed {ratio:.5f})")


def map_piecewise(segments, kind="piecewise", label="") -> TimeMap:
    """segments = [(from_ms, ratio, offset_ms)] or [(from_ms, offset_ms)] (ratio 1)."""
    segs = [(s[0], 1.0, s[1]) if len(s) == 2 else s for s in segments]
    return TimeMap(segs, kind=kind, label=label or f"{len(segs)} segment(s)")


def describe_ratio(ratio, tol=0.0006) -> str:
    """1.04271 → '25 → 23.976 fps'; 1.0 → 'same speed'; else 'speed ×1.01234'."""
    if abs(ratio - 1) < 1e-6:
        return "same speed"
    for f, t in FPS_PRESETS:
        if abs(fps_ratio(f, t) - ratio) < tol:
            return f"{_fps(f)} → {_fps(t)} fps"
    return f"speed ×{ratio:.5f}"


def _fps(x) -> str:
    return f"{x:g}"


# ── applying a map ───────────────────────────────────────────────────

class SyncResult:
    """New blocks plus what happened to them. dropped / clamped: indexes into the OLD block list."""

    def __init__(self, blocks, moved, clamped, dropped, tmap):
        self.blocks, self.moved, self.clamped, self.dropped, self.tmap = blocks, moved, clamped, dropped, tmap


def apply_map(blocks, tmap: TimeMap, min_ms: int = 1) -> SyncResult:
    """Retime every block. A start below 0 is clamped to 0; a block whose new end is ≤ 0 is dropped (it would
    be before the film). The new blocks carry "_synced": True; blocks without a timing line are kept as they are."""
    out, moved, clamped, dropped = [], 0, [], []
    for i, b in enumerate(blocks):
        t = parse_timestamp(b.get("timestamp", ""))
        if t is None:
            out.append(dict(b))
            continue
        s, e = tmap(t[0]), tmap(t[1])
        if e <= 0:
            dropped.append(i)
            continue
        if s < 0:
            s = 0
            clamped.append(i)
        if e < s + min_ms:
            e = s + min_ms
        nb = {**b, "timestamp": make_timestamp(s, e), "text_lines": list(b.get("text_lines", []))}
        if (s, e) != t:
            moved += 1
            nb["_synced"] = True
        out.append(nb)
    return SyncResult(out, moved, clamped, dropped, tmap)


def shift(blocks, ms) -> list:
    return apply_map(blocks, map_shift(ms)).blocks


def scale(blocks, ratio, anchor_ms=0) -> list:
    return apply_map(blocks, map_scale(ratio, anchor_ms)).blocks


def two_point(blocks, a, b) -> list:
    return apply_map(blocks, map_two_point(a, b)).blocks


def piecewise(blocks, segments) -> list:
    return apply_map(blocks, map_piecewise(segments)).blocks


# ── which blocks are dialogue ────────────────────────────────────────

_NOTICE_RE = re.compile(r"(?i)\b(subtitles?|legendas?|subt[ií]tulos?|sous-titres|untertitel|sottotitoli)\b.*"
                        r"\b(by|por|par|von|da|de)\b|https?://|www\.|\.(com|org|net)\b")


def dialogue_indexes(blocks) -> list:
    """Indexes of blocks that look like dialogue: timed, with text, not a credit/ad line. Used for the default
    blocks of Two points and for hints."""
    out = []
    for i, b in enumerate(blocks):
        if parse_timestamp(b.get("timestamp", "")) is None:
            continue
        text = " ".join(l for l in b.get("text_lines", []) if l.strip())
        if not text or _NOTICE_RE.search(text) or b.get("_notice"):
            continue
        out.append(i)
    return out


# ── hints with no reference ──────────────────────────────────────────

LATE_START_MS = 10 * 60_000
VIDEO_TOLERANCE_MS = 5_000
_NAME_FPS_RE = re.compile(r"(?i)(?<![\d.])(23[.,]976|23[.,]98|24|25|29[.,]97|30)\s*fps|\b(PAL)\b|\b(NTSC)\b")


def hints(blocks, video_ms=None, video_fps=None, name: str = "") -> list:
    """Clues from the subtitle alone (and the video's length when it is known). Each hint:
    {"kind", "text", "fill": {method, values…}} — "fill" pre-fills Fine-tune when the user presses Try it."""
    idx = dialogue_indexes(blocks)
    if not idx:
        return []
    times = block_times(blocks)
    first_i, last_i = idx[0], idx[-1]
    first_s, last_e = times[first_i][0], times[last_i][1]
    out = []
    if first_s >= LATE_START_MS:
        out.append({"kind": "late_start",
                    "text": f"The first line starts unusually late, at {fmt_ms(first_s)[:8]}. If it should come "
                            "earlier, type its correct time in Two points (block A).",
                    "fill": {"method": "two_point", "a": first_i, "b": last_i}})
    zero = sum(1 for i in idx if times[i][0] == 0)
    if zero >= 2 or (idx and first_s < 200 and len(idx) > 20):
        out.append({"kind": "early_start",
                    "text": f"The first line starts unusually early ({fmt_ms(first_s)}"
                            + (f", {zero} lines at 0:00" if zero >= 2 else "") + "). The subtitle may have been "
                            "shifted too far back.",
                    "fill": {"method": "two_point", "a": first_i, "b": last_i}})
    if video_ms and last_e > video_ms + VIDEO_TOLERANCE_MS:
        # The subtitle must shrink at least to video/last to fit; the end credits make the video longer than the
        # last line, so the length alone cannot give the exact ratio: take the smallest frame-rate change that fits.
        best, alt = _preset_that_fits(video_ms / float(last_e), video_fps)
        where = (f"The last line ends at {fmt_ms(last_e)[:8]}, after the end of the video "
                 f"({fmt_ms(video_ms)[:8]})")
        if best:
            f, t = best
            also = f" ({_fps(alt[0])} fps is nearly the same)" if alt else ""
            out.append({"kind": "frame_rate",
                        "text": f"{where}. The subtitle was probably made for {_fps(f)} fps{also} and the video "
                                f"is {_fps(t)} fps.",
                        "fill": {"method": "scale", "from": f, "to": t}})
        else:
            out.append({"kind": "too_long", "text": f"{where}: the offset or the speed is wrong.",
                        "fill": {"method": "two_point", "a": first_i, "b": last_i}})
    m = _NAME_FPS_RE.search(name or "")
    if m and video_fps:
        named = 25.0 if m.group(2) else 29.97 if m.group(3) else float(m.group(1).replace(",", "."))
        named = 23.976 if abs(named - 23.98) < 0.01 else named
        if abs(named - video_fps) > 0.05:
            out.append({"kind": "name_fps",
                        "text": f"The file name says {_fps(named)} fps; the video is {_fps(video_fps)} fps.",
                        "fill": {"method": "scale", "from": named, "to": video_fps}})
    return out


MIN_OVERRUN = 0.02      # a subtitle at least 2 % longer than the video: too much for end credits to hide
FIT_SLACK = 0.025       # the subtitle may then be up to this much shorter than "just fits" (end credits)
SAME_RATE = 0.0015      # 23.976 and 24 fps differ by 0.1 %: a length cannot tell them apart


def _preset_that_fits(bound, video_fps=None):
    """The frame-rate preset with the smallest change that still makes the subtitle fit (ratio ≤ bound), and a
    second one that is nearly the same, if any. A tie goes to the preset listed first (23.976 before 24:
    the PAL speed-up is by far the most common case). (None, None) when the overrun is small (an offset, or
    a frame-rate change hidden by the credits: cannot tell) or no preset fits closely enough."""
    if bound > 1 / (1 + MIN_OVERRUN):
        return None, None
    usable = [(fps_ratio(f, t), k, (f, t)) for k, (f, t) in enumerate(FPS_PRESETS)
              if fps_ratio(f, t) < 1 and (not video_fps or abs(t - video_fps) <= 0.05)]
    fits = [c for c in usable if c[0] <= bound + 0.0005]
    if not fits:
        return None, None
    top = max(c[0] for c in fits)
    if bound - top > FIT_SLACK:
        return None, None
    best = min((c for c in fits if c[0] >= top - SAME_RATE), key=lambda c: c[1])
    alt = [c for c in usable if c is not best and abs(c[0] - best[0]) <= SAME_RATE]
    return best[2], (min(alt, key=lambda c: c[1])[2] if alt else None)


# ── preview and report ───────────────────────────────────────────────

def preview_indexes(n, k=5) -> list:
    """First k, k around the middle and last k block indexes (no repeats), in order."""
    if n <= 3 * k:
        return list(range(n))
    mid = n // 2 - k // 2
    return sorted(set(range(k)) | set(range(mid, mid + k)) | set(range(n - k, n)))


def preview_rows(old_blocks, result: SyncResult, k=5) -> list:
    """[(id, old start, new start, text)] for the preview table; a dropped block shows '(dropped)'."""
    new_by_old, j = {}, 0
    dropped = set(result.dropped)
    for i in range(len(old_blocks)):
        if i in dropped:
            continue
        new_by_old[i] = result.blocks[j]
        j += 1
    rows = []
    for i in preview_indexes(len(old_blocks), k):
        b = old_blocks[i]
        old = parse_timestamp(b.get("timestamp", ""))
        nb = new_by_old.get(i)
        new = parse_timestamp(nb["timestamp"]) if nb else None
        text = " / ".join(l for l in b.get("text_lines", []) if l.strip())
        rows.append((b.get("id", str(i + 1)), fmt_ms(old[0]) if old else b.get("timestamp", "")[:12],
                     fmt_ms(new[0]) if new else "(dropped)", text))
    return rows


def first_words(block, n=6) -> str:
    words = " ".join(l for l in block.get("text_lines", []) if l.strip()).split()
    return " ".join(words[:n]) + (" …" if len(words) > n else "")


def build_report(info: dict) -> str:
    """The sync report (decision 12) as plain text. info keys (all optional except file and method):
    file, format, encoding, language, blocks, method, reference, result (list of lines), segments
    [(from, to, offset)], confidence, overlap (before, after), moved, clamped, dropped (lists of (time, words)),
    ads_removed, unmatched (list of (time, words)), sample (list of (id, old, new, text)), output, backup,
    app_version, already_in_sync (bool), notes (list)."""
    L = []
    add = L.append
    add("SRT Studio — sync report")
    add("=" * 40)
    add(f"File:        {info.get('file', '')}")
    meta = [x for x in (info.get("format"), info.get("encoding"), info.get("language")) if x]
    if meta:
        add(f"             {' · '.join(meta)}")
    if info.get("blocks") is not None:
        add(f"Blocks:      {info['blocks']:,}")
    add(f"Method:      {info.get('method', '')}")
    if info.get("reference"):
        add(f"Reference:   {info['reference']}")
    add("")
    if info.get("already_in_sync"):
        add("Result:      already in sync — nothing was changed or written.")
    else:
        add("Result:")
        for line in info.get("result") or []:
            add(f"  {line}")
        if info.get("segments"):
            add("  Segments:")
            for a, b, off in info["segments"]:
                add(f"    {fmt_ms(a)[:8]} – {fmt_ms(b)[:8]}   {fmt_offset(off)}")
        if info.get("confidence") is not None:
            add(f"  Confidence: {info['confidence']:.2f}")
        if info.get("overlap"):
            before, after = info["overlap"]
            add(f"  Overlap with the reference: {before:.2f} → {after:.2f}")
    add("")
    add("What changed:")
    add(f"  Blocks moved: {info.get('moved', 0):,}")
    for key, label in (("clamped", "Times clamped at 0"), ("dropped", "Dropped (ended before 0:00)"),
                       ("unmatched", "No counterpart in the reference")):
        items = info.get(key) or []
        add(f"  {label}: {len(items)}")
        for t, words in items[:20]:
            add(f"    {fmt_ms(t)[:12]}  {words}")
        if len(items) > 20:
            add(f"    … and {len(items) - 20} more")
    if info.get("ads_removed"):
        add(f"  Ad lines removed (repair): {info['ads_removed']}")
    for note in info.get("notes") or []:
        add(f"  {note}")
    if info.get("sample"):
        add("")
        add("Before → after (sample):")
        for bid, old, new, text in info["sample"]:
            add(f"  #{bid:<5} {old} → {new}   {text[:60]}")
    add("")
    add(f"Output:      {info.get('output') or 'not saved (applied in the app only)'}")
    if info.get("backup"):
        add(f"Backup:      {info['backup']}")
    add(f"Date:        {info.get('date') or datetime.now().strftime('%Y-%m-%d %H:%M')}")
    if info.get("app_version"):
        add(f"App:         SRT Studio {info['app_version']}")
    return "\n".join(L) + "\n"


def sample_for_report(old_blocks, result: SyncResult, k=3) -> list:
    return preview_rows(old_blocks, result, k)


# ══ MATCHING (v0.10.0 · S2, reused by S4) ════════════════════════════
#
# Two subtitles of the same film have text on screen at the same moments, whatever their language. Each one
# becomes an on/off signal; an FFT cross-correlation finds the offset that makes them overlap most, for each
# frame-rate candidate. Then the subtitle is cut into 3-minute windows and each window is searched against
# the whole reference. A window path (Viterbi) picks one offset per window and pays for every change, and a
# part with another offset is kept only when its own lines match clearly better there than anywhere else:
# that is a different cut (scenes added or removed). S4 builds the reference signal from the speech in the
# audio instead of a subtitle and reuses all of this.

STEP_MS = 10                       # fine grid: final offsets and overlaps
COARSE_MS = 50                     # coarse grid: the searches
MATCH_RATIOS = [1.0, 25 / 23.976, 23.976 / 25, 24 / 23.976, 23.976 / 24, 25 / 24, 24 / 25, 30 / 29.97, 29.97 / 30]
MAX_OFFSET_MS = 600_000            # global offset: ±10 min
WIN_MS, HOP_MS = 180_000, 90_000   # cut detection: 3-minute windows, half overlapping
SWITCH_PENALTY = 0.30              # cost of an offset change in the window path
SAME_LAG_MS = 500                  # windows within 0.5 s of each other agree
CUT_GAIN = 0.15                    # a part must also beat the global offset by this in its windows (plan S2)
SUBTITLE_GAIN = 0.85               # a typical global gain between two subtitles (audio thresholds scale to it)
PART_OVERLAP_MS = 30_000           # two parts may land on the same stretch of the film for at most 30 s
CUT_MARGIN = 0.12                  # a part's lines must match this much better at its offset than at any other
PROOF_RANGE_MS = 600_000           # … other offset within ±10 min of it
SHORT_CUT_MARGIN = 0.20            # a part of only 2 windows (4.5 min) must match even more clearly
NEAR_BEST = 0.10                   # an offset within this of a window's best is a candidate there …
MIN_PART_GAIN = 0.30               # … when its gain is at least this
NEAR_LAG_MS = 1_500                # parts closer than this differ by uneven timing, not by a cut …
NEAR_GAIN = 0.10                   # … and need this much better overlap than at the neighbouring offset
IN_SYNC_MS = 200                   # "in sync": every offset below 0.2 s
LOW_CONFIDENCE = 0.5               # below: "Low confidence — check the preview before applying"
CANNOT_TELL = 0.35                 # below: "? Cannot tell" (nothing in common, e.g. a different film)
UNEVEN_MEDIAN_MS = 250             # line-by-line differences above this median: "uneven timing"
NO_SUBTITLE_MS = 60_000            # reference text for this long with no subtitle line: listed in the report
MIN_DIALOGUE = 0.05                # a window with less text than this share of its time says nothing
MIN_LINES = 10                     # fewer dialogue lines than this: "? Cannot tell" (they fit in too many places)
PLATEAU = 0.005                    # overlap within 0.5 % of the best counts as the top of the peak
SEC_WIN_MS, SEC_HOP_MS = 120_000, 120_000   # uneven timing: 2-minute sections …
SEC_RANGE_MS = 2_000               # … each may move up to ±2 s from its part …
SEC_GAIN = 0.10                    # … when that gives at least 10 % more overlap …
SEC_MIN_MS = 250                   # … and moves it by at least 0.25 s …
SEC_AGREE_MS = 200                 # … and the next section agrees within 0.2 s
EDGE_MARGIN = 0.10                 # a one-window part at the very start or end (a different intro) needs this
EDGE_MS = 240_000                  # the first and last 4 minutes are checked on their own (a different intro)
EDGE_GAIN = 0.30                   # … and must match this much better at their own offset
SAME_LEN_MS = 20                   # a reference line of the same length (±20 ms) …
LINE_SEARCH_MS = 2_000             # … starting within ±2 s is this line's counterpart
LINE_SHARE = 0.5                   # half the lines with a counterpart: the reference shares the line timing
LINE_OFF_MS = 50                   # with shared timing, a line more than 50 ms off its counterpart is off …
LINE_UNEVEN_SHARE = 0.15           # … and when 15 % of the lines are off, they are aligned line by line
AUDIO_MARGIN_LOW, AUDIO_MARGIN_HIGH = 0.02, 0.10   # audio confidence from the peak margin (calibrated, S4)
AUDIO_GAP_DENSITY = 0.35           # audio: a stretch with no subtitle is "speech" only when mostly speech

STATUS_LABELS = {"in_sync": "✅ In sync", "offset": "⚠ Constant offset", "drift": "⚠ Speed drift",
                 "offset_drift": "⚠ Offset and drift", "uneven": "⚠ Uneven timing", "cut": "⛔ Different cut",
                 "cannot_tell": "? Cannot tell"}


class Cancelled(Exception):
    """The user pressed Cancel."""


def _np():
    import numpy as np  # noqa: F401  (lazy: Shift / Frame rate / Two points work without numpy)
    return np


def times_array(blocks, indexes=None):
    """(k, 2) float array of (start, end) ms for the given block indexes (default: the dialogue blocks)."""
    np = _np()
    idx = dialogue_indexes(blocks) if indexes is None else indexes
    t = [parse_timestamp(blocks[i]["timestamp"]) or (0, 0) for i in idx]
    return np.array([(a, max(b, a + 1)) for a, b in t], dtype=float).reshape(-1, 2)


def on_signal(times, n, step=STEP_MS):
    """1.0 where some text is on screen, else 0.0, in steps of `step` ms; length n."""
    np = _np()
    d = np.zeros(n + 1, np.int32)
    if len(times):
        a = np.clip(np.floor(times[:, 0] / step).astype(np.int64), 0, n)
        b = np.clip(np.ceil(times[:, 1] / step).astype(np.int64), 0, n)
        np.add.at(d, a, 1)
        np.add.at(d, b, -1)
    return (np.cumsum(d[:-1]) > 0).astype(np.float32)


def _gain(overlap_share, density):
    """How much better than chance: 0 = what a random offset gives, 1 = perfect overlap."""
    return (overlap_share - density) / (1 - density) if density < 1 else overlap_share * 0


def _fft_len(n):
    return 1 << max(1, int(n - 1).bit_length())


class MatchResult:
    """What the matcher found. new = old × ratio + offset, per part of the subtitle's own time."""

    def __init__(self):
        self.ratio = 1.0
        self.segments = []          # [{"from_ms", "to_ms", "offset_ms", "windows"}] in the subtitle's time
        self.tmap = None
        self.confidence = 0.0
        self.overlap_before = self.overlap_after = 0.0
        self.gain_before = 0.0
        self.status = "cannot_tell"
        self.unmatched = []         # subtitle block indexes with no reference text under them after the sync
        self.ref_gaps = []          # [(start, end)] reference text with no subtitle line for ≥ 60 s
        self.median_line_ms = None  # line-by-line difference after the sync (nearest reference start)
        self.shared_timing = False  # the reference has the same line timing (same file, or a translation of it)
        self.reference = "subtitle"  # or "audio" (S4)
        self.peak_margin = None     # audio: how much better the best offset is than the best other one
        self.lines_aligned = 0      # lines moved one by one onto their counterpart
        self.notes = []
        self.elapsed = 0.0
        self.duration_ms = 0

    @property
    def offset_ms(self) -> int:
        return int(self.segments[0]["offset_ms"]) if self.segments else 0

    @property
    def drift_ms(self) -> int:
        """How far the speed difference moves the last line."""
        return int(round((self.ratio - 1) * self.duration_ms))

    @property
    def low_confidence(self) -> bool:
        return self.confidence < LOW_CONFIDENCE

    @property
    def is_identity(self) -> bool:
        return self.tmap is None or self.tmap.is_identity

    @property
    def status_label(self) -> str:
        return STATUS_LABELS[self.status]

    def status_text(self, ref_name: str = "") -> str:
        """One sentence: '⚠ Constant offset: subtitles appear 1.0 s early', …"""
        vs = f" compared with {ref_name}" if ref_name else ""
        s = self.status
        if s == "in_sync":
            return f"✅ In sync{vs}"
        if s == "cannot_tell":
            return f"? Cannot tell{vs}: the two have too little in common (confidence {self.confidence:.2f})"
        if s == "cut":
            offs = [g["offset_ms"] for g in self.segments]
            return (f"⛔ Different cut{vs}: {len(self.segments)} parts with different offsets "
                    f"({fmt_offset(min(offs))} to {fmt_offset(max(offs))})")
        if s == "uneven":
            if len(self.segments) > 1:
                offs = [g["offset_ms"] for g in self.segments]
                return (f"⚠ Uneven timing{vs}: {len(self.segments)} sections, offsets "
                        f"{fmt_offset(min(offs))} to {fmt_offset(max(offs))}")
            if self.lines_aligned:
                return f"⚠ Uneven timing{vs}: {self.lines_aligned} lines are off; aligned line by line"
            return f"⚠ Uneven timing{vs}: lines differ by a median {self.median_line_ms / 1000:.2f} s"
        when = (f"subtitles appear {abs(self.offset_ms) / 1000:.1f} s "
                f"{'early' if self.offset_ms > 0 else 'late'}")       # the fix moves them later → early now
        rate = describe_ratio(self.ratio)
        if s == "offset":
            return f"⚠ Constant offset{vs}: {when}"
        if s == "drift":
            return f"⚠ Speed drift{vs}: {rate}, about {abs(self.drift_ms) / 1000:.0f} s over the film"
        return f"⚠ Offset and drift{vs}: {when}, {rate}"

    def fix_label(self) -> str:
        if len(self.segments) > 1:
            return f"Fix it: {len(self.segments)} parts"
        if abs(self.ratio - 1) > 1e-6:
            return f"Fix it: {describe_ratio(self.ratio)}" + (
                f", {fmt_offset(self.offset_ms)}" if abs(self.offset_ms) >= IN_SYNC_MS else "")
        return f"Fix it: shift {fmt_offset(self.offset_ms)}"


def _block_overlaps(cs, times, lag_steps, n):
    """Reference on-time under each line for a lag (fine steps), from the reference's cumulative sum."""
    np = _np()
    a = np.clip(np.floor(times[:, 0] / STEP_MS).astype(np.int64) + lag_steps, 0, n)
    b = np.clip(np.ceil(times[:, 1] / STEP_MS).astype(np.int64) + lag_steps, 0, n)
    return cs[b] - cs[a]


def _overlap_curve(cs, times, lag, n, radius):
    """Reference time under these lines for every lag in lag ± radius (fine steps)."""
    np = _np()
    a0 = np.floor(times[:, 0] / STEP_MS).astype(np.int64)
    b0 = np.ceil(times[:, 1] / STEP_MS).astype(np.int64)
    d = np.arange(-radius, radius + 1)
    v = np.array([float((cs[np.clip(b0 + lag + k, 0, n)] - cs[np.clip(a0 + lag + k, 0, n)]).sum()) for k in d])
    return d, v


def _plateau_centre(d, v):
    """The middle of the top of the curve: a broad top (lines of another language) gives its centre, not the
    first maximum on one side of it."""
    np = _np()
    top = v.max()
    if top <= 0:
        return 0
    on = v >= top * (1 - PLATEAU)
    j = int(np.argmax(v))                      # the contiguous stretch around the maximum
    a = j
    while a > 0 and on[a - 1]:
        a -= 1
    b = j
    while b + 1 < len(on) and on[b + 1]:
        b += 1
    return int(round((d[a] + d[b]) / 2))


def _refine_lag(cs, times, lag, n, radius):
    """Best lag (fine steps) within ±radius of lag for these lines alone (the centre of the overlap peak)."""
    d, v = _overlap_curve(cs, times, lag, n, radius)
    return lag + _plateau_centre(d, v)


class _Search:
    """Correlation of subtitle pieces against the whole reference, on the coarse grid."""

    def __init__(self, ref_c, dens):
        np = _np()
        self.n = len(ref_c)
        self.ref = ref_c
        self.dens = dens
        self.neg = MAX_OFFSET_MS // COARSE_MS          # the piece may also start before the reference
        self.L = _fft_len(self.n + WIN_MS // COARSE_MS + self.neg)
        self.fr = np.fft.rfft(ref_c, self.L)

    def gains(self, piece, at):
        """Gain for every lag (coarse steps) of `piece`, a signal that starts at coarse index `at`:
        returns (lags, gains); the piece is tried at every place in the reference, and up to 10 min before it."""
        np = _np()
        on = float(piece.sum())
        if on <= 0:
            return None
        L, fr = self.L, self.fr
        if len(piece) + self.n + self.neg > L:      # a long piece (a whole part): its own FFT size
            L = _fft_len(self.n + len(piece) + self.neg)
            fr = np.fft.rfft(self.ref, L)
        c = np.fft.irfft(fr * np.conj(np.fft.rfft(piece, L)), L)
        c = np.concatenate([c[L - self.neg:], c[:self.n]])     # positions −neg … n−1 in the reference
        return np.arange(-self.neg, self.n) - at, _gain(np.clip(c / on, 0, 1), self.dens)

    def gains_band(self, piece, at, lag, radius):
        """Like gains(), but only for lags within ±radius of lag (a small FFT: fast)."""
        np = _np()
        on = float(piece.sum())
        if on <= 0:
            return None
        lo = at + lag - radius
        hi = at + lag + radius + len(piece)
        band = np.zeros(hi - lo, np.float32)
        a, b = max(0, lo), min(self.n, hi)
        if b > a:
            band[a - lo:b - lo] = self.ref[a:b]
        L = _fft_len(len(band) + len(piece))
        c = np.fft.irfft(np.fft.rfft(band, L) * np.conj(np.fft.rfft(piece, L)), L)[:len(band) - len(piece) + 1]
        return np.arange(len(c)) + lo - at, _gain(np.clip(c / on, 0, 1), self.dens)


def match(ref_times, sub_times, detect_cuts=True, ratios=None, progress=None, cancel=None,
          reference="subtitle", frame_ms=None) -> MatchResult:
    """Find the time map that puts sub_times onto ref_times. Both are (k, 2) arrays in ms (times_array).
    progress(fraction, text) and cancel() → bool are optional callbacks (worker thread).
    reference="audio": ref_times are speech found in the video's audio (S4): no line pairs, and the confidence
    comes from how clearly the best offset stands out (speech detection is noisy, so the overlap stays low)."""
    import time as _time
    np = _np()
    t_start = _time.time()
    res = MatchResult()
    res.reference = reference
    ratios = ratios or MATCH_RATIOS

    def step(frac, text):
        if cancel and cancel():
            raise Cancelled()
        if progress:
            progress(frac, text)

    if len(ref_times) < MIN_LINES or len(sub_times) < MIN_LINES:
        res.notes.append("too few lines to compare")
        res.elapsed = _time.time() - t_start
        return res
    step(0.0, "Comparing the timing…")
    res.duration_ms = int(sub_times[:, 1].max())
    k_c = COARSE_MS // STEP_MS
    maxlag_c = MAX_OFFSET_MS // COARSE_MS
    end_ms = max(ref_times[:, 1].max(), sub_times[:, 1].max() * max(ratios)) + MAX_OFFSET_MS
    n = int(end_ms / STEP_MS) + 10                       # fine grid
    nc = n // k_c + 1                                    # coarse grid
    ref = on_signal(ref_times, n)
    cs = np.concatenate([[0.0], np.cumsum(ref, dtype=np.float64)])
    span = max(1.0, (ref_times[:, 1].max() - ref_times[:, 0].min()) / STEP_MS)
    dens = float(ref.sum() / span)
    ref_c = on_signal(ref_times, nc, COARSE_MS)
    search = _Search(ref_c, dens)

    # 1. global: the best (ratio, offset); a ratio other than 1 must win by a little
    s0 = on_signal(sub_times, n)
    res.overlap_before = float((ref * s0).sum() / max(1.0, s0.sum()))
    res.gain_before = float(_gain(res.overlap_before, dens))
    best = None
    for k, r in enumerate(ratios):
        step(0.05 + 0.35 * k / len(ratios), "Comparing speeds…")
        lags, g = search.gains(on_signal(sub_times * r, nc, COARSE_MS), 0)
        ok = np.abs(lags) <= maxlag_c
        j = int(np.argmax(np.where(ok, g, -9)))
        if best is None or g[j] > best[2] + (0.01 if r != 1.0 else -0.01):
            best = (r, int(lags[j]), float(g[j]))
    ratio, glag_c = best[0], best[1]
    # Speech detection hears music and misses whispers: against audio even the right offset scores far lower
    # than two subtitles do, so the thresholds for cuts follow the quality of the global match (subtitles: 1).
    sc = 1.0     # tried: thresholds scaled to the audio match quality gave false cuts (stress part 3); kept at 1
    res.ratio = ratio
    scaled = sub_times * ratio
    parts = [{"lag_c": glag_c, "from_s": 0.0, "windows": 0}]

    # 2. cut detection
    if detect_cuts:
        parts = _find_parts(search, scaled, nc, glag_c, cs, n, step, sc) or parts

    # 3. each part's offset to 10 ms on its own lines
    bounds = [p["from_s"] for p in parts] + [float("inf")]
    segs = []
    for k, p in enumerate(parts):
        sel = (scaled[:, 0] >= bounds[k]) & (scaled[:, 0] < bounds[k + 1])
        lag = p["lag_c"] * k_c
        if sel.sum() >= 1:
            lag = _refine_lag(cs, scaled[sel], lag, n, radius=k_c * 20)        # ±1 s around the coarse result
        segs.append({"from_ms": int(bounds[k] / ratio), "to_ms": None, "offset_ms": int(lag * STEP_MS),
                     "windows": p["windows"]})
    for k, g in enumerate(segs):
        g["to_ms"] = segs[k + 1]["from_ms"] if k + 1 < len(segs) else res.duration_ms
    if detect_cuts:
        segs = _edge_parts(search, cs, scaled, segs, ratio, n, res.duration_ms, sc)
        segs = _refine_sections(cs, scaled, segs, ratio, n)
    segs = _merge_equal(segs)
    step(0.95, "Checking the result…")

    # 4. the map, the result and the status
    res.segments = segs
    res.tmap = map_piecewise([(g["from_ms"], ratio, g["offset_ms"]) for g in segs], kind="auto")
    new = _apply_times(res.tmap, sub_times)
    len_tol = max(SAME_LEN_MS, (frame_ms or 0) * 1.25)          # MicroDVD: lengths are rounded to frames
    pairs = _line_pairs(ref_times, new, len_tol) if reference == "subtitle" else np.full(len(new), -1)
    paired = pairs >= 0
    res.shared_timing = bool(paired.mean() >= LINE_SHARE) if len(pairs) else False
    if res.shared_timing:
        delta = np.where(paired, ref_times[np.clip(pairs, 0, None), 0] - new[:, 0], 0.0)
        off = np.abs(delta[paired]) > max(LINE_OFF_MS, len_tol)
        if off.mean() >= LINE_UNEVEN_SHARE:
            res.tmap = _line_map(res.tmap, sub_times, delta, paired, ratio)
            res.lines_aligned = int((np.abs(delta) > max(LINE_OFF_MS, len_tol)).sum())
            new = _apply_times(res.tmap, sub_times)
    s1 = on_signal(new, n)
    res.overlap_after = float((ref * s1).sum() / max(1.0, s1.sum()))
    res.confidence = float(max(0.0, min(1.0, _gain(res.overlap_after, dens))))
    res.unmatched = [int(i) for i in np.where(_block_overlaps(cs, new, 0, n) <= 0)[0]]
    if reference == "audio":
        res.peak_margin = _peak_margin(search, scaled, nc, res.segments, ratio)
        res.confidence = audio_confidence(res.peak_margin, res.overlap_after, dens)
        res.ref_gaps = _ref_gaps(ref_times, new, min_density=AUDIO_GAP_DENSITY)
        res.median_line_ms = None
    else:
        res.ref_gaps = _ref_gaps(ref_times, new)
        res.median_line_ms = _median_line_diff(ref_times, new)
    res.status = _status(res)
    res.tmap.label = _map_label(res)
    res.elapsed = _time.time() - t_start
    step(1.0, "Done")
    return res


def _refine_sections(cs, scaled, segs, ratio, n):
    """Uneven timing (T12): inside each part, 2-minute sections may sit up to ±2 s off. A section gets its own
    offset only when that clearly improves the overlap and the next section agrees; the change goes in the gap
    between two lines. Returns the parts, split where needed."""
    np = _np()
    out = []
    win, rad = SEC_WIN_MS, SEC_RANGE_MS // STEP_MS
    for g in segs:
        lag = g["offset_ms"] // STEP_MS
        a_s, b_s = g["from_ms"] * ratio, (g["to_ms"] + 1) * ratio
        sel = np.where((scaled[:, 0] >= a_s) & (scaled[:, 0] < b_s))[0]
        if len(sel) < 8:
            out.append(g)
            continue
        t0 = scaled[sel[0], 0]
        secs = []
        while t0 < b_s:
            idx = sel[(scaled[sel, 0] >= t0) & (scaled[sel, 0] < t0 + win)]
            if len(idx) >= 4:
                d, v = _overlap_curve(cs, scaled[idx], lag, n, rad)
                base = v[rad]
                c = _plateau_centre(d, v)
                better = v[rad + c] >= base * (1 + SEC_GAIN) + 1e-9 if base > 0 else v.max() > 0
                secs.append([t0, idx, c if (better and abs(c) * STEP_MS >= SEC_MIN_MS) else 0])
            else:
                secs.append([t0, idx, None])          # too few lines: follows its neighbours
            t0 += SEC_HOP_MS
        # keep a moved section only when the next (or previous) one agrees
        vals = [x[2] for x in secs]
        keep = [0] * len(vals)
        for i, c in enumerate(vals):
            if not c:
                continue
            nb = [vals[j] for j in (i - 1, i + 1) if 0 <= j < len(vals) and vals[j]]
            if any(abs(c - o) * STEP_MS <= SEC_AGREE_MS for o in nb):
                keep[i] = c
        for i, c in enumerate(vals):       # sections without lines take their neighbours' value
            if c is None:
                keep[i] = keep[i - 1] if i > 0 else 0
        if not any(keep):
            out.append(g)
            continue
        cur = None
        for i, (t0, idx, _) in enumerate(secs):
            off = (lag + keep[i]) * STEP_MS
            if cur is None:
                cur = dict(g, offset_ms=int(off))
                continue
            if abs(off - cur["offset_ms"]) < SEC_AGREE_MS / 2:
                continue
            cut = _best_change_point(cs, scaled, cur["offset_ms"] // STEP_MS, int(off) // STEP_MS,
                                     t0 - SEC_HOP_MS / 2, t0 + SEC_HOP_MS / 2, n)
            cut_ms = max(int(cut / ratio), cur["from_ms"] + 1)
            cur["to_ms"] = cut_ms
            out.append(cur)
            cur = dict(g, from_ms=cut_ms, offset_ms=int(off), windows=0)
        out.append(cur)
    for k, g in enumerate(out):
        g["to_ms"] = out[k + 1]["from_ms"] if k + 1 < len(out) else g["to_ms"]
    if len(out) > len(segs):                 # each new section's offset again, on all its own lines
        for g in out:
            sel = (scaled[:, 0] >= g["from_ms"] * ratio) & (scaled[:, 0] < g["to_ms"] * ratio)
            if sel.sum() >= 4:
                g["offset_ms"] = int(_refine_lag(cs, scaled[sel], g["offset_ms"] // STEP_MS, n, 50) * STEP_MS)
    return out


def _line_pairs(ref_times, new_times, len_tol=SAME_LEN_MS):
    """For each subtitle line: the reference line of the same length (±20 ms) starting within ±2 s (the nearest
    one), or -1. Many pairs mean the reference shares this subtitle's line timing."""
    np = _np()
    order = np.argsort(ref_times[:, 0])
    rs = ref_times[order, 0]
    rd = (ref_times[order, 1] - ref_times[order, 0])
    out = np.full(len(new_times), -1, np.int64)
    lo = np.searchsorted(rs, new_times[:, 0] - LINE_SEARCH_MS)
    hi = np.searchsorted(rs, new_times[:, 0] + LINE_SEARCH_MS)
    for i in range(len(new_times)):
        if hi[i] <= lo[i]:
            continue
        d = new_times[i, 1] - new_times[i, 0]
        k = np.arange(lo[i], hi[i])
        ok = k[np.abs(rd[k] - d) <= len_tol]
        if len(ok):
            out[i] = order[ok[np.argmin(np.abs(rs[ok] - new_times[i, 0]))]]
    return out


def _line_map(tmap, sub_times, delta, paired, ratio):
    """The part map plus one step per line: each line lands on its counterpart; a line without one moves like the
    line before it."""
    np = _np()
    order = np.argsort(sub_times[:, 0])
    segs, last = [], 0.0
    for i in order:
        if paired[i]:
            last = float(delta[i])
        t = float(sub_times[i, 0])
        _, r, o = tmap.segment_for(t)
        segs.append((int(t) - 1 if segs else 0, r, o + last))
    # one segment per start time (two lines may start at the same moment)
    uniq = {}
    for a, r, o in segs:
        uniq[a] = (a, r, o)
    return map_piecewise(sorted(uniq.values()), kind="auto")


def _edge_parts(search, cs, scaled, segs, ratio, n, duration_ms, sc=1.0):
    """The first and the last 4 minutes on their own: a different intro (or ending) of another version is too
    short for the windows. A head or tail part is added only when its lines clearly match elsewhere."""
    np = _np()
    out = [dict(g) for g in segs]
    k_c = COARSE_MS // STEP_MS
    for where in ("head", "tail"):
        if where == "head":
            g = out[0]
            first = scaled[:, 0].min()
            sel = scaled[:, 0] < first + EDGE_MS
        else:
            g = out[-1]
            last = scaled[:, 0].max()
            sel = scaled[:, 0] > last - EDGE_MS
        lines = scaled[sel]
        if len(lines) < 4 or len(lines) > 0.25 * len(scaled):
            continue
        lag = g["offset_ms"] // STEP_MS
        a = int(lines[0, 0] / COARSE_MS)
        piece = on_signal(lines - a * COARSE_MS, int(lines[:, 1].max() / COARSE_MS) - a + 2, COARSE_MS)
        got = search.gains_band(piece, a, lag // k_c, PROOF_RANGE_MS // COARSE_MS)
        if got is None:
            continue
        lags, gains = got
        j = int(np.argmax(gains))
        best = int(lags[j]) * k_c
        if abs(best - lag) * STEP_MS < NEAR_LAG_MS:
            continue
        here = float(gains[j])
        at_part = float(gains[np.argmin(np.abs(lags * k_c - lag))])
        far = np.abs(lags - lags[j]) > 2 * (1000 // COARSE_MS)
        if here - at_part < (EDGE_GAIN * sc) or not far.any() or here - float(gains[far].max()) < (EDGE_MARGIN * sc):
            continue
        best = _refine_lag(cs, lines, best, n, radius=k_c * 20)
        if where == "head":
            cut = _best_change_point(cs, scaled, best, lag, first, first + EDGE_MS, n)
            cut_ms = int(cut / ratio)
            if cut_ms <= g["from_ms"] + 1 or cut_ms >= g["to_ms"]:
                continue
            out.insert(0, dict(g, to_ms=cut_ms, offset_ms=int(best * STEP_MS), windows=0))
            out[1]["from_ms"] = cut_ms
        else:
            cut = _best_change_point(cs, scaled, lag, best, last - EDGE_MS, last, n)
            cut_ms = int(cut / ratio)
            if cut_ms <= g["from_ms"] + 1 or cut_ms >= g["to_ms"]:
                continue
            out[-1]["to_ms"] = cut_ms
            out.append(dict(g, from_ms=cut_ms, to_ms=duration_ms, offset_ms=int(best * STEP_MS), windows=0))
    return out


def _apply_times(tmap, times):
    np = _np()
    return np.array([(tmap(a), tmap(b)) for a, b in times], dtype=float).reshape(-1, 2)


def _merge_equal(segs):
    out = []
    for g in segs:
        if out and abs(out[-1]["offset_ms"] - g["offset_ms"]) < SAME_LAG_MS / 5:      # within 0.1 s: one part
            out[-1]["to_ms"] = g["to_ms"]
            out[-1]["windows"] += g["windows"]
        else:
            out.append(dict(g))
    return out


def _viterbi(E, centers):
    """One offset per window; staying costs nothing, a change costs SWITCH_PENALTY (a little more for a big
    jump). Windows without text have zero emission everywhere and simply carry the path."""
    np = _np()
    W, K = E.shape
    cen = np.array(centers, dtype=float) * COARSE_MS
    jump_cost = SWITCH_PENALTY + 0.1 * np.minimum(1.0, np.abs(cen[:, None] - cen[None, :]) / 300_000)
    np.fill_diagonal(jump_cost, 0.0)
    score = E[0].copy()
    back = np.zeros((W, K), np.int64)
    for i in range(1, W):
        cand = score[:, None] - jump_cost          # from j (rows) to k (columns)
        back[i] = np.argmax(cand, axis=0)
        score = cand[back[i], np.arange(K)] + E[i]
    path = [int(np.argmax(score))]
    for i in range(W - 1, 0, -1):
        path.append(int(back[i, path[-1]]))
    return path[::-1]


def _runs(path):
    runs, a = [], 0
    for i in range(1, len(path) + 1):
        if i == len(path) or path[i] != path[a]:
            runs.append([path[a], a, i - 1])
            a = i
    return runs


def _find_parts(search, scaled, nc, glag_c, cs, n, step, sc=1.0):
    """[{lag_c, from_s, windows}] (from_s: scaled subtitle time where the part starts), or None if the whole
    subtitle has one offset."""
    np = _np()
    w, h = WIN_MS // COARSE_MS, HOP_MS // COARSE_MS
    sub = on_signal(scaled, nc, COARSE_MS)
    end = int(scaled[:, 1].max() / COARSE_MS) + 1
    starts = list(range(0, max(1, end - w // 2), h))
    pool = 1000 // COARSE_MS                        # emissions on a 1 s grid (max inside each second)
    rows, peaks = [], []
    for k, a in enumerate(starts):
        step(0.4 + 0.45 * k / len(starts), "Looking for cuts…")
        piece = sub[a:a + w]
        if piece.sum() < MIN_DIALOGUE * len(piece):
            rows.append(None)
            continue
        lags, g = search.gains(piece, a)
        m = len(g) // pool * pool
        pooled = g[:m].reshape(-1, pool).max(axis=1)        # bin b: positions (b·pool − neg) …
        rows.append((a, pooled))
        v = g.copy()
        for _ in range(3):                           # the 3 best peaks of this window
            j = int(np.argmax(v))
            peaks.append(int(lags[j]))
            v[max(0, j - 2 * pool):j + 2 * pool] = -9
    if sum(r is not None for r in rows) < 3:
        return None
    tol = SAME_LAG_MS // COARSE_MS
    allp = sorted(peaks + [glag_c])
    clusters = []
    for c in allp:
        if clusters and c - clusters[-1][-1] <= tol:
            clusters[-1].append(c)
        else:
            clusters.append([c])
    centers = [int(np.median(c)) for c in clusters]
    gi = int(np.argmin([abs(c - glag_c) for c in centers]))
    centers[gi] = glag_c
    E = np.zeros((len(rows), len(centers)))
    for i, r in enumerate(rows):
        if r is None:
            continue
        a, pooled = r
        for j, c in enumerate(centers):
            b = (c + a + search.neg) // pool
            E[i, j] = pooled[max(0, b - 1):b + 2].max() if 0 <= b < len(pooled) else -1.0
    # proof first: every stretch of windows where an offset is (nearly) the best is tested once; then one
    # path, in which an offset other than the global one may only be used inside a proven stretch
    allowed = np.zeros_like(E, dtype=bool)
    has_text = np.array([r is not None for r in rows])
    top = E.max(axis=1)
    good = (E >= top[:, None] - (NEAR_BEST * sc)) & (E >= (MIN_PART_GAIN * sc)) & has_text[:, None]
    for j in range(len(centers)):
        col = good[:, j]
        i = 0
        while i < len(col):
            if not col[i]:
                i += 1
                continue
            k = i
            while k + 1 < len(col) and (col[k + 1] or not has_text[k + 1]):
                k += 1
            sel = (scaled[:, 0] >= starts[i] * COARSE_MS) & (scaled[:, 0] < (starts[k] + w) * COARSE_MS)
            nb = [c for c in range(len(centers)) if c != j and abs(centers[c] - centers[j]) * COARSE_MS < NEAR_LAG_MS
                  and good[i:k + 1, c].any()] + ([gi] if j != gi else [])
            text_rows = np.where(has_text)[0]
            edge = bool(len(text_rows)) and (i <= text_rows[0] or k >= text_rows[-1])
            rows_t = [r for r in range(i, k + 1) if has_text[r]]
            beats_global = j == gi or (bool(rows_t) and float(np.mean([E[r, j] - E[r, gi] for r in rows_t]))
                                       >= (CUT_GAIN * sc))
            if j == gi or (beats_global and _part_proves_itself(search, scaled[sel], nc, centers, j, nb,
                                                                int(has_text[i:k + 1].sum()), edge, sc)):
                allowed[i:k + 1, j] = True
            i = k + 1
    E2 = np.where(allowed, E, -1.0)
    E2[~allowed.any(axis=1)] = 0.0          # nothing proven here: the window carries its neighbours' offset
    k_c = COARSE_MS // STEP_MS
    for _ in range(12):
        runs = _runs(_viterbi(E2, centers))
        if len(runs) == 1:
            return None
        # change points: the gap between two lines that fits both neighbours best (fine grid)
        parts = [{"lag_c": centers[runs[0][0]], "from_s": 0.0, "windows": runs[0][2] - runs[0][1] + 1,
                  "run": runs[0]}]
        for k in range(1, len(runs)):
            ja, a0, b0 = runs[k - 1]
            jb, a1, b1 = runs[k]
            lo_ms = starts[b0] * COARSE_MS
            hi_ms = (starts[a1] + w) * COARSE_MS
            cut = _best_change_point(cs, scaled, centers[ja] * k_c, centers[jb] * k_c, lo_ms, hi_ms, n)
            cut = max(cut, parts[-1]["from_s"] + 1)
            parts.append({"lag_c": centers[jb], "from_s": float(cut), "windows": b1 - a1 + 1, "run": runs[k]})
        clash = _overlapping_part(parts, scaled, cs, n)
        if clash is None:
            break
        j, a, b = clash["run"]                  # each moment of the video shows one part: drop the smaller one
        E2[a:b + 1, j] = -1.0
        if not (E2[a:b + 1] > -1.0).any(axis=1).all():
            E2[a:b + 1][~(E2[a:b + 1] > -1.0).any(axis=1)] = 0.0
    else:
        return None
    for g in parts:
        g.pop("run", None)
    return parts


def _overlapping_part(parts, scaled, cs, n):
    """The smaller of two parts when most of its lines land inside the stretch of the reference that another part
    covers, or None. In a real edit every moment of the film shows one part of the subtitle at most; a few lines
    of a scene the reference does not have may land anywhere, so only the share of lines counts."""
    np = _np()
    bounds = [g["from_s"] for g in parts] + [float("inf")]
    k_c = COARSE_MS // STEP_MS
    placed = []                                  # per part: mapped start of its lines that land on reference text
    for k, g in enumerate(parts):
        lines = scaled[(scaled[:, 0] >= bounds[k]) & (scaled[:, 0] < bounds[k + 1])]
        if len(lines):
            ov = _block_overlaps(cs, lines, g["lag_c"] * k_c, n)
            lines = lines[ov >= 0.5 * np.maximum(1.0, (lines[:, 1] - lines[:, 0]) / STEP_MS)]
        placed.append(lines[:, 0] + g["lag_c"] * COARSE_MS if len(lines) >= 3 else None)
    worst = None
    for i in range(len(parts)):
        for j in range(len(parts)):
            if i == j or placed[i] is None or placed[j] is None:
                continue
            lo, hi = np.percentile(placed[j], [2, 98])
            if hi - lo < PART_OVERLAP_MS:
                continue
            inside = float(((placed[i] > lo + PART_OVERLAP_MS / 2) & (placed[i] < hi - PART_OVERLAP_MS / 2)).mean())
            if inside >= 0.5 and parts[i]["windows"] <= parts[j]["windows"]:
                if worst is None or parts[i]["windows"] < worst["windows"]:
                    worst = parts[i]
    return worst


def _part_proves_itself(search, lines, nc, centers, j, neighbours, n_windows, edge=False, sc=1.0):
    """A part with another offset is real only when its own lines say so clearly."""
    np = _np()
    if len(lines) < 3:
        return False
    a = int(lines[0, 0] / COARSE_MS)
    piece = on_signal(lines - a * COARSE_MS, int(lines[:, 1].max() / COARSE_MS) - a + 2, COARSE_MS)
    lag = centers[j]
    got = search.gains_band(piece, a, lag, PROOF_RANGE_MS // COARSE_MS)
    if got is None:
        return False
    lags, g = got
    tol = 1000 // COARSE_MS
    here = float(g[np.abs(lags - lag) <= tol].max())
    near = [c for c in (centers[m] for m in neighbours) if abs(c - lag) * COARSE_MS < NEAR_LAG_MS]
    if near:                                        # a small step: uneven timing, needs to beat the neighbour
        there = max(float(g[np.abs(lags - c) <= 2].max()) if (np.abs(lags - c) <= 2).any() else 0.0 for c in near)
        return n_windows >= 3 and here - there >= (NEAR_GAIN * sc)
    far = (np.abs(lags - lag) > 2 * tol) & (np.abs(lags - lag) <= PROOF_RANGE_MS // COARSE_MS)
    need = (CUT_MARGIN * sc) if n_windows >= 3 else (SHORT_CUT_MARGIN * sc) if n_windows == 2 else (EDGE_MARGIN * sc)
    if n_windows < 2 and not edge:
        return False
    return bool(far.any()) and here - float(g[far].max()) >= need


def _best_change_point(cs, times, lag_a, lag_b, lo_ms, hi_ms, n):
    """Scaled time where part B starts: the lines before it use lag_a, from it lag_b (fine lags)."""
    np = _np()
    inside = np.where((times[:, 0] >= lo_ms) & (times[:, 0] <= hi_ms))[0]
    if len(inside) == 0:
        return int((lo_ms + hi_ms) / 2)
    oa = _block_overlaps(cs, times[inside], lag_a, n)
    ob = _block_overlaps(cs, times[inside], lag_b, n)
    pre = np.concatenate([[0.0], np.cumsum(oa)])
    post = np.concatenate([np.cumsum(ob[::-1])[::-1], [0.0]])
    k = int(np.argmax(pre + post))
    if k >= len(inside):
        return int(times[inside[-1], 1]) + 1
    i = inside[k]
    prev_end = times[i - 1, 1] if i > 0 else times[i, 0] - 1
    return int((min(prev_end, times[i, 0] - 1) + times[i, 0]) / 2)


def _peak_margin(search, scaled, nc, segments, ratio):
    """Audio: the gain of each part's lines at its offset minus the best gain more than 2 s away (±10 min),
    weighted by the part's lines."""
    np = _np()
    total, acc = 0, 0.0
    for g in sorted(segments, key=lambda g: -(g["to_ms"] - g["from_ms"]))[:1]:      # the main (longest) part
        sel = (scaled[:, 0] >= g["from_ms"] * ratio) & (scaled[:, 0] < g["to_ms"] * ratio + 1)
        lines = scaled[sel]
        if len(lines) < 3:
            continue
        a = int(lines[0, 0] / COARSE_MS)
        piece = on_signal(lines - a * COARSE_MS, int(lines[:, 1].max() / COARSE_MS) - a + 2, COARSE_MS)
        lag = int(round(g["offset_ms"] / COARSE_MS))
        got = search.gains_band(piece, a, lag, PROOF_RANGE_MS // COARSE_MS)
        if got is None:
            continue
        lags, gains = got
        here = float(gains[np.abs(lags - lag) <= 2].max())
        far = np.abs(lags - lag) > 2000 // COARSE_MS
        if not far.any():
            continue
        acc += (here - float(gains[far].max())) * len(lines)
        total += len(lines)
    return acc / total if total else 0.0


def audio_confidence(margin, overlap_after, density):
    """Speech detection hears music and noise too, so the overlap with speech stays well below that of two
    subtitles. What tells a real match is a clear peak: margin AUDIO_MARGIN_LOW → 0, AUDIO_MARGIN_HIGH → 1."""
    m = (margin - AUDIO_MARGIN_LOW) / (AUDIO_MARGIN_HIGH - AUDIO_MARGIN_LOW)
    return float(max(0.0, min(1.0, m)))


def _ref_gaps(ref_times, new_times, min_ms=NO_SUBTITLE_MS, min_density=0.0):
    """Stretches where the reference has text but the synced subtitle has no line for ≥ min_ms."""
    np = _np()
    if not len(new_times):
        return []
    edges, cover_end = [], None
    for i in np.argsort(new_times[:, 0]):
        s, e = new_times[i]
        if cover_end is not None and s - cover_end >= min_ms:
            edges.append((cover_end, s))
        cover_end = e if cover_end is None else max(cover_end, e)
    first = float(new_times[:, 0].min())
    edges = ([(-1.0, first)] if first >= min_ms else []) + edges + [(cover_end, float(ref_times[:, 1].max()) + 1)]
    gaps = []
    for a, b in edges:
        inside = ref_times[(ref_times[:, 0] >= a) & (ref_times[:, 1] <= b)]
        if len(inside) >= 3 and inside[-1, 1] - inside[0, 0] >= min_ms / 2:
            span = inside[-1, 1] - inside[0, 0]
            if (inside[:, 1] - inside[:, 0]).sum() / span >= min_density:     # audio: mostly speech, not music
                gaps.append((int(inside[0, 0]), int(inside[-1, 1])))
    return gaps


def _median_line_diff(ref_times, new_times, within=1000):
    np = _np()
    rs = np.sort(ref_times[:, 0])
    k = np.searchsorted(rs, new_times[:, 0])
    left = np.abs(new_times[:, 0] - rs[np.clip(k - 1, 0, len(rs) - 1)])
    right = np.abs(rs[np.clip(k, 0, len(rs) - 1)] - new_times[:, 0])
    d = np.minimum(left, right)
    d = d[d <= within]
    return float(np.median(d)) if len(d) else None


def _status(res: MatchResult) -> str:
    if res.confidence < CANNOT_TELL or not res.segments:
        return "cannot_tell"
    drift = abs(res.ratio - 1) > 1e-6
    off = abs(res.offset_ms)
    if len(res.segments) > 1:
        offs = [g["offset_ms"] for g in res.segments]
        steps = [abs(b - a) for a, b in zip(offs, offs[1:])]
        if max(steps) >= NEAR_LAG_MS:
            return "cut"
        if not drift:
            return "uneven"
        off = max(abs(o) for o in offs)        # a speed change with small section differences: the speed leads
    if drift:
        return "offset_drift" if off >= IN_SYNC_MS else "drift"
    if off >= IN_SYNC_MS:
        return "offset"
    if res.lines_aligned:
        return "uneven"
    if not res.shared_timing and res.median_line_ms is not None and res.median_line_ms >= UNEVEN_MEDIAN_MS:
        return "uneven"
    return "in_sync"


def _map_label(res: MatchResult) -> str:
    if res.lines_aligned:
        return f"{res.lines_aligned} lines aligned line by line" + (
            "" if len(res.segments) == 1 else f", {len(res.segments)} parts")
    if len(res.segments) > 1:
        return f"{len(res.segments)} parts" + ("" if abs(res.ratio - 1) < 1e-6 else f", {describe_ratio(res.ratio)}")
    if abs(res.ratio - 1) > 1e-6:
        return f"{describe_ratio(res.ratio)}, {fmt_offset(res.offset_ms)}"
    return f"Shift {fmt_offset(res.offset_ms)}"


def match_speech(speech_times, sub_blocks, detect_cuts=True, progress=None, cancel=None) -> MatchResult:
    """S4: match the dialogue lines of a subtitle against speech found in the video's audio."""
    sidx = dialogue_indexes(sub_blocks)
    res = match(speech_times, times_array(sub_blocks, sidx), detect_cuts=detect_cuts, progress=progress,
                cancel=cancel, reference="audio")
    res.unmatched = [sidx[i] for i in res.unmatched if i < len(sidx)]
    return res


def match_blocks(ref_blocks, sub_blocks, detect_cuts=True, progress=None, cancel=None, frame_ms=None) -> MatchResult:
    """match() on the dialogue lines of two block lists. res.unmatched indexes the sub_blocks list.
    frame_ms: one frame, when either subtitle is frame-based (MicroDVD), so line lengths are only that exact."""
    sidx = dialogue_indexes(sub_blocks)
    res = match(times_array(ref_blocks), times_array(sub_blocks, sidx), detect_cuts=detect_cuts,
                progress=progress, cancel=cancel, frame_ms=frame_ms)
    res.unmatched = [sidx[i] for i in res.unmatched if i < len(sidx)]
    return res
