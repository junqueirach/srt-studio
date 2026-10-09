"""Unit tests for the pure (non-GUI, non-network) parts of srt_translator.py.

Run:  python -m pytest tests -v
They need neither an API key nor the anthropic/requests packages.
"""
import importlib.util
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load_module():
    # The repo file is srt_translator.py; the dev folder keeps a versioned name.
    candidates = [ROOT / "srt_translator.py"] + sorted(ROOT.glob("srt_translator_gui_v*.py"), reverse=True)
    for path in candidates:
        if path.exists():
            spec = importlib.util.spec_from_file_location("srt_translator", path)
            mod = importlib.util.module_from_spec(spec)
            sys.modules["srt_translator"] = mod
            spec.loader.exec_module(mod)
            return mod
    raise FileNotFoundError("srt_translator.py not found")


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
