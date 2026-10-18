"""Unit tests for srt_sync.py (v0.10.0 · S1): the timing core. No Tk, no network.

Run:  python -m pytest tests -v
"""
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import srt_sync as ss  # noqa: E402


def _blocks(*times):
    """_blocks((1000, 2000), (3000, 4500)) → app blocks with those times."""
    return [{"id": str(i + 1), "timestamp": ss.make_timestamp(s, e), "text_lines": [f"line {i + 1}"]}
            for i, (s, e) in enumerate(times)]


SAMPLE = _blocks((2_145, 7_185), (8_225, 12_105), (60_000, 61_500), (3_599_999, 3_601_000))


# ── times ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text, ms", [
    ("01:02:03,450", 3_723_450), ("1:02:03.45", 3_723_450), ("00:00:00,048", 48), ("02:03", 123_000),
    ("+2.35", 2_350), ("-0,5 s", -500), ("2", 2_000), (".25", 250), ("-1:00", -60_000), (2.35, 2_350),
    ("123:00:00,000", 442_800_000), ("-00:00:01,000", -1_000),
])
def test_to_ms(text, ms):
    assert ss.to_ms(text) == ms


@pytest.mark.parametrize("bad", ["", "abc", "1:2:3:4", "00:61:00", "1,2,3", None])
def test_to_ms_rejects(bad):
    with pytest.raises(ValueError):
        ss.to_ms(bad)


def test_fmt_ms_hours_above_99_and_negative():
    assert ss.fmt_ms(0) == "00:00:00,000"
    assert ss.fmt_ms(3_723_450) == "01:02:03,450"
    assert ss.fmt_ms(100 * 3_600_000 + 1) == "100:00:00,001"
    assert ss.fmt_ms(-5_000) == "00:00:00,000"
    assert ss.parse_timestamp(ss.make_timestamp(100 * 3_600_000, 100 * 3_600_000 + 500)) == (360_000_000,
                                                                                               360_000_500)


def test_fmt_offset():
    assert ss.fmt_offset(2350) == "+2.350 s"
    assert ss.fmt_offset(-1000) == "−1.000 s"
    assert ss.fmt_offset(0) == "0.000 s"


# ── shift / scale / two points / piecewise ───────────────────────────

def test_shift_exact_times_and_flags():
    out = ss.shift(SAMPLE, 2_350)
    assert [ss.parse_timestamp(b["timestamp"]) for b in out] == [
        (4_495, 9_535), (10_575, 14_455), (62_350, 63_850), (3_602_349, 3_603_350)]
    assert all(b["_synced"] for b in out)
    assert [b["text_lines"] for b in out] == [b["text_lines"] for b in SAMPLE]
    assert SAMPLE[0]["timestamp"] == "00:00:02,145 --> 00:00:07,185"      # the old blocks are untouched
    assert "_synced" not in SAMPLE[0]


def test_shift_round_trip_is_identity():
    back = ss.shift(ss.shift(SAMPLE, 1_234), -1_234)
    assert [b["timestamp"] for b in back] == [b["timestamp"] for b in SAMPLE]


def test_negative_times_clamped_and_dropped():
    res = ss.apply_map(SAMPLE, ss.map_shift(-8_000))
    assert res.dropped == [0]                     # 2.145–7.185 ends before 0 → dropped
    assert res.clamped == []                      # 8.225 → 0.225: still after 0
    assert ss.parse_timestamp(res.blocks[0]["timestamp"]) == (225, 4_105)
    res = ss.apply_map(SAMPLE, ss.map_shift(-9_000))
    assert res.clamped == [1] and ss.parse_timestamp(res.blocks[0]["timestamp"]) == (0, 3_105)
    assert len(res.blocks) == 3


def test_clamped_start_counts():
    res = ss.apply_map(_blocks((1_000, 5_000)), ss.map_shift(-2_000))
    assert res.clamped == [0] and res.dropped == []
    assert ss.parse_timestamp(res.blocks[0]["timestamp"]) == (0, 3_000)


def test_scale_frame_rate_25_to_23976():
    ratio = ss.fps_ratio(25, 23.976)
    out = ss.scale(SAMPLE, ratio)
    assert ss.parse_timestamp(out[2]["timestamp"]) == (round(60_000 * 25 / 23.976), round(61_500 * 25 / 23.976))
    back = ss.scale(out, 1 / ratio)
    for a, b in zip(back, SAMPLE):
        sa, sb = ss.parse_timestamp(a["timestamp"]), ss.parse_timestamp(b["timestamp"])
        assert abs(sa[0] - sb[0]) <= 1 and abs(sa[1] - sb[1]) <= 1


