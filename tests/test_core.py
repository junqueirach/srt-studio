"""Unit tests for the pure (non-GUI, non-network) parts of srt_translator.py.

Run:  python -m pytest tests -v
They need neither an API key nor the anthropic/requests packages.
"""
import importlib.util
import json
import pathlib
import re
import sys
import threading

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _version_key(path) -> tuple:
    """Numeric version from a file name: srt_translator_v0.10.0.py → (0, 10, 0)."""
    m = re.search(r"_v(\d+(?:\.\d+)*)\.py$", pathlib.Path(path).name)
    return tuple(int(x) for x in m.group(1).split(".")) if m else ()


def _candidates(root) -> list:
    """The repo file (srt_studio.py, or the older srt_translator.py) first, then the versioned dev files,
    newest version first. All name patterns are accepted: srt_studio_v0.9.0.py (from v0.9.0),
    srt_translator_v0.8.1.py and the older srt_translator_gui_v0.8.0.py."""
    versioned = [p for pat in ("srt_studio_v*.py", "srt_translator_v*.py", "srt_translator_gui_v*.py")
                 for p in root.glob(pat)]
    return ([root / "srt_studio.py", root / "srt_translator.py"]
            + sorted(versioned, key=_version_key, reverse=True))


def _load_module():
    for path in _candidates(ROOT):
        if path.exists():
            spec = importlib.util.spec_from_file_location("srt_translator", path)
            mod = importlib.util.module_from_spec(spec)
            sys.modules["srt_translator"] = mod
            spec.loader.exec_module(mod)
            return mod
    raise FileNotFoundError("srt_studio_v*.py / srt_translator.py not found")


pytest.importorskip("tkinter")
st = _load_module()


# ── SRT parsing / writing ────────────────────────────────────────────

SAMPLE = """\ufeff1
00:00:02,145 --> 00:00:07,185
This programme contains
some strong language

2
00:00:08,225 --> 00:00:12,105
[door slams]

3
00:00:20,225 --> 00:00:23,185

4
00:00:23,185 --> 00:00:25,745
<i>the aircraft I was in,</i>
British Airways,
"""


def test_parse_keeps_empty_blocks_and_strips_bom():
    blocks = st.parse_srt_text(SAMPLE)
    assert [b["id"] for b in blocks] == ["1", "2", "3", "4"]
    assert blocks[0]["text_lines"] == ["This programme contains", "some strong language"]
    assert blocks[2]["text_lines"] == []


def test_write_then_parse_roundtrip(tmp_path):
    blocks = st.parse_srt_text(SAMPLE)
    out = tmp_path / "x.srt"
    st.write_srt(blocks, str(out))
    again, enc = st.parse_srt(str(out))
    assert enc == "utf-8-sig"
    assert [b["timestamp"] for b in again] == [b["timestamp"] for b in blocks]
    assert [b["text_lines"] for b in again] == [b["text_lines"] for b in blocks]


def test_timestamp_ms():
    assert st.timestamp_ms("00:01:02,345 --> 00:01:04,000") == (62345, 64000)
    assert st.timestamp_ms("garbage") == (0, 0)


# ── Output naming ────────────────────────────────────────────────────

@pytest.mark.parametrize("stem,expected", [
    ("Movie.en", "Movie"),
    ("Movie.en-US", "Movie"),
    ("Movie.eng.sdh", "Movie"),
    ("Movie.2023", "Movie.2023"),
    ("Movie (2023) [1080p].en", "Movie (2023) [1080p]"),
    ("Movie", "Movie"),
])
def test_strip_language_tag(stem, expected):
    assert st.strip_language_tag(stem) == expected


def test_default_output_name():
    assert st.default_output_name(str(pathlib.Path("x") / "Movie.en.srt"), "pt-BR") == "Movie.pt-BR.srt"


# ── Cues, tags, passthrough ──────────────────────────────────────────

@pytest.mark.parametrize("line,cue", [
    ("[door slams]", True),
    ("(laughs)", True),
    ("APPLAUSE", True),
    ("CHEERING AND APPLAUSE", True),
    ("MAN ON TV:", True),
    ("Hello there", False),
    ("- OK.", False),
    ("♪", False),
    ("1999", False),
])
def test_is_cue(line, cue):
    assert st.is_cue(line) is cue


def test_passthrough_rules():
    assert st.is_passthrough("") is True
    assert st.is_passthrough("...") is True
    assert st.is_passthrough("♪ ♪") is True
    assert st.is_passthrough("[door slams]", translate_cues=True) is False   # v0.7.0 fix
    assert st.is_passthrough("[door slams]", translate_cues=False) is True
    assert st.is_passthrough("<i>Hello</i>") is False


def test_protect_and_restore_tags():
    core, tags = st.protect_tags("<i>Hello</i> {\\an8}world")
    assert core == "{T1}Hello{T2} {T3}world"
    assert st.restore_tags("{T1}Olá{T2} {T3}mundo", tags) == "<i>Olá</i> {\\an8}mundo"
    # placeholder lost by the model: tags are re-attached, nothing is left behind
    assert st.restore_tags("Olá mundo", tags) == "{\\an8}<i>Olá mundo</i>"
    assert "{T" not in st.restore_tags("Olá {T9} mundo", tags)


# ── Glossary ─────────────────────────────────────────────────────────

def test_parse_glossary_dedup_and_split():
    assert st.parse_glossary("Arif Naqvi\nOxford University, Abraaj\n\narif naqvi\n• Dubai") == \
        ["Arif Naqvi", "Oxford University", "Abraaj", "Dubai"]


def test_glossary_violations():
    terms = ["Arif Naqvi", "Oxford"]
    assert st.glossary_violations("Arif Naqvi went to Oxford.", "Arif Naqvi foi para Oxford.", terms) == []
    assert st.glossary_violations("Arif Naqvi went to Oxford.", "Arif Naqvi foi para Oxônia.", terms) == ["Oxford"]
    assert st.glossary_violations("No names here.", "Sem nomes aqui.", terms) == []


