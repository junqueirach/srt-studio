"""
SRT Studio — FFmpeg on demand and video helpers (v0.10.0 · S3, used by S4 and S5).

No Tk here: everything is unit-tested in tests/test_media.py with fake files, a fake server and fake processes.

FFmpeg is not bundled. It is looked for in this order: the path set in Settings → `~/.srt_studio/tools/ffmpeg/`
(where the app downloads it) → the PATH. The download is an LGPL build (BtbN FFmpeg-Builds, a month-end release:
those are kept for about two years) with a pinned URL, size and SHA-256; only ffmpeg.exe, ffprobe.exe, their DLLs
and the licence are kept. Every FFmpeg process runs without a console window, at below-normal priority, with a
timeout, and Cancel kills it.
"""

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import zipfile
from pathlib import Path

FFMPEG_BUILD = "n8.1.3 LGPL (BtbN FFmpeg-Builds, autobuild-2026-09-30)"
FFMPEG_URL = ("https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-2026-09-30-13-08/"
              "ffmpeg-n8.1.3-9-g29e619e767-win64-lgpl-shared-8.1.zip")
FFMPEG_SIZE = 80_733_362
FFMPEG_SHA256 = "3e47bda1607740550141e37c0e49d1e5182b34699f15adfd137ee266d346811a"
FFMPEG_LICENCE = "LGPL v2.1 or later"
TOOLS_DIR = Path.home() / ".srt_studio" / "tools" / "ffmpeg"
EXE = ".exe" if os.name == "nt" else ""
CHUNK = 1 << 16


class Cancelled(Exception):
    """The user pressed Cancel."""


class MediaError(Exception):
    """A clear message for the user."""


# ── where is FFmpeg ──────────────────────────────────────────────────

def _pair_in(folder: Path):
    f, p = folder / f"ffmpeg{EXE}", folder / f"ffprobe{EXE}"
    return (str(f), str(p)) if f.is_file() and p.is_file() else None


def find_ffmpeg(setting: str = "", tools_dir: Path = None, path_env: str = None) -> dict:
    """{"ffmpeg", "ffprobe", "source": "settings" | "downloaded" | "path"} or None.
    setting may be ffmpeg.exe itself or its folder; ffprobe must sit next to it."""
    if setting:
        s = Path(setting.strip().strip('"'))
        pair = _pair_in(s) if s.is_dir() else _pair_in(s.parent) if s.name.lower().startswith("ffmpeg") else None
        if pair:
            return {"ffmpeg": pair[0], "ffprobe": pair[1], "source": "settings"}
    tools_dir = TOOLS_DIR if tools_dir is None else Path(tools_dir)
    for folder in (tools_dir, tools_dir / "bin"):
        pair = _pair_in(folder)
        if pair:
            return {"ffmpeg": pair[0], "ffprobe": pair[1], "source": "downloaded"}
    env = os.environ.get("PATH", "") if path_env is None else path_env
    for d in env.split(os.pathsep):
        if d.strip():
            pair = _pair_in(Path(d.strip().strip('"')))
            if pair:
                return {"ffmpeg": pair[0], "ffprobe": pair[1], "source": "path"}
    return None


# ── running FFmpeg ───────────────────────────────────────────────────

def _creation_flags() -> int:
    if os.name != "nt":
        return 0
    return getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS",
                                                                          0x00004000)


def popen(cmd, **kw):
    """Popen with no console window and below-normal priority (Windows)."""
    return subprocess.Popen(cmd, creationflags=_creation_flags(), stdin=subprocess.DEVNULL, **kw)