def test_scale_with_anchor_keeps_the_anchor():
    out = {b["id"]: b for b in ss.scale(SAMPLE, 1.5, anchor_ms=60_000)}
    assert ss.parse_timestamp(out["3"]["timestamp"]) == (60_000, 62_250)
    assert "1" not in out                          # 2.145 s → before 0 → dropped


def test_two_point_fixes_offset_and_speed():
    # the true map: new = old × 1.04271 + 1500
    r = ss.fps_ratio(25, 23.976)
    a = (2_145, round(2_145 * r + 1_500))
    b = (3_599_999, round(3_599_999 * r + 1_500))
    tmap = ss.map_two_point(a, b)
    assert abs(tmap.ratio - r) < 1e-6
    for blk in SAMPLE:
        s, _ = ss.parse_timestamp(blk["timestamp"])
        assert abs(tmap(s) - (s * r + 1_500)) <= 1
    assert ss.describe_ratio(tmap.ratio) == "25 → 23.976 fps"


def test_two_point_rejects_nonsense():
    with pytest.raises(ValueError):
        ss.map_two_point((1_000, 2_000), (1_000, 5_000))
    with pytest.raises(ValueError):
        ss.map_two_point((1_000, 2_000), (60_000, 1_000))     # backwards
    with pytest.raises(ValueError):
        ss.map_scale(3.0)


def test_piecewise_cut():
    # a cut at 60 s: everything from there on is 5 s later
    out = ss.piecewise(SAMPLE, [(0, 0), (60_000, 5_000)])
    assert [ss.parse_timestamp(b["timestamp"])[0] for b in out] == [2_145, 8_225, 65_000, 3_604_999]
    assert "_synced" not in out[0] and out[2]["_synced"]


def test_identity_moves_nothing():
    res = ss.apply_map(SAMPLE, ss.map_shift(0))
    assert res.moved == 0 and ss.map_shift(0).is_identity
    assert not any(b.get("_synced") for b in res.blocks)


def test_block_without_timing_is_kept():
    blocks = SAMPLE + [{"id": "9", "timestamp": "garbage", "text_lines": ["x"]}]
    out = ss.shift(blocks, 1000)
    assert out[-1]["timestamp"] == "garbage"


def test_describe_ratio():
    assert ss.describe_ratio(1.0) == "same speed"
    assert ss.describe_ratio(ss.fps_ratio(23.976, 25)) == "23.976 → 25 fps"
    assert ss.describe_ratio(1.01).startswith("speed ×1.01")


# ── preview, hints, report ───────────────────────────────────────────

def test_preview_indexes():
    assert ss.preview_indexes(10) == list(range(10))
    idx = ss.preview_indexes(100)
    assert idx[:5] == [0, 1, 2, 3, 4] and idx[-5:] == [95, 96, 97, 98, 99] and len(idx) == 15
    assert 50 in idx


def test_preview_rows_mark_dropped():
    res = ss.apply_map(SAMPLE, ss.map_shift(-8_000))
    rows = ss.preview_rows(SAMPLE, res)
    assert rows[0][2] == "(dropped)" and rows[1][1] == "00:00:08,225" and rows[1][2] == "00:00:00,225"


def test_hints_late_and_video_length():
    late = _blocks(*[(700_000 + i * 3_000, 701_000 + i * 3_000) for i in range(30)])
    kinds = [h["kind"] for h in ss.hints(late)]
    assert "late_start" in kinds
    # a subtitle made for 23.976 fps on a 25 fps video runs 4.3 % too long and ends after the video
    r = ss.fps_ratio(23.976, 25)
    blocks = _blocks(*[(5_000 + i * 60_000, 7_000 + i * 60_000) for i in range(100)])
    video_ms = round(ss.block_times(blocks)[-1][1] * r) + 2_000
    h = [x for x in ss.hints(blocks, video_ms=video_ms) if x["kind"] == "frame_rate"]
    assert h and (h[0]["fill"]["from"], h[0]["fill"]["to"]) == (23.976, 25)
    assert ss.hints(blocks, video_ms=ss.block_times(blocks)[-1][1] + 60_000) == []
    assert ss.hints([]) == []


def test_hints_early_start():
    blocks = _blocks((0, 900), (0, 1_200), (5_000, 6_000))
    assert [h["kind"] for h in ss.hints(blocks)] == ["early_start"]


def test_dialogue_indexes_skip_credits():
    blocks = _blocks((1_000, 2_000), (3_000, 4_000), (5_000, 6_000))
    blocks[0]["text_lines"] = ["Subtitles by SomeGroup"]
    blocks[2]["text_lines"] = ["www.example.com"]
    assert ss.dialogue_indexes(blocks) == [1]