def test_sidecar_path():
    assert st.glossary_sidecar_path(str(pathlib.Path("x") / "Movie.en.srt")).name == "Movie.names.txt"


# ── Models & pricing ─────────────────────────────────────────────────

@pytest.mark.parametrize("s,key", [
    ("claude-haiku-5-5", "haiku 5.5"),
    ("claude-haiku-4-5-20251001", "haiku 4.5"),
    ("claude-sonnet-4-20250514", "sonnet 4"),
    ("claude-opus-5", "opus 5"),
    ("Claude Haiku 5.5 (for prompts up to 100,000 tokens)", "haiku 5.5"),
    ("Claude Opus 4.1 ([retired](x))", "opus 4.1"),
    ("gpt-4", ""),
])
def test_model_family_key(s, key):
    assert st.model_family_key(s) == key


PRICING_MD = """\
## Model pricing

| Model | Base input tokens | 5m cache writes | 1h cache writes | Cache hits and refreshes | Output tokens |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Claude Haiku 5.5 (for prompts up to 100,000 tokens) | $0.10 / MTok | $0.125 / MTok | $0.20 / MTok | $0.01 / MTok | $0.50 / MTok |
| Claude Haiku 5.5 (for prompts over 100,000 tokens) | $0.50 / MTok | $0.625 / MTok | $1 / MTok | $0.05 / MTok | $2.50 / MTok |
| Claude Sonnet 5 | $2 / MTok<sup>3</sup> | $2.50 / MTok | $4 / MTok | $0.20 / MTok | $10 / MTok |

## Other table

| Model | Something | Else |
| --- | --- | --- |
| Claude Opus 5.5 | $8 / MTok | $40 / MTok |
"""


def test_parse_pricing_markdown():
    prices = st.parse_pricing_markdown(PRICING_MD)
    assert prices["haiku 5.5"] == {"input": 0.10, "cache_write": 0.125, "cache_read": 0.01, "output": 0.50}
    assert prices["sonnet 5"]["output"] == 10.0
    assert "opus 5.5" not in prices          # second table has a different header


def test_catalog_price_precedence_and_fallback(tmp_path, monkeypatch):
    cat = st.Catalog({})
    assert cat.price("claude-haiku-5-5")["source"] == "built-in"
    cat.prices = {"haiku 5.5": {"input": 0.2, "output": 1.0}}
    cat.prices_source = "live"
    p = cat.price("claude-haiku-5-5")
    assert (p["input"], p["source"]) == (0.2, "live")
    cat.override = {"haiku 5.5": {"input": 9, "output": 9}}
    assert cat.price("claude-haiku-5-5")["source"] == "override"
    assert cat.price("claude-unknown-9")["input"] is None


def test_catalog_pick_default():
    cat = st.Catalog({})
    assert cat.pick_default("claude-sonnet-4-20250514") == st.DEFAULT_MODEL    # retired id falls back
    assert cat.pick_default("claude-sonnet-5-5") == "claude-sonnet-5-5"


def test_estimate_cost_approx():
    blocks = st.parse_srt_text(SAMPLE)
    est = st.estimate_cost(blocks, "claude-haiku-5-5", st.Catalog({}), batch_size=2)
    assert est["method"] == "approx"
    assert est["total_cost"] > 0
    assert est["n_batches"] == 2


# ── Prompt building & response handling ──────────────────────────────

def test_build_batch_prompt_skips_passthrough_and_protects_tags():
    blocks = st.parse_srt_text(SAMPLE)
    prompt, items = st.build_batch_prompt(blocks, translate_cues=True)
    assert "[b78]\nThis programme contains\nsome strong language" in prompt
    assert "[c15]\n[door slams]" in prompt
    assert "{T1}the aircraft I was in,{T2}" in prompt
    assert [i for i, _, _, _ in items] == [0, 1, 3]       # empty block 3 skipped
    assert [k for _, _, _, k in items] == ["b78", "c15", "d52"]


def test_block_keys_unique_and_non_sequential():
    keys = [st.block_key(n) for n in range(1, 60)]
    assert len(set(keys)) == len(keys)
    assert not any(k[1:] == f"{n:02d}" for n, k in enumerate(keys, 1))


def test_rewrap():
    assert st.rewrap(["one line only"], 1) == ["one line only"]
    out = st.rewrap(["a fairly long sentence that was returned", "as three", "lines"], 2)
    assert len(out) == 2 and " ".join(out).split() == "a fairly long sentence that was returned as three lines".split()
    assert st.rewrap(["only"], 2) == ["only", ""]
    assert st.rewrap(["x y z w"], 4) == ["x", "y", "z", "w"]


def test_parse_json_blocks_tolerant():
    raw = 'Sure:\n{"blocks":[{"k":"b78","lines":["a","b"]},{"k":"[c15]","lines":["c"]}]}'
    assert st._parse_json_blocks(raw) == {"b78": ["a", "b"], "c15": ["c"]}
    assert st._parse_json_blocks("nonsense") == {}


def test_context_window_text():
    ctx = [{"timestamp": "00:00:00,000 --> 00:00:02,000", "text_lines": ["early"]},
           {"timestamp": "00:01:00,000 --> 00:01:02,000", "text_lines": ["middle"]},
           {"timestamp": "00:05:00,000 --> 00:05:02,000", "text_lines": ["late"]}]
    assert st.context_window_text(ctx, 60_000, 61_000) == "middle"
    # no overlap at all → proportional fallback still returns something
    assert st.context_window_text(ctx, 3_000_000, 3_001_000, 0.9, 1.0) != ""


class _FakeUsage:
    input_tokens = 10
    output_tokens = 5
    cache_read_input_tokens = 0
    cache_creation_input_tokens = 0


