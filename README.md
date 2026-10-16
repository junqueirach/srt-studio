# SRT Studio

**Translate and repair subtitle files (SRT, ASS, WebVTT and more) while keeping timing and structure intact.**
Formerly *SRT Translator* (renamed in v0.9.0).

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE) ![Python](https://img.shields.io/badge/Python-3.9%2B-blue) [![CI](https://github.com/junqueirach/srt-studio/actions/workflows/ci.yml/badge.svg)](https://github.com/junqueirach/srt-studio/actions/workflows/ci.yml) ![Version](https://img.shields.io/badge/version-0.9.1-brightgreen)

<p align="center"><img src="docs/screenshots/srt-studio.png" alt="SRT Studio screenshot" width="900"></p>

**Download for Windows:** the current Windows build is v0.9.0: [`SRT-Studio-0.9.0-win64.zip`](https://github.com/junqueirach/srt-studio/releases/download/v0.9.0/SRT-Studio-0.9.0-win64.zip) (about 26 MB). v0.9.1 is a source-only release (run it with Python, see Quick start); the next Windows build comes with v0.10.0. Unzip it, open the `SRT Studio` folder and double-click `SRT Studio.exe`. No Python needed. The SHA-256 checksum is in the [v0.9.0 release notes](https://github.com/junqueirach/srt-studio/releases/tag/v0.9.0). For the Claude engine you need your own API key (see Quick start).

> **Windows SmartScreen:** the file is not code-signed, so Windows may show "Windows protected your PC". Click **More info**, then **Run anyway**. You can also run the app from source (see Quick start) and read every line of the code first.

## How it works

<p align="center"><img src="docs/screenshots/how-it-works.png" alt="How SRT Studio works" width="900"></p>

1. Open a subtitle (**Open…**, Ctrl+O, **Recent ▾**, or drop it on the window). Format, encoding, language and block count are shown as small labels, and the file is checked for problems.
2. If the **Repair** line shows problems, **Review…** lists them and **Repair** fixes them in the app.
3. Pick the target language, the provider and, for Claude, the model. Check the cost estimate; optionally run a 20-block **Sample** (from the busiest dialogue in the middle, or from the start).
4. Press **Start**. Blocks are translated in parallel batches, checked, repaired if needed and saved as `Movie.pt-BR.srt` (or `.ass`, `.vtt`… in the source's own format). A finish message shows the real cost.

## What it does

- **Every text subtitle format**: SRT, ASS/SSA (styles, positions and comments kept), WebVTT, MicroDVD, SAMI, TTML, MPL2/TMP. Output in the same format or always SRT. Picture subtitles (PGS `.sup`, VobSub) need OCR and are not supported
- **Source check and repair**: text without a timing line (kept, never dropped), unreadable or reversed timings, zero durations, overlaps, wrong order, bad numbering, and ad or credit lines such as "Subtitles by … www.OpenSubtitles.org". Repair works in memory; *Save repaired copy…* writes a `.bak` first when it replaces the original
- **"Translated by AI" notice**: a short block in the target language at the start of the output (on by default, text and duration configurable)
- **32 languages**, detected by alphabet first (Thai, Cyrillic, Greek, Hebrew, Arabic, Devanagari, Hangul, Kana, Han) and then by common words; "language ?" instead of a wrong guess
- Two engines: **Claude** (best quality, bring your own key) and **MyMemory** (free, for testing)
- **Structure-preserving**: timings and line counts are never touched, only text is translated, and the saved file is read back and verified
- **Live model list and live pricing** from Anthropic, cached for offline use, plus a local `pricing.json` override
- **Real cost** of every run from the API usage, next to the estimate, with the total for the subtitle (runs, samples, name detection)
- **Hearing-impaired cues**, **name preservation** (with auto-detect), optional **context file** (same film in another language)
- Output encoding: UTF-8 with BOM (default), UTF-8 without BOM, or the same as the source

## Quick start

```
python srt_studio.py
```

The first run offers to install the packages the app needs if they are missing (`requests`, `anthropic`, `pysubs2` for formats other than SRT, `tkinterdnd2` for drag and drop). Or install them yourself:

```
pip install -r requirements.txt
```

For the Claude engine you need an API key from [console.anthropic.com](https://console.anthropic.com). Enter it in **⚙ Settings** or set the `ANTHROPIC_API_KEY` environment variable. The key is kept in `~/.srt_studio_config.json`, outside this repository, and is sent only to `api.anthropic.com`. On the first start after the rename, the settings of SRT Translator (`~/.srt_translator_config.json`) are imported once; the old file is left as it was.

## The window

| Part | What it does |
|---|---|
| Toolbar | **Open…**, **Recent ▾** (last 8 files), **⚙ Settings**, **Help ▾** (Help, Translation engines, Check for updates…, About). Click the logo for **About** (author, contact, GitHub, Reddit, licence). |
| Left side | **SOURCE**: file name, format / encoding / blocks / language labels, **Repair** status with **Review…**, optional **Context** file. **LANGUAGES**: source (detected) and target, ⇄ swaps them. **ENGINE**: provider and model (★ = the cheapest current model; hover for details). **OPTIONS**: a one-line summary with **Edit…** (batch size, workers, cues, save next to source, AI notice, sample from). At the bottom: estimated cost (**↻ exact** counts the real input tokens), **Start**, **Sample** and **Cancel**. |
| Divider | Drag it to make either side wider. When the window is resized, both sides keep their proportion. Double-click it, or Settings → General → Reset layout, to go back to the default. |
| Subtitles tab | One row per block: number, time, source, translation (filled during the run), ⚑ flag. Show *All / Flagged / Repaired*, search text or a number; the strip below shows the selected block in full. |
| Names tab | One name per line; **Auto-detect names** (Claude); a `Movie.names.txt` next to the subtitle is loaded automatically. The list belongs to one subtitle: loading another file clears it, after asking to save names that are not saved yet. |
| Log tab | Batch progress, quality-control report, repair log, real cost and "estimate vs actual". **Save log…** writes it to a text file. |
| Status bar | What is happening, the progress bar, the last cost, and **Open folder** after a saved run. |
| Finish message | The saved file, flagged blocks, structure check, the cost of the run next to the estimate, the total for this subtitle and where the prices came from. If saving fails, it says why, shows the cost and offers **Save as…**. Can be turned off in Settings → Output. |
| Failure message | When a run cannot work (API key rejected, model not found, no connection, MyMemory daily limit) it stops at once: **no file is written and no AI notice is added**, and a *Translation failed* message says what happened and what to do. When only some batches fail, the file is saved and the message counts only the blocks that really changed; the others are named and marked ⚑. |
| Settings | **General**: API key, models and prices, the optional `pricing.json` (found / not present, Open folder), reset layout, dark title bar, check for updates at start (off by default). **Output**: finish message, output format, encoding, AI notice. **Repair**: remove ad and credit lines, extra patterns. **Files**: where the settings file is. |
| Keyboard | Ctrl+O open · Ctrl+Enter start · Esc cancel · Ctrl+1/2/3 tabs · Ctrl+S save the log (Log tab) · F1 Help. |

## Quality control

After every run each block is compared with its source:

- text identical to the source (likely untranslated)
- missing or empty lines, lost formatting tags
- names from the preserve list that disappeared

Blocks with these problems are sent back to Claude once, in small groups. Whatever remains is listed in the Log and marked ⚑ in the Subtitles tab. A batch whose output was cut off by the token limit is split in half and retried automatically.

## Models and pricing

The app does not hardcode the model list. On start, and whenever you press ↻, it reads `GET /v1/models` and shows every current Claude model with its context size. The list is cached in the settings file so the app also opens offline.

Prices are resolved in this order:

1. `pricing.json` next to the app, if present (see `pricing.example.json`)
2. the official pricing page, downloaded once a day and cached
3. a built-in table, used only when both fail (the finish message then says the price may be out of date)

`pricing.json` format, prices in dollars per million tokens, keys are model family and version:

```json
{
  "haiku 5.5":  {"input": 0.10, "output": 0.50},
  "sonnet 5.5": {"input": 2.00, "output": 10.00}
}
```

Typical cost, measured on a 903-block, 90-minute documentary translated to Brazilian Portuguese with Claude Haiku 5.5: about two cents. Thinking is turned off, or effort set to low, on every model so no reasoning tokens are billed.

## Hearing-impaired subtitles

Cue lines written as `[door slams]`, `(laughs)` or `APPLAUSE` are translated and keep their bracket or capital style. Untick *Translate hearing-impaired cues* (Options) to leave them untouched. Lines made only of punctuation, numbers or music notes are never sent for translation.

## Development

```
pip install -r requirements.txt pytest
python -m pytest tests -v
python tools/make_icon.py        # rebuilds assets/icon.ico and icon-small.ico from the drawing (needs Pillow)
```

`tests/test_core.py` covers parsing (all formats), repair, the AI notice, language detection, naming, cues, tags, the glossary, the pricing parser, the cost estimate and ledger, the batch protocol with a fake client, and quality control. No API key or network is needed.

## Project facts

- Built in small steps, from a command-line script (`archive/versions/srt_translator R0 (no GUI).py`) to the GUI in v0.6.0, the quality-control release v0.7.0, the one-screen redesign in v0.8.0, the fixes in v0.8.1, in v0.9.0 the new name, layout and icon, all text subtitle formats, source repair and the AI notice, and in v0.9.1 honest failure reports, the About window and a polished window
- About 5,400 lines of Python in one file (`srt_studio.py`), 148 automated tests, 13 versions (the 12 earlier files are in `archive/versions/`)
- `web-prototype/` holds an early React version of the interface
- Changes per version are in [CHANGELOG.md](CHANGELOG.md)
- Planned next (v0.10.0): subtitle sync with AI support. Not in this version; FFmpeg is not used yet

---

## Community and contact

- **Reddit:** [r/SRTStudio](https://www.reddit.com/r/SRTStudio/) — questions, ideas, show your results
- **Bugs and requests:** [GitHub issues](https://github.com/junqueirach/srt-studio/issues)
- **Email:** junqueira.ch@gmail.com
- **New versions:** [Releases](https://github.com/junqueirach/srt-studio/releases) (the app can check for you: Help ▾ › Check for updates…)

The same links are in the app under Help ▾ › About SRT Studio.

## How this was built

Built with **Claude (Anthropic)** as the coding partner. I wrote the requirements and the revision prompts, tested every build on real data, and decided what to fix next. The `archive/versions/` folder keeps every earlier release so the iteration history is visible.

**Security note:** the app stores any API keys you enter in a local settings file outside this repository. `.gitignore` excludes config and settings files so keys are never committed.

## Contributing and security

See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md). Bug reports and ideas are welcome through the issue templates.

## Licence

MIT. See [LICENSE](LICENSE).

## Author

Luiz Junqueira - [junqueira.ch](https://www.junqueira.ch) - [LinkedIn](https://www.linkedin.com/in/luizjunqueira/)