def run(cmd, timeout: float = 60, cancel=None, popen_fn=None) -> tuple:
    """Run to the end: (returncode, stdout bytes, stderr text). Cancel or the timeout kill the process
    (checked every 0.1 s) and raise Cancelled / MediaError."""
    popen_fn = popen_fn or popen
    proc = popen_fn(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = [], []
    readers = [threading.Thread(target=lambda: out.append(proc.stdout.read()), daemon=True),
               threading.Thread(target=lambda: err.append(proc.stderr.read()), daemon=True)]
    for t in readers:
        t.start()
    end = time.time() + timeout
    while proc.poll() is None:
        if cancel and cancel():
            kill(proc)
            raise Cancelled()
        if time.time() > end:
            kill(proc)
            raise MediaError(f"{Path(cmd[0]).name} did not finish within {timeout:.0f} s")
        time.sleep(0.1)
    for t in readers:
        t.join(2)
    return proc.returncode, (out[0] if out else b""), (err[0] if err else b"").decode("utf-8", "replace")


def kill(proc):
    try:
        proc.kill()
        proc.wait(5)
    except Exception:
        pass


def ffmpeg_version(ff: dict, popen_fn=None) -> str:
    """'ffmpeg version n8.1.3 …' (first line), or raise MediaError when it does not run."""
    try:
        rc, out, err = run([ff["ffmpeg"], "-hide_banner", "-version"], timeout=20, popen_fn=popen_fn)
    except OSError as e:
        raise MediaError(f"FFmpeg does not start: {e}") from e
    line = (out.decode("utf-8", "replace") or err).strip().splitlines()[:1]
    if rc != 0 or not line or "version" not in line[0]:
        raise MediaError(f"FFmpeg does not run properly (exit code {rc})")
    return line[0]


# ── the download ─────────────────────────────────────────────────────

KEEP_SUFFIXES = (".exe", ".dll")
KEEP_EXES = {f"ffmpeg{EXE}", f"ffprobe{EXE}"}


def download_ffmpeg(dest: Path = None, url: str = FFMPEG_URL, sha256: str = FFMPEG_SHA256, size: int = FFMPEG_SIZE,
                    progress=None, cancel=None, opener=None, verify=None) -> dict:
    """Download, check the SHA-256, keep ffmpeg/ffprobe/DLLs/licence in dest, check that it runs.
    progress(done_bytes, total_bytes); cancel() → bool. Nothing is left behind on a failure or Cancel.
    opener(url) → a file-like response (tests pass a fake). verify(ff) checks the result (default: ffmpeg -version)."""
    import urllib.request
    dest = TOOLS_DIR if dest is None else Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    opener = opener or (lambda u: urllib.request.urlopen(urllib.request.Request(
        u, headers={"User-Agent": "SRT-Studio"}), timeout=60))
    fd, part = tempfile.mkstemp(prefix="ffmpeg-", suffix=".zip.part", dir=str(dest.parent))
    os.close(fd)
    part = Path(part)
    staging = None
    try:
        h = hashlib.sha256()
        done = 0
        with opener(url) as resp, open(part, "wb") as f:
            total = int(getattr(resp, "headers", {}).get("Content-Length") or size or 0)
            while True:
                if cancel and cancel():
                    raise Cancelled()
                chunk = resp.read(CHUNK)
                if not chunk:
                    break
                f.write(chunk)
                h.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
        if h.hexdigest().lower() != sha256.lower():
            raise MediaError("The downloaded file is not the expected one (SHA-256 does not match). It was "
                             "deleted. Try again later, or choose an ffmpeg.exe you already have.")
        staging = Path(tempfile.mkdtemp(prefix="ffmpeg-new-", dir=str(dest.parent)))
        with zipfile.ZipFile(part) as z:
            names = z.namelist()
            for n in names:
                base = n.rsplit("/", 1)[-1]
                low = base.lower()
                if not base or n.endswith("/"):
                    continue
                if ("/bin/" in n or n.startswith("bin/")) and (low in KEEP_EXES or low.endswith(".dll")):
                    target = staging / base
                elif low in ("license.txt", "license", "copying.lgplv2.1", "copying.lgplv3"):
                    target = staging / base
                else:
                    continue
                if cancel and cancel():
                    raise Cancelled()
                with z.open(n) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out, CHUNK)
        ff = find_ffmpeg(tools_dir=staging, path_env="")
        if not ff:
            raise MediaError("The download does not contain ffmpeg.exe and ffprobe.exe.")
        (verify or ffmpeg_version)(ff)
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        os.replace(staging, dest)
        staging = None
        return find_ffmpeg(tools_dir=dest, path_env="")
    finally:
        try:
            part.unlink()
        except OSError:
            pass
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)


# ── ffprobe ──────────────────────────────────────────────────────────