class _FakeResp:
    def __init__(self, text, stop="end_turn"):
        self.stop_reason = stop
        self.usage = _FakeUsage()
        self.content = [type("B", (), {"type": "text", "text": text})()]


class _FakeClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        return self._responses.pop(0)


def test_claude_translate_batch_rewraps_and_flags(monkeypatch):
    blocks = st.parse_srt_text(SAMPLE)
    model = st._BUILTIN_MODELS[0]
    resp = _FakeResp('{"blocks":[{"k":"b78","lines":["Este programa contém linguagem forte"]},'
                     '{"k":"c15","lines":["[porta bate]"]}]}')     # key d52 (3rd item) missing
    client = _FakeClient([resp])
    usage = st.UsageTotals()
    out = st.claude_translate_batch(client, blocks, "English", "Portuguese", model, ["British Airways"],
                                    "", True, usage)
    assert len(out[0]["text_lines"]) == 2                       # one line came back → rewrapped to 2
    assert out[1]["text_lines"] == ["[porta bate]"]
    assert out[3].get("_untranslated") is True                  # missing → flagged for QC
    assert out[3]["text_lines"] == blocks[3]["text_lines"]
    assert usage.calls == 1 and usage.input == 10
    kw = client.calls[0]
    assert kw["thinking"] == {"type": "disabled"}
    assert kw["output_config"]["format"]["type"] == "json_schema"
    assert "British Airways" in kw["system"][0]["text"]


def test_claude_translate_batch_splits_on_max_tokens():
    blocks = st.parse_srt_text(SAMPLE)
    model = st._BUILTIN_MODELS[0]
    client = _FakeClient([
        _FakeResp("", stop="max_tokens"),
        _FakeResp('{"blocks":[{"k":"b78","lines":["A","B"]},{"k":"c15","lines":["[C]"]}]}'),
        _FakeResp('{"blocks":[{"k":"b78","lines":["D","E"]}]}'),
    ])
    out = st.claude_translate_batch(client, blocks, "English", "Portuguese", model, [], "", True, st.UsageTotals())
    assert len(client.calls) == 3
    assert out[0]["text_lines"] == ["A", "B"]
    assert out[3]["text_lines"] == ["<i>D</i>", "E"]


def test_claude_translate_batch_refusal():
    blocks = st.parse_srt_text(SAMPLE)
    client = _FakeClient([_FakeResp("", stop="refusal")])
    with pytest.raises(st.BatchRefused):
        st.claude_translate_batch(client, blocks, "English", "Portuguese", st._BUILTIN_MODELS[0], [], "", True, st.UsageTotals())


# ── Quality control ──────────────────────────────────────────────────

def test_qc_report_flags_unchanged_and_names():
    src = st.parse_srt_text(SAMPLE)
    out = [dict(b, text_lines=b["text_lines"][:]) for b in src]
    out[0]["text_lines"] = ["Este programa contém", "linguagem forte"]
    out[1]["text_lines"] = ["[porta bate]"]
    out[3]["text_lines"] = ["<i>the aircraft I was in,</i>", "British Airways,"]   # unchanged
    report = st.qc_report(src, out, ["British Airways"], True)
    kinds = {(i, k) for i, k, _ in report}
    assert (3, "unchanged") in kinds
    assert (0, "unchanged") not in kinds
    out[3]["text_lines"] = ["<i>o avião em que eu estava,</i>", "Linhas Aéreas Britânicas,"]
    report = st.qc_report(src, out, ["British Airways"], True)
    assert [(i, k) for i, k, _ in report] == [(3, "name")]


def test_qc_flags_missing_year():
    src = [{"id": "1", "timestamp": "t", "text_lines": ["On 10th April 2019, the plane landed."]}]
    out = [{"id": "1", "timestamp": "t", "text_lines": ["Em 10 de abril de 2018, o avião pousou."]}]
    assert [(k, d) for _, k, d in st.qc_report(src, out, [], True)] == [("number", "missing: 2019")]


def test_qc_ignores_short_or_passthrough_blocks():
    src = [{"id": "1", "timestamp": "t", "text_lines": ["OK."]},
           {"id": "2", "timestamp": "t", "text_lines": ["..."]}]
    assert st.qc_report(src, [dict(b) for b in src], [], True) == []


def test_usage_totals_cost():
    u = st.UsageTotals()
    u.add(_FakeUsage())
    price = {"input": 1.0, "output": 2.0, "cache_read": 0.1, "cache_write": 1.25}
    assert u.cost(price) == pytest.approx((10 * 1.0 + 5 * 2.0) / 1e6)
    assert u.cost({"input": None}) is None


# ── v0.8.1 · A2: version-safe loader ────────────────────────────────

def test_loader_sorts_versions_as_numbers(tmp_path):
    for name in ("srt_translator_gui_v0.8.0.py", "srt_studio_v0.9.0.py",
                 "srt_studio_v0.10.0.py", "srt_translator_v0.8.1.py"):
        (tmp_path / name).write_text("", encoding="utf-8")
    order = [p.name for p in _candidates(tmp_path)[2:]]
    assert order == ["srt_studio_v0.10.0.py", "srt_studio_v0.9.0.py",
                     "srt_translator_v0.8.1.py", "srt_translator_gui_v0.8.0.py"]


def test_loader_picks_this_version():
    assert st.APP_VERSION == "v0.9.0"


# ── v0.8.1 · A1: safe writes ────────────────────────────────────────