def test_report_contains_the_facts():
    res = ss.apply_map(SAMPLE, ss.map_shift(-8_000))
    text = ss.build_report({"file": "film.en.srt", "format": "SRT", "encoding": "UTF-8", "language": "English",
                            "blocks": len(SAMPLE), "method": "Shift", "result": ["Offset −8.000 s"],
                            "moved": res.moved, "dropped": [(2_145, "line 1")], "clamped": [],
                            "sample": ss.sample_for_report(SAMPLE, res), "output": "", "app_version": "v0.10.0"})
    for part in ("film.en.srt", "Method:      Shift", "Offset −8.000 s", "Dropped (ended before 0:00): 1",
                 "00:00:02,145  line 1", "not saved", "SRT Studio v0.10.0", "Before → after"):
        assert part in text
    assert "already in sync" in ss.build_report({"file": "x", "method": "Check", "already_in_sync": True})


def test_fmt_seconds_round_trips():
    for ms in (0, 1_250, -1_250, -50, 3_600_001):
        assert ss.to_ms(ss.fmt_seconds(ms)) == ms
    assert ss.fmt_seconds(-50) == "-0.050"


def test_hint_prefers_23976_and_names_24_as_nearly_the_same():
    r = ss.fps_ratio(23.976, 25)
    blocks = _blocks(*[(5_000 + i * 60_000, 7_000 + i * 60_000) for i in range(95)])
    last = ss.block_times(blocks)[-1][1]
    for extra in (0, 3_000, 20_000):           # the video a little longer than "just fits" (credits)
        h = [x for x in ss.hints(blocks, video_ms=round(last * r) + extra, video_fps=25) if x["kind"] == "frame_rate"]
        assert h and (h[0]["fill"]["from"], h[0]["fill"]["to"]) == (23.976, 25), extra
        assert "24 fps is nearly the same" in h[0]["text"]


def test_hint_too_long_but_no_frame_rate_fits():
    blocks = _blocks(*[(5_000 + i * 60_000, 7_000 + i * 60_000) for i in range(95)])
    last = ss.block_times(blocks)[-1][1]
    kinds = [x["kind"] for x in ss.hints(blocks, video_ms=last - 30_000, video_fps=25)]   # 0.5 % too long
    assert kinds == ["too_long"]


# ── S2: sync to another subtitle (synthetic films; no media, no network) ──

np = pytest.importorskip("numpy")


def _film(seed, n=900):
    """A plausible subtitle: 900 lines of 1–6 s, short gaps and now and then a long pause (music, action)."""
    import random
    rnd = random.Random(seed)
    t, out = 20_000, []
    for i in range(n):
        d = rnd.randint(1_000, 6_000)
        out.append((t, t + d))
        t += d + (rnd.randint(30_000, 120_000) if rnd.random() < 0.02 else rnd.randint(100, 8_000))
    return _blocks(*out)


def _accuracy(res, blocks, truth):
    """Share of lines whose synced start is within 100 ms of the true one (truth: list of true starts)."""
    ok = sum(1 for b, t in zip(blocks, truth) if t is not None
             and abs(res.tmap(ss.parse_timestamp(b["timestamp"])[0]) - t) <= 100)
    return ok / sum(1 for t in truth if t is not None)


REF = _film(1)
TRUE = [ss.parse_timestamp(b["timestamp"])[0] for b in REF]


def test_s2_identical_is_in_sync():
    res = ss.match_blocks(REF, REF)
    assert res.status == "in_sync" and res.confidence > 0.95 and res.offset_ms == 0


def test_s2_shift_3_2_s():
    sub = ss.shift(REF, 3_200)
    res = ss.match_blocks(REF, sub)
    assert res.status == "offset" and abs(res.offset_ms + 3_200) <= 10
    assert res.confidence >= 0.7 and _accuracy(res, sub, TRUE) >= 0.95
    assert "appear 3.2 s late" in res.status_text() and res.fix_label() == "Fix it: shift −3.200 s"


def test_s2_frame_rate_25_to_23976():
    sub = ss.scale(REF, 25 / 23.976)
    res = ss.match_blocks(REF, sub)
    assert res.status == "drift" and abs(res.ratio - 23.976 / 25) < 1e-6
    assert res.confidence >= 0.7 and _accuracy(res, sub, TRUE) >= 0.95


