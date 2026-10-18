"""Unit tests for srt_media.py (v0.10.0 · S3): finding FFmpeg, the download, running processes, ffprobe.
No network: the download is served by a local HTTP server or a fake opener."""
import hashlib
import io
import os
import pathlib
import sys
import threading
import time
import zipfile

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import srt_media as sm  # noqa: E402

EXE = sm.EXE
# The FFmpeg download is a Windows build (ffmpeg.exe, ffprobe.exe): its tests run on Windows only.
windows_only = pytest.mark.skipif(sys.platform != "win32", reason="the FFmpeg download is a Windows build")


def _fake_pair(folder):
    folder.mkdir(parents=True, exist_ok=True)
    for n in ("ffmpeg", "ffprobe"):
        (folder / f"{n}{EXE}").write_bytes(b"MZ")
    return folder


def test_find_order_settings_then_downloaded_then_path(tmp_path):
    s, d, p = _fake_pair(tmp_path / "set"), _fake_pair(tmp_path / "tools"), _fake_pair(tmp_path / "onpath")
    env = os.pathsep.join([str(tmp_path / "nothing"), str(p)])
    assert sm.find_ffmpeg(str(s), d, env)["source"] == "settings"
    assert sm.find_ffmpeg(str(s / f"ffmpeg{EXE}"), d, env)["ffmpeg"] == str(s / f"ffmpeg{EXE}")
    assert sm.find_ffmpeg("", d, env)["source"] == "downloaded"
    assert sm.find_ffmpeg(str(tmp_path / "missing"), tmp_path / "none", env)["source"] == "path"
    assert sm.find_ffmpeg("", tmp_path / "none", str(tmp_path / "nothing")) is None
    (s / f"ffprobe{EXE}").unlink()                                       # ffmpeg alone is not enough
    assert sm.find_ffmpeg(str(s), tmp_path / "none", "") is None
    _fake_pair(tmp_path / "tools2" / "bin")
    assert sm.find_ffmpeg("", tmp_path / "tools2", "")["source"] == "downloaded"


def _zip_bytes():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        top = "ffmpeg-n8.1-win64-lgpl-shared-8.1/"
        z.writestr(top + "bin/ffmpeg.exe", b"MZ ffmpeg")
        z.writestr(top + "bin/ffprobe.exe", b"MZ ffprobe")
        z.writestr(top + "bin/ffplay.exe", b"MZ ffplay")
        z.writestr(top + "bin/avcodec-62.dll", b"dll")
        z.writestr(top + "LICENSE.txt", b"LGPL")
        z.writestr(top + "doc/ffmpeg.html", b"<html>")
        z.writestr(top + "include/libavcodec/avcodec.h", b"/* */")
    return buf.getvalue()


ZIP = _zip_bytes()
SHA = hashlib.sha256(ZIP).hexdigest()


class _Resp(io.BytesIO):
    def __init__(self, data, slow=0.0):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}
        self.slow = slow

    def read(self, n=-1):
        if self.slow:
            time.sleep(self.slow)
        return super().read(min(n, 4096) if n and n > 0 else n)


def _leftovers(base):
    return sorted(p.name for p in base.iterdir())


@windows_only
def test_download_keeps_only_the_tools(tmp_path):
    dest = tmp_path / "tools" / "ffmpeg"
    seen = []
    ff = sm.download_ffmpeg(dest, url="x", sha256=SHA, size=len(ZIP), progress=lambda d, t: seen.append((d, t)),
                            opener=lambda u: _Resp(ZIP), verify=lambda ff: "ok")
    assert sorted(p.name for p in dest.iterdir()) == ["LICENSE.txt", "avcodec-62.dll", f"ffmpeg{EXE}",
                                                      f"ffprobe{EXE}"]
    assert ff["source"] == "downloaded" and pathlib.Path(ff["ffprobe"]).read_bytes() == b"MZ ffprobe"
    assert seen[-1] == (len(ZIP), len(ZIP))
    assert _leftovers(tmp_path / "tools") == ["ffmpeg"]                  # no .part, no staging folder


def test_download_sha_mismatch_leaves_nothing(tmp_path):
    dest = tmp_path / "tools" / "ffmpeg"
    with pytest.raises(sm.MediaError, match="SHA-256"):
        sm.download_ffmpeg(dest, url="x", sha256="0" * 64, opener=lambda u: _Resp(ZIP), verify=lambda ff: "ok")
    assert _leftovers(tmp_path / "tools") == []


def test_download_cancel_leaves_nothing_and_keeps_an_old_copy(tmp_path):
    dest = _fake_pair(tmp_path / "tools" / "ffmpeg")
    calls = []
    with pytest.raises(sm.Cancelled):
        sm.download_ffmpeg(dest, url="x", sha256=SHA, opener=lambda u: _Resp(ZIP),
                           cancel=lambda: calls.append(1) or len(calls) > 3, verify=lambda ff: "ok")
    assert _leftovers(tmp_path / "tools") == ["ffmpeg"]
    assert (dest / f"ffmpeg{EXE}").read_bytes() == b"MZ"                  # the copy that was there is untouched


@windows_only
def test_download_that_does_not_run_is_not_installed(tmp_path):
    dest = tmp_path / "tools" / "ffmpeg"

    def bad(ff):
        raise sm.MediaError("FFmpeg does not run properly (exit code 1)")
    with pytest.raises(sm.MediaError, match="does not run"):
        sm.download_ffmpeg(dest, url="x", sha256=SHA, opener=lambda u: _Resp(ZIP), verify=bad)
    assert _leftovers(tmp_path / "tools") == []