def test_save_config_threads_keep_every_key(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "CONFIG_PATH", tmp_path / "cfg.json")
    threads = [threading.Thread(target=st.save_config, args=({f"key{i}": i},)) for i in range(20)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    data = json.loads((tmp_path / "cfg.json").read_text(encoding="utf-8"))
    assert all(data[f"key{i}"] == i for i in range(20))
    assert data["config_version"] == st.CONFIG_VERSION
    assert not list(tmp_path.glob("*.tmp"))


def test_corrupt_config_is_kept_and_reported(tmp_path, monkeypatch):
    cfg = tmp_path / "cfg.json"
    cfg.write_text('{"api_key": "abc", "glossary": ', encoding="utf-8")     # cut off
    monkeypatch.setattr(st, "CONFIG_PATH", cfg)
    monkeypatch.setattr(st, "CONFIG_WARNINGS", [])
    assert st.load_config() == {}
    copies = list(tmp_path.glob("cfg.json.corrupt-*"))
    assert len(copies) == 1 and copies[0].read_text(encoding="utf-8").startswith('{"api_key"')
    assert st.CONFIG_WARNINGS and "corrupt" in st.CONFIG_WARNINGS[0]
    st.save_config({"x": 1})                                               # repaired on the next save
    assert json.loads(cfg.read_text(encoding="utf-8"))["x"] == 1


def test_write_srt_failure_leaves_target_and_no_tmp(tmp_path):
    target = tmp_path / "out.srt"
    target.write_text("old", encoding="utf-8")
    bad = [{"id": "1", "timestamp": "00:00:01,000 --> 00:00:02,000", "text_lines": None}]   # not iterable
    with pytest.raises(TypeError):
        st.write_srt(bad, str(target))
    assert target.read_text(encoding="utf-8") == "old"
    assert not list(tmp_path.glob("*.tmp"))


def test_write_srt_to_missing_folder_raises(tmp_path):
    with pytest.raises(OSError):
        st.write_srt(st.parse_srt_text(SAMPLE), str(tmp_path / "missing" / "out.srt"))
    assert not list(tmp_path.rglob("*.tmp"))


# ── v0.8.1 · U3: cost and finish message ────────────────────────────

class _Usage:
    def __init__(self, i, o, cr=0, cw=0):
        self.input_tokens, self.output_tokens = i, o
        self.cache_read_input_tokens, self.cache_creation_input_tokens = cr, cw


HAIKU = {"input": 0.10, "output": 0.50, "cache_read": 0.01, "cache_write": 0.125, "source": "live"}


def test_usage_cost_includes_cache_exactly():
    u = st.UsageTotals()
    u.add(_Usage(29_810, 27_087, cr=12_400, cw=1_600))
    expected = (29_810 * 0.10 + 27_087 * 0.50 + 12_400 * 0.01 + 1_600 * 0.125) / 1e6
    assert u.cost(HAIKU) == pytest.approx(expected)
    assert u.calls == 1


def test_format_usd():
    assert st.format_usd(0.0171234) == "$0.0171"
    assert st.format_usd(1.234) == "$1.23"
    assert st.format_usd(1234.5) == "$1,234.50"
    assert st.format_usd(None) == "unknown"


def test_cost_ledger_total_and_breakdown():
    led = st.CostLedger()
    for kind, (i, o) in (("sample", (1000, 1000)), ("names", (2000, 100)), ("translation", (20_000, 18_000))):
        u = st.UsageTotals()
        u.add(_Usage(i, o))
        led.add(kind, "claude-haiku-5-5", u, HAIKU)
    run = (20_000 * 0.10 + 18_000 * 0.50) / 1e6
    smp = (1000 * 0.10 + 1000 * 0.50) / 1e6
    nam = (2000 * 0.10 + 100 * 0.50) / 1e6
    assert led.total() == pytest.approx(run + smp + nam)
    assert led.breakdown() == f"run {st.format_usd(run)} + sample {st.format_usd(smp)} + names {st.format_usd(nam)}"
    led.clear()
    assert led.entries == [] and led.total() == 0


def test_cost_ledger_unknown_price():
    led = st.CostLedger()
    u = st.UsageTotals()
    u.add(_Usage(10, 10))
    led.add("translation", "x", u, {"input": None})
    assert led.total() is None and "unknown" in led.breakdown()


def test_price_source_text():
    class Cat:
        prices_fetched_at = 1_789_000_000
    assert st.price_source_text(Cat, {**HAIKU, "source": "live"})[1] is True
    assert "Anthropic pricing page" in st.price_source_text(Cat, {**HAIKU, "source": "cache"})[0]
    text, ok = st.price_source_text(Cat, {**HAIKU, "source": "built-in"})
    assert not ok and "may be out of date" in text
    assert st.price_source_text(Cat, {**HAIKU, "source": "override"})[1] is True
    assert st.price_source_text(Cat, {"input": None, "source": "unknown"})[1] is False


def _result(**kw):
    base = {"engine": "claude", "sample": False, "cancelled": False, "ok": True, "saved_path": "C:/x/Movie.pt-BR.srt",
            "save_error": "", "flagged": 1, "total": 903, "cost": 0.0171}
    base.update(kw)
    return base


def test_finish_summary_cases():
    d, s = st.finish_summary(_result())
    assert d == "finished" and "Movie.pt-BR.srt" in s and "$0.0171" in s
    d, s = st.finish_summary(_result(sample=True, saved_path="", total=20))
    assert d is None and s.startswith("Sample done — 20 blocks") and "$0.0171" in s
    d, s = st.finish_summary(_result(cancelled=True, ok=False))
    assert d is None and s == "Cancelled — cost so far $0.0171"
    d, s = st.finish_summary(_result(ok=False, save_error="Permission denied", saved_path=""))
    assert d == "save_failed" and s.startswith("Not saved") and "Done" not in s
    d, s = st.finish_summary(_result(ok=False))
    assert d is None and "errors" in s
    d, s = st.finish_summary(_result(engine="free", cost=None))
    assert d == "finished" and "free" in s


def test_builtin_prices_checked():
    assert st._BUILTIN_PRICES["sonnet 5.5"]["cache_read"] == 0.10


# ── v0.8.1 · U4: names belong to one subtitle ───────────────────────

def test_saved_names_for(tmp_path):
    a, b = str(tmp_path / "A.en.srt"), str(tmp_path / "B.en.srt")
    cfg = {"file": a, "names": "Ashley\nJack"}
    assert st.saved_names_for(cfg, a) == "Ashley\nJack"
    assert st.saved_names_for(cfg, b) == ""
    assert st.saved_names_for("Old\nList", a) == ""          # v0.8.0 plain string is not restored
    assert st.saved_names_for(None, a) == ""


def test_names_unsaved():
    assert st.names_unsaved(["Ashley", "Jack"], ["ashley"]) is True
    assert st.names_unsaved(["Ashley"], ["Ashley", "Jack"]) is False
    assert st.names_unsaved([], []) is False


def test_same_file(tmp_path):
    p = tmp_path / "Movie.en.srt"
    assert st.same_file(str(p), str(tmp_path / "." / "Movie.en.srt"))
    assert not st.same_file(str(p), "")
    assert not st.same_file(str(p), str(tmp_path / "Other.srt"))


# ── v0.8.1 · U5: short model labels ─────────────────────────────────

def test_model_labels_short(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "PRICING_OVERRIDE_PATH", tmp_path / "none.json")
    cat = st.Catalog({})
    for m in st._BUILTIN_MODELS:
        lab = cat.label(m["id"])
        assert len(lab) <= 45, lab
        assert m["display_name"] in cat.long_label(m["id"])
    assert cat.label("claude-haiku-5-5") == "Claude Haiku 5.5 · $0.10/$0.50 · 1M ★"
    assert cat.label("claude-sonnet-5-5") == "Claude Sonnet 5.5 · $2/$10 · 1M"


# ── Help is kept up to date (plan rule C) ───────────────────────────

def test_help_mentions_settings_and_tabs():
    # v0.9.0: every tab, every Settings page and option, the divider and the new features are explained
    for text in ("NEW IN v0.9.0", "NEW IN v0.8.1", "Subtitles tab", "Names", "Log", "Settings", "General",
                 "Output format", "Encoding", "AI notice", "Repair", "Remove ad and credit lines", "Files",
                 "Show a message when a translation finishes", "Total for this subtitle", "Divider",
                 "Reset layout", "Recent", "Sample from", "Save log", "Drag and drop", "Ctrl+O", "SRT Studio",
                 "ASS", "WebVTT", "MicroDVD", "OCR", "Save repaired copy", "Batch size", "workers"):
        assert text.lower() in st.HELP_TEXT.lower(), text


# ── v0.8.1 · encodings: UTF-16/UTF-32 files (Notepad "Unicode") ─────

ENC_TEXT = ("1\r\n00:00:12,400 --> 00:00:14,039\r\nPROFESSOR BRIAN COX: Why are we here?\r\n\r\n"
            "2\r\n00:00:14,120 --> 00:00:16,000\r\nVocê está aqui — ação, coração\r\n\r\n")


@pytest.mark.parametrize("data, enc_name", [
    (b"\xff\xfe" + ENC_TEXT.encode("utf-16-le"), "utf-16+bom"),
    (b"\xfe\xff" + ENC_TEXT.encode("utf-16-be"), "utf-16+bom"),
    (ENC_TEXT.encode("utf-16-le"), "utf-16-le"),
    (ENC_TEXT.encode("utf-16-be"), "utf-16-be"),
    (b"\xff\xfe\x00\x00" + ENC_TEXT.encode("utf-32-le"), "utf-32+bom"),
    (b"\xef\xbb\xbf" + ENC_TEXT.encode("utf-8"), "utf-8-sig"),
    (ENC_TEXT.encode("utf-8"), "utf-8-sig"),          # plain UTF-8 decodes with utf-8-sig too
    (ENC_TEXT.encode("cp1252"), "cp1252"),
])
def test_every_unicode_variant_loads(tmp_path, data, enc_name):
    p = tmp_path / "Movie.en.srt"
    p.write_bytes(data)
    blocks, enc = st.parse_srt(str(p))
    assert enc == enc_name
    assert len(blocks) == 2
    assert blocks[0]["timestamp"] == "00:00:12,400 --> 00:00:14,039"
    assert blocks[0]["text_lines"] == ["PROFESSOR BRIAN COX: Why are we here?"]
    assert blocks[1]["text_lines"] == ["Você está aqui — ação, coração"]


def test_decode_never_returns_nul_characters():
    text, _ = st.decode_subtitle_bytes(b"1\x00\r\x00\n\x00x\x00y" + b"\x00" * 3)
    assert "\x00" not in text


def test_utf16_output_roundtrip_is_utf8(tmp_path):
    src = tmp_path / "in.srt"
    src.write_bytes(b"\xff\xfe" + ENC_TEXT.encode("utf-16-le"))
    blocks, _ = st.parse_srt(str(src))
    out = tmp_path / "out.srt"
    st.write_srt(blocks, str(out))
    again, enc = st.parse_srt(str(out))
    assert enc == "utf-8-sig" and again == blocks


# ════════════════════════════════════════════════════════════════════
# v0.9.0
# ════════════════════════════════════════════════════════════════════

def test_app_renamed():
    assert st.APP_NAME == "SRT Studio" and st.APP_VERSION == "v0.9.0"
    assert st.CONFIG_PATH.name == ".srt_studio_config.json"


def test_timestamp_ms_keeps_leading_zero_milliseconds():
    # v0.8.x read ",048" as 480 ms
    assert st.timestamp_ms("00:41:40,084 --> 00:41:45,048") == (2_500_084, 2_505_048)
    assert st.timestamp_ms("00:00:01,5 --> 00:00:02,05") == (1500, 2050)
    assert st.ms_to_srt_time(2_505_048) == "00:41:45,048"


def test_old_config_imported_once(tmp_path, monkeypatch):
    old, new = tmp_path / ".srt_translator_config.json", tmp_path / ".srt_studio_config.json"
    old.write_text(json.dumps({"api_key": "k", "target_lang": "pt-BR"}), encoding="utf-8")
    monkeypatch.setattr(st, "OLD_CONFIG_PATH", old)
    monkeypatch.setattr(st, "CONFIG_PATH", new)
    monkeypatch.setattr(st, "CONFIG_WARNINGS", [])
    cfg = st.load_config()
    assert cfg["api_key"] == "k" and new.exists() and old.exists()
    assert "imported" in st.CONFIG_WARNINGS[0]
    st.save_config({"api_key": "changed"})
    assert json.loads(old.read_text(encoding="utf-8"))["api_key"] == "k"      # old file never changed
    assert st.load_config()["api_key"] == "changed"


# ── L1 languages ─────────────────────────────────────────────────────

def _blocks(*lines):
    return [{"id": str(i + 1), "timestamp": st.make_timestamp(i * 2000, i * 2000 + 1500), "text_lines": [l]}
            for i, l in enumerate(lines)]


@pytest.mark.parametrize("text, code", [
    ("สวัสดีครับ คุณเป็นอย่างไรบ้าง วันนี้อากาศดีมาก", "th-TH"),
    ("Привет, как дела? Что ты здесь делаешь сегодня вечером", "ru-RU"),
    ("Привіт, як справи? Що ти тут робиш сьогодні ввечері, її єнот ґанок", "uk-UA"),
    ("Γεια σου, τι κάνεις σήμερα; Πού πηγαίνεις απόψε", "el-GR"),
    ("שלום, מה שלומך היום? לאן אתה הולך הערב", "he-IL"),
    ("مرحبا كيف حالك اليوم إلى أين أنت ذاهب", "ar-AR"),
    ("नमस्ते आप कैसे हैं आज आप कहाँ जा रहे हैं", "hi-IN"),
    ("안녕하세요 오늘 어떻게 지내세요 어디 가세요", "ko-KR"),
    ("こんにちは、今日はどこに行きますか。わたしはがっこうにいきます", "ja-JP"),
    ("你好，今天你要去哪里？我们这个时候说什么", "zh-CN"),
    ("你好，今天你要去哪裡？我們這個時候說什麼", "zh-TW"),
])
def test_detect_by_script(text, code):
    assert st.detect_language(_blocks(*([text] * 10))) == code


@pytest.mark.parametrize("text, code", [
    ("What is this? I will tell you where and when they would go, but not how.", "en-US"),
    ("Você não está aqui, isso é muito bom, então ele tem uma casa também.", "pt-BR"),
    ("Pero usted tiene los papeles, gracias, ahora estoy aquí con las chicas.", "es-ES"),
    ("Het is niet wat ik dacht, maar hij weet het goed, ook zij zijn hier.", "nl-NL"),
    ("Jag vet inte vad det är, och varför har du det som mig?", "sv-SE"),
    ("Nie wiem, co to jest, ale już tak, czy jestem tutaj, że się boję.", "pl-PL"),
    ("Ben sen ve bir şey için değil ama çok var mı bu?", "tr-TR"),
    ("Saya tidak tahu apa yang kamu mau dengan itu, ada aku untuk ini.", "id-ID"),
])
def test_detect_latin_words(text, code):
    assert st.detect_language(_blocks(*([text] * 6))) == code


def test_detect_unknown_instead_of_wrong():
    assert st.detect_language(_blocks("12:00", "♪ ♪", "OK", "Hmm.")) == ""
    assert st.detect_language([]) == ""


def test_language_list_and_notice_cover_every_language():
    codes = [c for c, _, _ in st.LANGUAGES]
    assert len(codes) == len(set(codes)) >= 32
    for c in codes:
        text = st.notice_text_for(c, "Claude Haiku 5.5")
        assert "Claude Haiku 5.5" in text
        assert c in st._MM_LANG or c.split("-")[0] in ("en",), c


# ── F1 formats ───────────────────────────────────────────────────────

ASS_SAMPLE = """[Script Info]
ScriptType: v4.00+
PlayResX: 640
PlayResY: 480

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,28,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,1,2,20,20,20,1
Style: Sign,Arial,20,&H0000FFFF,&H000000FF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,2,1,8,20,20,20,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:03.50,Default,,0,0,0,,{\\an4\\pos(100,200)}Hello there,\\Nhow are you?
Comment: 0,0:00:02.00,0:00:04.00,Default,,0,0,0,,Translator note: keep this
Dialogue: 0,0:00:02.00,0:00:05.00,Sign,,0,0,0,,{\\i1}EXIT{\\i0}
Dialogue: 0,0:00:06.00,0:00:07.00,Default,,0,0,0,,{\\p1}m 0 0 l 100 0 100 100{\\p0}
"""


def _fake_translate(blocks):
    return [{**b, "text_lines": ["PT " + l if l else l for l in b["text_lines"]]} for b in blocks]


def test_ass_read_translate_write_keeps_styles_tags_comments(tmp_path):
    p = tmp_path / "Show.en.ass"
    p.write_text(ASS_SAMPLE, encoding="utf-8")
    doc = st.load_subtitle(str(p))
    assert doc.label == "ASS" and len(doc.blocks) == 2               # comment and drawing are not blocks
    assert doc.blocks[0]["text_lines"] == ["{\\an4\\pos(100,200)}Hello there,", "how are you?"]
    out_text = st.render_subtitle(doc, _fake_translate(doc.blocks))
    out = tmp_path / "Show.pt-BR.ass"
    st.write_subtitle_text(out_text, str(out), "utf-8")
    again = st.load_subtitle(str(out))
    assert again.blocks[0]["text_lines"] == ["PT {\\an4\\pos(100,200)}Hello there,", "PT how are you?"]
    assert again.blocks[1]["text_lines"] == ["PT {\\i1}EXIT{\\i0}"]
    assert [b["timestamp"] for b in again.blocks] == [b["timestamp"] for b in doc.blocks]
    assert "Style: Sign,Arial,20" in out_text
    assert "Comment: 0,0:00:02.00,0:00:04.00,Default,,0,0,0,,Translator note: keep this" in out_text
    assert "{\\p1}m 0 0 l 100 0 100 100{\\p0}" in out_text


def test_ass_to_srt_output(tmp_path):
    p = tmp_path / "Show.en.ass"
    p.write_text(ASS_SAMPLE, encoding="utf-8")
    doc = st.load_subtitle(str(p))
    text = st.render_subtitle(doc, _fake_translate(doc.blocks), "srt")
    blocks = st.parse_srt_text(text)
    assert len(blocks) == 2 and blocks[0]["timestamp"] == "00:00:01,000 --> 00:00:03,500"
    assert st.output_extension(doc, "srt") == ".srt" and st.output_extension(doc, "same") == ".ass"


@pytest.mark.parametrize("ext, text", [
    (".vtt", "WEBVTT\n\n00:00:01.000 --> 00:00:02.500 align:start position:10%\n<i>Hello</i> world\n\n"
             "00:00:03.000 --> 00:00:04.000\nSecond line\n"),
    (".sub", "{1}{1}23.976\n{24}{60}Hello|world\n{72}{96}Second\n"),
    (".srt", "1\n00:00:01,000 --> 00:00:02,500\nHello\nworld\n\n2\n00:00:03,000 --> 00:00:04,000\nSecond\n"),
])
def test_round_trip_formats(tmp_path, ext, text):
    p = tmp_path / f"Movie.en{ext}"
    p.write_text(text, encoding="utf-8")
    doc = st.load_subtitle(str(p))
    assert len(doc.blocks) == 2
    out = tmp_path / f"Movie.pt-BR{ext}"
    st.write_subtitle_text(st.render_subtitle(doc, doc.blocks), str(out), "utf-8")
    again = st.load_subtitle(str(out))
    assert [b["text_lines"] for b in again.blocks] == [b["text_lines"] for b in doc.blocks]
    for a, b in zip(again.blocks, doc.blocks):
        sa, ea = st.timestamp_ms(a["timestamp"])
        sb, eb = st.timestamp_ms(b["timestamp"])
        assert abs(sa - sb) <= 50 and abs(ea - eb) <= 50     # MicroDVD is frame-exact only


def test_microdvd_without_frame_rate_asks(tmp_path):
    p = tmp_path / "Movie.sub"
    p.write_text("{24}{60}Hello\n{72}{96}Second\n", encoding="utf-8")
    with pytest.raises(st.NeedsFrameRate):
        st.load_subtitle(str(p))
    doc = st.load_subtitle(str(p), fps=25)
    assert st.timestamp_ms(doc.blocks[0]["timestamp"])[0] == 960       # frame 24 at 25 fps


def test_picture_subtitles_refused(tmp_path):
    for name, data in (("Movie.sup", b"PG\x00\x00"), ("Movie.sub", b"\x00\x00\x01\xba\x44")):
        p = tmp_path / name
        p.write_bytes(data)
        with pytest.raises(st.SubtitleError, match="OCR"):
            st.load_subtitle(str(p))


# ── R1 check and repair ──────────────────────────────────────────────

BROKEN = """1
00:00:01,000 --> 00:00:03,000
First line

second part after a blank line

2
00:00:05.500 --> 00:00:04,000
Ends before it starts

2
00:00:10,000 --> 00:00:12,000
Repeated number, overlaps the next

4
00:00:11,000 --> 00:00:13,000
Overlapped

5
00:00:08,000 --> 00:00:09,000
Out of order

6
00:00:20,000 --> 00:00:20,000
Zero

7
00:00:30,00 -> 00:00:31,000
Unreadable timing
"""


def test_parser_keeps_orphan_text():
    blocks, problems = st.parse_srt_text_ex(BROKEN)
    assert blocks[0]["text_lines"] == ["First line", "second part after a blank line"]
    assert problems[0]["kind"] == "orphan_text" and problems[0]["block"] == 0
    assert len(st.parse_srt_text(BROKEN)) == 6     # the unreadable block lacks '-->' and becomes orphan text


def test_check_finds_every_kind():
    text = BROKEN.replace("7\n00:00:30,00 -> 00:00:31,000", "7\n00:00:30 --> 00:00:31")
    blocks, parse_problems = st.parse_srt_text_ex(text)
    kinds = {p["kind"] for p in st.check_subtitle(blocks, parse_problems=parse_problems)}
    assert {"orphan_text", "end_before_start", "zero_duration", "overlap", "out_of_order", "bad_number",
            "odd_format", "bad_timestamp"} <= kinds


def test_repair():
    blocks, pp = st.parse_srt_text_ex(BROKEN)
    probs = st.check_subtitle(blocks, parse_problems=pp)
    fixed, log, removed = st.repair_blocks(blocks, probs)
    times = [st.timestamp_ms(b["timestamp"]) for b in fixed]
    assert [b["id"] for b in fixed] == [str(i + 1) for i in range(len(fixed))]
    assert [s for s, _ in times] == sorted(s for s, _ in times)
    assert all(e > s for s, e in times)
    assert all(times[i][1] < times[i + 1][0] + 101 for i in range(len(times) - 1))
    assert all(st._STRICT_TS_RE.match(b["timestamp"]) for b in fixed)
    assert st.check_subtitle(fixed) == [] and log


def test_clean_sample_has_no_problems():
    blocks, pp = st.parse_srt_text_ex(SAMPLE)
    assert st.check_subtitle(blocks, parse_problems=pp) == []


def test_ad_lines_found_and_removed():
    blocks = _blocks("Hello.", "Subtitles by explosiveskull", "www.OpenSubtitles.org", "Bye.")
    blocks[1]["timestamp"] = st.make_timestamp(60_000, 61_000)
    probs = st.check_subtitle(blocks)
    assert {p["block"] for p in probs if p["kind"] == "ad_line"} == {1, 2}
    fixed, _, removed = st.repair_blocks(blocks, probs, remove_ads=True)
    assert [b["text_lines"][0] for b in fixed] == ["Hello.", "Bye."] and removed == [1, 2]
    kept, _, _ = st.repair_blocks(blocks, probs, remove_ads=False)
    assert len(kept) == 4


def test_credit_phrase_mid_film_is_not_an_ad():
    blocks = _blocks(*["Line."] * 2000)                        # 66 minutes
    blocks[1000]["text_lines"] = ["Corrected by the teacher, he smiled."]
    assert not [p for p in st.check_subtitle(blocks) if p["kind"] == "ad_line"]


# ── N1 notice ────────────────────────────────────────────────────────

def test_notice_at_start_when_there_is_room():
    blocks = st.parse_srt_text(SAMPLE)          # first dialogue at 2.145 s
    out, where = st.add_ai_notice(blocks, st.notice_text_for("pt-BR", "Claude Haiku 5.5"))
    assert where == "start" and out[0]["text_lines"] == ["Legendas traduzidas por IA (Claude Haiku 5.5)"]
    s, e = st.timestamp_ms(out[0]["timestamp"])
    assert s == 500 and e <= 2145 - 200
    assert [b["id"] for b in out] == [str(i + 1) for i in range(len(blocks) + 1)]
    assert blocks[0]["id"] == "1"                               # input not changed


def test_notice_at_end_when_no_room():
    blocks = _blocks("Hi", "There")                            # first block at 0 ms
    out, where = st.add_ai_notice(blocks, "Subtitles translated by AI (x)")
    assert where == "end" and out[-1]["text_lines"] == ["Subtitles translated by AI (x)"]
    assert st.timestamp_ms(out[-1]["timestamp"])[0] > st.timestamp_ms(blocks[-1]["timestamp"])[1]


def test_no_double_notice():
    blocks = st.parse_srt_text(SAMPLE)
    once, _ = st.add_ai_notice(blocks, st.notice_text_for("en-US", "A"))
    twice, where = st.add_ai_notice(once, st.notice_text_for("pt-BR", "B"))
    assert where is None and len(twice) == len(once)


def test_custom_notice_text():
    assert st.notice_text_for("pt-BR", "Haiku", "Tradução automática ({model})") == "Tradução automática (Haiku)"


# ── M1 small improvements ────────────────────────────────────────────

def test_recent_files(tmp_path):
    files = []
    for i in range(10):
        p = tmp_path / f"f{i}.srt"
        p.write_text("x", encoding="utf-8")
        files = st.push_recent(files, str(p))
    assert len(files) == 8 and files[0].endswith("f9.srt")
    files = st.push_recent(files, str(tmp_path / "." / "f5.srt"))
    assert files[0].endswith("f5.srt") and len(files) == 8
    (tmp_path / "f9.srt").unlink()
    assert all(not f.endswith("f9.srt") for f in st.prune_recent(files))


def test_middle_ellipsis():
    name = "Don't Let Go (2019) [1080p] [Horror].en.srt"
    short = st.middle_ellipsis(name, 30)
    assert len(short) == 30 and "…" in short and short.endswith(".en.srt") and short.startswith("Don't")
    assert st.middle_ellipsis("short.srt", 30) == "short.srt"


def test_pick_sample_middle_prefers_dialogue():
    blocks = _blocks(*(["♪ music ♪"] * 50 + ["Hello, how are you doing today my friend?"] * 60))
    assert st.pick_sample(blocks, 20, "start") == 0
    assert st.pick_sample(blocks, 20, "middle") >= 50
    assert st.pick_sample(blocks[:10], 20, "middle") == 0


def test_estimate_vs_actual_and_history():
    u = st.UsageTotals()
    u.add(_Usage(1000, 500))
    line = st.estimate_vs_actual({"total_cost": 0.01, "input_tokens": 900, "output_tokens": 400}, u, 0.015)
    assert "+50 %" in line and "~$0.0100" in line
    hist = []
    for i in range(60):
        hist = st.push_cost_history(hist, st.cost_history_entry("m", i, {}, u, 0.01))
    assert len(hist) == 50 and hist[-1]["blocks"] == 59


def test_output_encoding_choices():
    assert st.output_encoding_for("utf-8-sig", "cp1252", "ação", True) == ("utf-8-sig", "")
    assert st.output_encoding_for("utf-8", "cp1252", "ação", True) == ("utf-8", "")
    assert st.output_encoding_for("same", "cp1252", "ação", True) == ("cp1252", "")
    enc, note = st.output_encoding_for("same", "cp1252", "สวัสดี", True)
    assert enc == "utf-8-sig" and note
    assert st.output_encoding_for("same", "utf-16+bom", "x", True) == ("utf-16", "")


def test_write_srt_encodings_round_trip(tmp_path):
    blocks = st.parse_srt_text(SAMPLE)
    for enc in ("utf-8-sig", "utf-8", "cp1252", "utf-16"):
        p = tmp_path / f"o-{enc}.srt"
        st.write_srt(blocks, str(p), enc)
        raw = p.read_bytes()
        assert raw.startswith(b"\xef\xbb\xbf") == (enc == "utf-8-sig")
        assert not raw.startswith(b"\xef\xbb\xbf\xef\xbb\xbf")
        assert st.parse_srt(str(p))[0] == blocks


def test_no_old_money_format_left():
    src = pathlib.Path(st.__file__).read_text(encoding="utf-8")
    assert "< $0.01" not in src and ":.3f}" not in src
