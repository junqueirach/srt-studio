# Changelog

All notable changes to SRT Translator. Dates are release dates.

## v0.7.0 — 2026-10-09

Quality-control release. Claude calls now go through the official `anthropic` SDK.

### Added
- Live model list from `GET /v1/models`, newest first, with context size and price in the label; cached in the config file for offline use; ↻ button to refresh
- Live pricing parsed from Anthropic's published pricing page, refreshed once a day; `pricing.json` next to the app overrides it; built-in table as last resort
- Exact input-token count through the free `count_tokens` endpoint (↻ exact button) and the real cost of every run reported from the API usage figures
- Hearing-impaired cues (`[door slams]`, `(laughs)`, `APPLAUSE`) are translated in their original style; checkbox to keep them untouched
- Quality-control pass after every run: unchanged text, missing or empty lines, lost tags and missing names are flagged; unchanged blocks are retranslated once automatically; QC report in the Activity Log and highlighted blocks in the Comparison tab
- Preserve-names list (section 07) with **Auto-detect names** (Claude extracts people, places and institutions), automatic loading of `<file>.names.txt` next to the subtitle, and **Save next to SRT**
- **Sample** button: translates the first 20 blocks without saving and reports the real cost
- Formatting tags (`<i>`, `<b>`, `{\an8}`) protected with placeholders and restored after translation
- Output file named without the source language tag: `Movie.en.srt` becomes `Movie.pt-BR.srt`
- Comparison tab shows every block, with the two panes scrolled together
- Dependencies (`requests`, `anthropic`) installed on demand from a dialog instead of silently at import time
- Unit tests in `tests/test_core.py` (no network or API key needed)

### Changed
- Translation protocol is JSON with one entry per block and a fixed line list, enforced with the API's JSON-schema structured output; a block that still comes back with the wrong line count is re-wrapped deterministically
- Blocks are labelled with non-sequential keys (`b78`, `c15`, …) that the model must copy, so a merged or dropped block becomes a missing key that QC repairs instead of silently shifting every following block (this shift was the cause of untranslated or misplaced lines)
- Double quotes travel as a `{Q}` placeholder, which removes the JSON-escaping failures that made the model stop a batch early
- A batch whose output is cut off by the token limit is split in half and retried; a batch the model refuses or returns mostly empty is retried and then flagged
- Context file is sent by time window: only the context lines overlapping each batch (plus 8 s margin) are included, and the fixed part of the prompt uses prompt caching
- Thinking is disabled, or effort set to low, depending on what each model supports, so translation never pays for reasoning tokens
- Default model is the cheapest current one (Claude Haiku 5.5); a saved model that no longer exists falls back to it
- Batch size and worker options are compact radio rows; model selection is a drop-down

### Fixed
- Lines inside `[...]` or `(...)` were never sent for translation (hearing-impaired cues stayed in the source language)
- Lines left untranslated when the model merged or split lines inside a block
- Cut-off responses were written as success
- Cancel now stops queued batches immediately
- Mouse wheel over the right-hand tabs no longer scrolls the settings panel
- Blocks with no text are kept instead of dropped, so IDs no longer shift
- "Live pricing" in v0.6.0 only pinged the API and returned a hardcoded table
- Worker threads update the UI through a queue on the main thread
- Drag and drop never activated (since v0.6.0): the tkdnd package was never loaded into the plain `tk.Tk()` root, so the drop zones silently fell back to click-to-browse
- Engine radio indicator was invisible on the dark card; Comparison tab stayed blank until the window was resized; the two Comparison panes are now a draggable split; target-language box could show empty
- "?" button on the engine section explains how Claude API and MyMemory work

## v0.6.0 — 2026-05

- Drag-and-drop file loading for source and context files
- Output folder memory and "Same folder as source" checkbox
- Context file support (Claude API only)
- Encoding shown after load
- Estimated cost panel with hardcoded pricing

## v0.1.0 – v0.5.0

Incremental GUI releases: Claude and MyMemory engines, structure-preserving parser with encoding detection, language auto-detection, batch and parallel-worker settings, comparison and activity-log tabs, persistent settings and API key. The sources are kept in `archive/`.