def test_s2_shift_and_a_40_s_cut():
    # the subtitle is 1.5 s early, and from 30 min on 40 s of the film are missing in its version
    x = []
    for b, t in zip(REF, TRUE):
        s, e = ss.parse_timestamp(b["timestamp"])
        if 1_800_000 <= s < 1_840_000:
            x.append(None)
            continue
        d = -1_500 - (40_000 if s >= 1_840_000 else 0)
        x.append({**b, "timestamp": ss.make_timestamp(s + d, e + d)})
    sub = [b for b in x if b is not None]
    truth = [t for b, t in zip(x, TRUE) if b is not None]
    res = ss.match_blocks(REF, sub)
    assert res.status == "cut" and len(res.segments) == 2
    assert [round(g["offset_ms"] / 100) for g in res.segments] == [15, 415]
    assert res.confidence >= 0.7 and _accuracy(res, sub, truth) >= 0.95


def test_s2_dropped_lines_and_joined_pairs():
    import random
    rnd = random.Random(5)
    keep = [(b, t) for b, t in zip(ss.shift(REF, -2_000), TRUE) if rnd.random() > 0.2]   # another language: fewer lines
    sub, truth = [b for b, _ in keep], [t for _, t in keep]
    res = ss.match_blocks(REF, sub)
    assert res.status == "offset" and abs(res.offset_ms - 2_000) <= 20 and _accuracy(res, sub, truth) >= 0.95
    joined, jt, k = [], [], 0          # pairs of lines close together joined into one block (another splitting)
    while k < len(REF):
        a = ss.parse_timestamp(REF[k]["timestamp"])
        b = ss.parse_timestamp(REF[k + 1]["timestamp"]) if k + 1 < len(REF) else None
        if b and b[0] - a[1] < 1_500:
            joined.append({"id": str(k), "timestamp": ss.make_timestamp(a[0], b[1]), "text_lines": ["x", "y"]})
            k += 2
        else:
            joined.append({"id": str(k), "timestamp": ss.make_timestamp(*a), "text_lines": ["x"]})
            k += 1
        jt.append(a[0])
    res = ss.match_blocks(REF, joined)
    assert res.status in ("in_sync", "uneven") and _accuracy(res, joined, jt) >= 0.95


def test_s2_unrelated_reference_cannot_tell():
    res = ss.match_blocks(REF, _film(99))
    assert res.status == "cannot_tell" and res.confidence < 0.5
    assert res.status_text().startswith("? Cannot tell")


def test_s2_too_few_lines_and_cancel():
    assert ss.match_blocks(REF, REF[:2]).status == "cannot_tell"
    with pytest.raises(ss.Cancelled):
        ss.match_blocks(REF, ss.shift(REF, 500), cancel=lambda: True)
    seen = []
    ss.match_blocks(REF, ss.shift(REF, 500), progress=lambda f, t: seen.append(f))
    assert seen and seen[-1] == 1.0 and seen == sorted(seen)


def test_s2_reference_gap_is_listed():
    # the reference has 4 minutes of dialogue that the subtitle lacks entirely (a scene not in its version)
    sub = [b for b, t in zip(REF, TRUE) if not 2_400_000 <= t < 2_640_000]
    sub = [{**b, "timestamp": ss.make_timestamp(*(x - (240_000 if x >= 2_640_000 else 0)
                                                  for x in ss.parse_timestamp(b["timestamp"])))} for b in sub]
    res = ss.match_blocks(REF, sub)
    assert res.status == "cut"
    assert any(a >= 2_390_000 and b <= 2_650_000 for a, b in res.ref_gaps), res.ref_gaps


def test_s2_jitter_against_the_same_timing_is_aligned_line_by_line():
    import random
    rnd = random.Random(8)
    sub, truth = [], []
    for b, t in zip(REF, TRUE):
        j = rnd.randint(-300, 300)
        s, e = ss.parse_timestamp(b["timestamp"])
        sub.append({**b, "timestamp": ss.make_timestamp(s + j, e + j)})
        truth.append(t)
    res = ss.match_blocks(REF, sub)
    assert res.shared_timing and res.status == "uneven" and res.lines_aligned > 0.5 * len(REF)
    assert _accuracy(res, sub, truth) >= 0.95
    assert "aligned line by line" in res.status_text()


def test_s2_different_intro_is_a_part_of_its_own():
    first = TRUE[0]
    sub = [{**b, "timestamp": ss.make_timestamp(*(x + (45_000 if t >= first + 180_000 else 0)
                                                  for x in ss.parse_timestamp(b["timestamp"])))}
           for b, t in zip(REF, TRUE)]
    res = ss.match_blocks(REF, sub)
    assert res.status == "cut" and [g["offset_ms"] for g in res.segments] == [0, -45_000]
    assert _accuracy(res, sub, TRUE) >= 0.95