def probe(ff: dict, path: str, timeout: float = 60, popen_fn=None) -> dict:
    """ffprobe as JSON: {"duration_ms", "streams": [{index, type, codec, language, title, default, forced}]}."""
    cmd = [ff["ffprobe"], "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)]
    rc, out, err = run(cmd, timeout=timeout, popen_fn=popen_fn)
    if rc != 0:
        raise MediaError(f"ffprobe cannot read {Path(path).name}: {err.strip()[-300:]}")
    return parse_probe(out)


def parse_probe(raw) -> dict:
    data = json.loads(raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw)
    fmt = data.get("format") or {}
    dur = fmt.get("duration")
    streams = []
    for s in data.get("streams") or []:
        tags = s.get("tags") or {}
        disp = s.get("disposition") or {}
        streams.append({"index": s.get("index"), "type": s.get("codec_type"), "codec": s.get("codec_name"),
                        "language": (tags.get("language") or "").lower(), "title": tags.get("title") or "",
                        "default": bool(disp.get("default")), "forced": bool(disp.get("forced")),
                        "hearing_impaired": bool(disp.get("hearing_impaired")),
                        "channels": s.get("channels"), "fps": _fps(s.get("avg_frame_rate") or s.get("r_frame_rate"))})
    return {"duration_ms": int(float(dur) * 1000) if dur else None, "streams": streams,
            "format": fmt.get("format_name") or ""}


def _fps(rate):
    try:
        a, b = str(rate).split("/")
        return round(float(a) / float(b), 3) if float(b) else None
    except (ValueError, ZeroDivisionError):
        return None


# ── speech in the audio (v0.10.0 · S4) ──────────────────────────────

SAMPLE_RATE = 16_000
VAD_FRAME_MS = 30
VAD_MODE = 3                    # webrtcvad: 0 (lenient) … 3 (strict); music-heavy films need the strict one
BRIDGE_MS = 300                 # speech pauses shorter than this are bridged …
MIN_SPEECH_MS = 200             # … and bursts shorter than this dropped
CACHE_DIR = Path.home() / ".srt_studio" / "cache" / "speech"


def channel_mode(channels) -> str:
    """'center' for 5.1 / 7.1 (film dialogue is mixed into the centre channel, most of the music is not:
    speech detection is much cleaner there), else 'mix' (mono or stereo downmix)."""
    return "center" if channels in (6, 8) else "mix"


def audio_command(ff: dict, video: str, stream_index=None, channels=None) -> list:
    """FFmpeg reads one audio track and writes 16 kHz mono 16-bit PCM to stdout (the centre channel of 5.1/7.1)."""
    amap = f"0:{stream_index}" if stream_index is not None else "0:a:0"
    mono = ["-af", "pan=mono|c0=FC"] if channel_mode(channels) == "center" else ["-ac", "1"]
    return [ff["ffmpeg"], "-v", "error", "-nostdin", "-i", str(video), "-vn", "-sn", "-dn", "-map", amap,
            *mono, "-ar", str(SAMPLE_RATE), "-f", "s16le", "-"]


def speech_runs(flags, frame_ms=VAD_FRAME_MS, bridge_ms=BRIDGE_MS, min_ms=MIN_SPEECH_MS):
    """Per-frame speech flags → (k, 2) array of (start, end) ms."""
    import numpy as np
    f = np.asarray(flags, dtype=bool)
    if not f.any():
        return np.zeros((0, 2))
    d = np.diff(np.concatenate([[0], f.astype(np.int8), [0]]))
    starts, ends = np.where(d == 1)[0] * frame_ms, np.where(d == -1)[0] * frame_ms
    out = []
    for a, b in zip(starts, ends):
        if out and a - out[-1][1] <= bridge_ms:
            out[-1][1] = b
        else:
            out.append([a, b])
    return np.array([x for x in out if x[1] - x[0] >= min_ms], dtype=float).reshape(-1, 2)


def energy_flags(energy):
    """The fallback when webrtcvad is not installed: frames well above the film's quiet level (weaker on music)."""
    import numpy as np
    e = np.asarray(energy, dtype=float)
    if not len(e):
        return e.astype(bool)
    floor = np.percentile(e, 20)
    return e > max(floor * 3.0, np.percentile(e, 55))


def detect_speech(ff: dict, video: str, stream_index=None, duration_ms=None, progress=None, cancel=None,
                  popen_fn=None, use_vad=True, channels=None) -> dict:
    """Speech in the video's audio: {"times": (k, 2) ms, "detector": "webrtcvad" | "energy", "length_ms", "elapsed"}.
    The audio is streamed, never held whole. progress(fraction) while decoding; cancel() kills FFmpeg at once."""
    import numpy as np
    vad = None
    if use_vad:
        try:
            import webrtcvad
            vad = webrtcvad.Vad(VAD_MODE)
        except ImportError:
            vad = None
    frame_bytes = SAMPLE_RATE * VAD_FRAME_MS // 1000 * 2
    total_bytes = (duration_ms or 0) / 1000 * SAMPLE_RATE * 2
    t0 = time.time()
    proc = (popen_fn or popen)(audio_command(ff, video, stream_index, channels), stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE)
    err = []
    reader = threading.Thread(target=lambda: err.append(proc.stderr.read()), daemon=True)
    reader.start()
    flags, energy, buf, got = [], [], b"", 0
    try:
        while True:
            if cancel and cancel():
                kill(proc)
                raise Cancelled()
            chunk = proc.stdout.read(frame_bytes * 64)         # about 2 s of audio at a time
            if not chunk:
                break
            got += len(chunk)
            buf += chunk
            k = len(buf) // frame_bytes
            if k:
                if vad is not None:
                    flags.extend(vad.is_speech(buf[i * frame_bytes:(i + 1) * frame_bytes], SAMPLE_RATE)
                                 for i in range(k))
                a = np.frombuffer(buf[:k * frame_bytes], np.int16).astype(np.float32).reshape(k, -1)
                energy.extend(np.sqrt((a * a).mean(axis=1)).tolist())
                buf = buf[k * frame_bytes:]
            if progress and total_bytes:
                progress(min(1.0, got / total_bytes))
        proc.wait(30)
    except Cancelled:
        raise
    except Exception:
        kill(proc)
        raise
    reader.join(2)
    if proc.returncode not in (0, None) and not energy:
        msg = (err[0] if err else b"").decode("utf-8", "replace").strip()[-300:]
        raise MediaError(f"FFmpeg could not read the audio of {Path(video).name}: {msg or 'no audio track?'}")
    if not energy:
        raise MediaError(f"{Path(video).name} has no audio to compare with.")
    f = np.array(flags, dtype=bool) if vad is not None else energy_flags(energy)
    return {"times": speech_runs(f), "detector": "webrtcvad" if vad is not None else "energy",
            "channel": channel_mode(channels), "length_ms": len(energy) * VAD_FRAME_MS, "elapsed": time.time() - t0}


def speech_cache_key(video: str, stream_index=None, detector="webrtcvad", channels=None) -> str:
    p = Path(video)
    st = p.stat()
    raw = (f"{p.resolve()}|{st.st_size}|{int(st.st_mtime)}|{stream_index}|{detector}|{VAD_MODE}|{VAD_FRAME_MS}|"
           f"{channel_mode(channels)}")
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def load_cached_speech(video, stream_index=None, cache_dir: Path = None, channels=None):
    import numpy as np
    for det in ("webrtcvad", "energy"):
        f = (CACHE_DIR if cache_dir is None else Path(cache_dir)) /             f"{speech_cache_key(video, stream_index, det, channels)}.npz"
        if f.exists():
            try:
                z = np.load(f)
                return {"times": z["times"], "detector": det, "length_ms": int(z["length_ms"]), "elapsed": 0.0,
                        "cached": True, "channel": channel_mode(channels)}
            except Exception:
                return None
    return None


def save_cached_speech(video, stream_index, speech: dict, cache_dir: Path = None, channels=None):
    import numpy as np
    d = CACHE_DIR if cache_dir is None else Path(cache_dir)
    try:
        d.mkdir(parents=True, exist_ok=True)
        f = d / f"{speech_cache_key(video, stream_index, speech['detector'], channels)}.npz"
        tmp = f.with_suffix(".tmp.npz")
        np.savez_compressed(tmp, times=speech["times"], length_ms=speech["length_ms"])
        os.replace(tmp, f)
    except OSError:
        pass                     # a cache is a convenience: never fail the sync for it


# ── subtitles inside a video (v0.10.0 · S5) ─────────────────────────

TEXT_SUB_CODECS = {"subrip": ".srt", "srt": ".srt", "ass": ".ass", "ssa": ".ass", "mov_text": ".srt",
                   "webvtt": ".srt", "text": ".srt"}
PICTURE_SUB_CODECS = {"hdmv_pgs_subtitle": "PGS (Blu-ray)", "dvd_subtitle": "VobSub (DVD)",
                      "dvb_subtitle": "DVB", "xsub": "XSUB"}
TRACK_CACHE = Path.home() / ".srt_studio" / "cache" / "tracks"


def subtitle_tracks(info: dict) -> list:
    """The subtitle streams of a probed video: [{index, n, codec, language, title, forced, sdh, default, text,
    ext, note}]; n counts subtitle streams from 1 (as players show them)."""
    out = []
    for s in info.get("streams") or []:
        if s.get("type") != "subtitle":
            continue
        codec = (s.get("codec") or "").lower()
        title = s.get("title") or ""
        text = codec in TEXT_SUB_CODECS
        out.append({"index": s.get("index"), "n": len(out) + 1, "codec": codec, "language": s.get("language", ""),
                    "title": title, "forced": bool(s.get("forced")), "default": bool(s.get("default")),
                    "sdh": bool(s.get("hearing_impaired")) or any(w in title.upper() for w in ("SDH", "CC", "HI)")),
                    "text": text, "ext": TEXT_SUB_CODECS.get(codec, ""),
                    "note": "" if text else f"{PICTURE_SUB_CODECS.get(codec, codec or 'unknown')} is a picture "
                                            "subtitle: it needs text recognition (OCR), which is not supported"})
    return out


def track_cache_dir(video: str, base: Path = None) -> Path:
    p = Path(video)
    st = p.stat()
    key = hashlib.sha1(f"{p.resolve()}|{st.st_size}|{int(st.st_mtime)}".encode("utf-8")).hexdigest()[:20]
    return (TRACK_CACHE if base is None else Path(base)) / key


def extract_tracks(ff: dict, video: str, tracks: list, out_dir: Path = None, timeout: float = 900, cancel=None,
                   popen_fn=None) -> dict:
    """All text tracks in one pass over the video (a big file is read once): {stream index: file path}.
    ASS tracks are copied as ASS (styles kept); the others are converted to SRT. Files already extracted
    (same video, same size and date) are reused. The video itself is only read."""
    out_dir = track_cache_dir(video) if out_dir is None else Path(out_dir)
    want = [t for t in tracks if t["text"]]
    paths = {t["index"]: out_dir / f"track{t['index']}{t['ext']}" for t in want}
    todo = [t for t in want if not (paths[t["index"]].exists() and paths[t["index"]].stat().st_size > 0)]
    if todo:
        out_dir.mkdir(parents=True, exist_ok=True)
        tmp = {t["index"]: out_dir / f"track{t['index']}.part{t['ext']}" for t in todo}
        cmd = [ff["ffmpeg"], "-v", "error", "-nostdin", "-y", "-i", str(video)]
        for t in todo:
            cmd += ["-map", f"0:{t['index']}", "-c:s", "copy" if t["ext"] == ".ass" else "srt", str(tmp[t["index"]])]
        try:
            rc, _, err = run(cmd, timeout=timeout, cancel=cancel, popen_fn=popen_fn)
        except BaseException:
            for f in tmp.values():
                try:
                    f.unlink()
                except OSError:
                    pass
            raise
        for t in todo:
            f = tmp[t["index"]]
            if f.exists() and f.stat().st_size > 0:
                os.replace(f, paths[t["index"]])
            else:
                try:
                    f.unlink()
                except OSError:
                    pass
        if rc != 0 and not any(paths[t["index"]].exists() for t in todo):
            raise MediaError(f"FFmpeg could not extract the subtitles of {Path(video).name}: {err.strip()[-300:]}")
    return {i: str(p) for i, p in paths.items() if p.exists()}