@windows_only
def test_download_from_a_local_http_server(tmp_path):
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", str(len(ZIP)))
            self.end_headers()
            self.wfile.write(ZIP)

        def log_message(self, *a):
            pass
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{srv.server_address[1]}/ffmpeg.zip"
        ff = sm.download_ffmpeg(tmp_path / "ff", url=url, sha256=SHA, verify=lambda ff: "ok")
        assert ff and pathlib.Path(ff["ffmpeg"]).exists()
    finally:
        srv.shutdown()


def test_run_cancel_kills_within_a_second():
    cmd = [sys.executable, "-c", "import time; time.sleep(30)"]
    t0 = time.time()
    stop = []
    threading.Timer(0.5, lambda: stop.append(1)).start()
    with pytest.raises(sm.Cancelled):
        sm.run(cmd, timeout=60, cancel=lambda: bool(stop))
    assert time.time() - t0 < 2.0


def test_run_timeout_and_output():
    with pytest.raises(sm.MediaError, match="did not finish"):
        sm.run([sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.5)
    rc, out, err = sm.run([sys.executable, "-c", "import sys; print('hi'); sys.stderr.write('warn')"], timeout=30)
    assert rc == 0 and out.strip() == b"hi" and err == "warn"


PROBE_JSON = """{"streams": [
 {"index": 0, "codec_name": "h264", "codec_type": "video", "avg_frame_rate": "24000/1001", "disposition": {"default": 1}},
 {"index": 1, "codec_name": "ac3", "codec_type": "audio", "channels": 6, "tags": {"language": "eng"},
  "disposition": {"default": 1}},
 {"index": 2, "codec_name": "subrip", "codec_type": "subtitle", "tags": {"language": "eng", "title": "English"},
  "disposition": {"default": 0}},
 {"index": 3, "codec_name": "hdmv_pgs_subtitle", "codec_type": "subtitle", "tags": {"language": "por"},
  "disposition": {"forced": 1}}],
 "format": {"format_name": "matroska,webm", "duration": "1353.120000"}}"""


def test_parse_probe():
    p = sm.parse_probe(PROBE_JSON)
    assert p["duration_ms"] == 1_353_120 and p["format"].startswith("matroska")
    assert [s["type"] for s in p["streams"]] == ["video", "audio", "subtitle", "subtitle"]
    assert p["streams"][0]["fps"] == 23.976 and p["streams"][1]["channels"] == 6
    assert p["streams"][2]["title"] == "English" and p["streams"][3]["forced"] and p["streams"][3]["language"] == "por"


def test_real_ffmpeg_if_installed():
    ff = sm.find_ffmpeg()
    if not ff:
        pytest.skip("no FFmpeg on this PC")
    assert sm.ffmpeg_version(ff).startswith("ffmpeg version")


def test_subtitle_tracks_text_and_picture():
    tr = sm.subtitle_tracks(sm.parse_probe(PROBE_JSON))
    assert [(t["n"], t["index"], t["text"], t["ext"]) for t in tr] == [(1, 2, True, ".srt"), (2, 3, False, "")]
    assert "OCR" in tr[1]["note"] and tr[1]["forced"] and not tr[0]["sdh"]


SRT = "1\n00:00:01,000 --> 00:00:03,000\nHello there\n\n2\n00:00:05,000 --> 00:00:07,500\nSecond line\n\n"
ASS = """[Script Info]
ScriptType: v4.00+

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, \
Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, \
MarginV, Encoding
Style: Sign,Arial,30,&H0000FFFF,&H000000FF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,2,0,8,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:02.00,0:00:04.00,Sign,,0,0,0,,{\an8}A sign
"""


def test_extract_tracks_from_a_real_clip(tmp_path):
    ff = sm.find_ffmpeg()
    if not ff:
        pytest.skip("no FFmpeg on this PC")
    (tmp_path / "a.srt").write_text(SRT, encoding="utf-8")
    (tmp_path / "b.ass").write_text(ASS, encoding="utf-8")
    clip = tmp_path / "clip.mkv"
    rc, _, err = sm.run([ff["ffmpeg"], "-v", "error", "-nostdin", "-y", "-f", "lavfi", "-i",
                         "color=c=black:s=160x120:d=10", "-i", str(tmp_path / "a.srt"), "-i", str(tmp_path / "b.ass"),
                         "-map", "0:v", "-map", "1:s", "-map", "2:s", "-c:v", "mpeg4", "-c:s:0", "srt",
                         "-c:s:1", "ass", "-metadata:s:s:0", "language=eng", "-metadata:s:s:1", "language=por",
                         str(clip)], timeout=120)
    assert rc == 0, err
    tracks = sm.subtitle_tracks(sm.probe(ff, str(clip)))
    assert [(t["codec"], t["language"], t["ext"]) for t in tracks] == [("subrip", "eng", ".srt"), ("ass", "por", ".ass")]
    out = sm.extract_tracks(ff, str(clip), tracks, tmp_path / "cache")
    srt = pathlib.Path(out[tracks[0]["index"]]).read_text(encoding="utf-8")
    ass = pathlib.Path(out[tracks[1]["index"]]).read_text(encoding="utf-8")
    assert "00:00:05,000 --> 00:00:07,500" in srt and "Second line" in srt
    assert "Style: Sign,Arial,30" in ass and "{\an8}A sign" in ass               # ASS stays ASS, styles kept
    again = sm.extract_tracks(ff, str(clip), tracks, tmp_path / "cache")           # cached: no second pass
    assert again == out and not list((tmp_path / "cache").glob("*.part*"))
