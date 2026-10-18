# Changelog

All notable changes to SRT Studio (SRT Translator until v0.8.1). Dates are release dates.

## v0.10.0 — 2026-10-18

Sync: fix the timing of a subtitle, against another subtitle, the video's audio or a track inside a video; and subtitles taken straight from MKV/MP4.

### Added
- **Sync tab** (between Names and Log, Ctrl+3; Log is now Ctrl+4). Methods on the left: **Automatic** first (to another subtitle, to the video, to a track inside a video), then **Check**, then **Fine-tune**. On the right: one sentence with the result, the key numbers (offset, speed, cuts, match, unmatched blocks), a preview of the old and new times (first, middle and last lines) and a timeline of the two
- **Sync to another subtitle** (any language: only the timing is compared). Finds the offset, the frame-rate difference (9 candidates) and **cuts** (another version of the film: a window path over the whole film, and a part with another offset is kept only when its own lines match clearly better there than at any other offset). **Uneven timing** is fixed section by section. The result: one sentence with **Fix it**, the key numbers, the preview with the reference line next to each line, and the timeline (reference / now / after). Confidence below 0.5 asks before it applies; "? Cannot tell" (another film) changes nothing. Runs in the background with progress and Cancel (2–7 s for a film)
- **Check sync** (status only): ✅ In sync · ⚠ Constant offset · ⚠ Speed drift · ⚠ Offset and drift · ⚠ Uneven timing · ⛔ Different cut · ? Cannot tell, shown on the SOURCE card ("⚠ +2.5 s vs Movie.pt.srt") with Fix…
- **Check on load** (Settings → Output → SYNC CHECK, on by default): compares a newly opened subtitle with the context file or another subtitle of the same film next to it; it only reports
- **Check a folder…**: every subtitle in a folder against the loaded one, one status table, Copy report and Save report…
- New setting `sync_check_on_load`
- **Fine-tune by hand**: **Shift** (seconds or a time, −1 s … +1 s buttons), **Frame rate** (8 presets such as 25 → 23.976, or any two rates), **Two points** (the correct time of a line near the start and one near the end: fixes offset and speed together)
- **Hints** when there is nothing to compare against: a first line unusually late or early, lines after the end of the video (probable frame-rate mismatch); **Try it** fills in Fine-tune
- **Apply** gives the loaded subtitle the new times (a translation started afterwards uses them); a second Apply goes on top; **Undo sync** brings back the times of the file. A block that would end before 0:00 is dropped and a start below 0:00 is clamped; both are listed
- **Save synced copy…** in the file's own format; ASS comments, drawings and signs move with the dialogue. Overwriting the original writes `<name>.bak` first (an older `.bak` is never replaced: `.bak2`, `.bak3`…)
- **Sync report** for every applied sync (file, method, offset and speed, blocks moved / clamped / dropped, before-and-after sample, output and backup files): **Report…** with **Copy** and **Save as .txt**; a short line in the Activity Log
- SOURCE card: **Sync** row ("not checked" / "✓ synced: +2.350 s") with a link to the Sync tab; Subtitles table: **Synced** filter
- **Sync to the video's audio** (To the video): choose the video (suggested: the one next to the subtitle) and the audio track (the subtitle's language); FFmpeg streams the audio (the **centre channel** of 5.1/7.1, where film dialogue is), webrtcvad finds the speech (an energy detector if it is missing), and the same engine finds offset, frame rate, cuts and uneven sections. The confidence comes from how clearly the best offset stands out. Speech with no subtitle for more than 60 s is listed (a scene not in the subtitle's version). The speech is cached per video. Progress, Cancel (FFmpeg is stopped at once)
- **Is the reference in sync?** With a video next to the subtitle, To another subtitle can check the reference against the audio first and warns when it is off
- **Open a video directly** (toolbar **From video…**, Open…, Recent ▾, drag and drop; decision 25): its subtitle tracks (one pass over the file) in a picker with language, title, format, flags and line count; picture tracks listed but disabled (OCR). **Load and translate** (saved next to the video), **Use as sync reference**, or **Save as file…** (ASS stays ASS). Sync method **Track in a video**. The video is never written
- **Video tools (FFmpeg) on demand**: looked for in Settings (`ffmpeg_path`), then `~/.srt_studio/tools/ffmpeg/`, then the PATH. When missing, the app offers to download an **LGPL** build (BtbN, n8.1.3, about 81 MB, pinned URL, size and SHA-256; only ffmpeg/ffprobe, their DLLs and the licence are kept; it must run before it is installed) with a progress bar and Cancel, or to choose an ffmpeg.exe. Every FFmpeg process runs without a window, at below-normal priority, with a timeout; Cancel kills it. Settings → General → VIDEO TOOLS. `srt_media.py` holds this, tested with a local server and fake processes (`tests/test_media.py`)
- `srt_sync.py`: the timing core (shift, frame-rate scale, two points, piecewise maps), pure and unit-tested (`tests/test_sync.py`)
- New dependencies: `numpy`, `webrtcvad-wheels` (offered by "Install dependencies" when running from source)

- Subtitle tracks in languages outside the translation list are named (Bulgarian, Croatian, Macedonian…), not shown as codes

### Known limits
- Against the video's audio, offset and speed are reliable; cuts, intros and inserted scenes are found only sometimes
  (speech detection also hears music and effects). For another version of the film, sync to a subtitle of that version
- Random errors of single lines (±0.15–0.3 s) are not found against a subtitle in another language: two good subtitles
  already differ by about 0.06–0.14 s per line. With a reference that shares the timing they are found and fixed

## v0.9.1 — 2026-10-16

Fixes found after v0.9.0 and a polished window.

### Fixed
- **A run that fails is no longer reported as finished.** With a rejected API key (HTTP 401) v0.9.0 saved the untranslated text under "Legendas traduzidas por IA" and said "Translation finished". Now an error that retrying cannot fix (rejected key, model not found, refused request, MyMemory daily limit) stops the run at once: **no file is written and no AI notice is added**, and a *Translation failed* message says what happened and what to do (**Open Settings** for a key problem, **Show log**). A run in which nothing was translated at all (e.g. no connection) ends the same way
- **Partial failures are counted honestly**: the finish message says "N of M translated", names the blocks kept in the source language (marked ⚑) and is titled *Translation finished with problems*
- MyMemory: no connection or the daily limit ("MYMEMORY WARNING…") is reported instead of silently keeping the source text or saving the warning as a translation
- **MyMemory AI notice** fully in the target language: "Legendas traduzidas por IA (MyMemory)" instead of "(MyMemory, machine translation)"
- The **double-arrow cursor** of the divider stayed on over the whole window after the mouse crossed the divider quickly; both sides now keep the normal arrow
- The "Install dependencies" question (running from source) has the app's name and icon and appears in front of other windows

### Added
- **About window** (Help ▾ › About, or click the logo): author, contact email, GitHub page, Reddit (r/SRTStudio), licence and what the app does; the links can be clicked (without a mail program the address is copied); **Copy** copies the version details for bug reports
- **Help ▾ menu**: Help (F1), Translation engines, Check for updates…, About
- **Check for updates**: asks GitHub for the latest release (nothing else is sent, nothing is downloaded); optional check at start, at most once a day (Settings → General → UPDATES, off by default) with a status-bar link when a newer version exists; "Skip this version"
- **Dark title bar** on the main window and the app's dialogs (Windows 10 and 11; on Windows 11 in the toolbar colour). Settings → General → WINDOW, on by default
- New settings keys: `dark_title_bar`, `check_updates`, `last_update_check`, `skipped_version`

### Changed
- **Title-bar icon** without the dark square: a transparent bubble (`assets/icon-small.ico`, 16–32 px) is used for the title bar; the taskbar, Alt+Tab and the exe keep the tile
- **Subtitles table**: before a run the Source column uses the width; when translations arrive Source and Translation share it. Column widths you set by dragging are kept until another file is opened
- The line above the block text in the strip under the table uses the app font (it was Consolas)
- The "from the middle" box next to Sample is sized from its text (it was clipped)
- Settings → General: the price override file shows its status (found / not present), a short path with the full path in the tooltip, **Open folder** and **Copy path**
- README links point to the renamed repository `junqueirach/srt-studio`; User-Agent `SRT-Studio/<version>`
- Tests: 127 → 148 (failed and partial runs with a fake client, MyMemory errors, notice text, icons, update check, column widths, About, Help menu, cursor); the window tests skip on a machine without a display (GitHub CI). GUI harness kept as `tools/gui_harness.py`

## v0.9.0 — 2026-10-15

New name, new layout and every text subtitle format. **SRT Translator is now SRT Studio.**

### Added
- **All text subtitle formats** for translation: SRT, ASS/SSA, WebVTT, MicroDVD (asks for the frame rate when the file does not declare it), SAMI, TTML, MPL2/TMP, through `pysubs2`. ASS styles, positions (`{\an4\pos(…)}`), comments and drawings are kept. Output in the same format as the source (default) or always SRT (Settings → Output). Picture subtitles (PGS `.sup`, VobSub) are refused with a clear message (they need OCR)
- **Source check and repair** on load: text without a timing line (now kept, attached to the previous block), unreadable timings, end before start, zero duration, overlaps over 100 ms, wrong order, bad numbering, non-standard timing and **ad or credit lines** ("Subtitles by …", "www.OpenSubtitles.org", "Subtitulado por …", translator credits at the start or end; extra patterns in Settings → Repair). SOURCE › Repair › **Review…** lists them; **Repair** fixes them in the app; **Save repaired copy…** writes a `.bak` first when it replaces the original. ASS files are checked only for ad lines and impossible durations (overlaps are normal there)
- **"Translated by AI" notice**: a block in the target language at the start of a full run's output (e.g. "Legendas traduzidas por IA (Claude Haiku 5.5)"), ending at least 0.2 s before the first dialogue, or at the end when there is no room; never added twice. On by default; text and seconds in Settings → Output
- **32 languages** (Thai, Russian, Ukrainian, Greek, Hebrew, Hindi, Polish, Dutch, Swedish, Norwegian, Danish, Finnish, Czech, Hungarian, Romanian, Turkish, Indonesian, Vietnamese, Chinese Traditional added). Detection by alphabet first, then by common words; "language ?" instead of a wrong guess
- **App icon** (caption bubble) for the window, the taskbar and the exe (`assets/icon.ico`, built by `tools/make_icon.py`)
- **Recent ▾** menu and recent files on the start screen (last 8)
- **Sample from the middle** (default): the 20 blocks with the busiest dialogue after the opening; "from the start" still available
- **Estimate vs actual** line in the Log after every Claude run; the last 50 runs are kept (`cost_history`) to tune the estimate later
- **Output encoding**: UTF-8 with BOM (default), UTF-8 without BOM, or the same as the source (with a safe fallback)
- **Save log…** on the Log tab (Ctrl+S)
- **Open folder** link in the status bar after a saved run
- Keyboard: Ctrl+O, Ctrl+Enter, Esc, Ctrl+1/2/3

### Changed
- **New layout** (approved mockup): slim toolbar, **adjustable divider** between the left and right sides (drag either way; both sides keep their proportion when the window is resized; double-click or Settings → General → Reset layout restores it; default left width 460 px, so long language names show in full), left column that never scrolls and never grows (Options is a summary with Edit…), one **Subtitles** table instead of Source Preview + Comparison (source and translation side by side, time on one line, filters All / Flagged / Repaired, search, detail strip), status bar with progress, last cost and Open folder. Default window 1280×800, minimum 1100×700. Sharper text on 125 %/150 % displays
- **Renamed to SRT Studio**: window title, files (`srt_studio_v0.9.0.py`, `SRT Studio.bat`), settings file `~/.srt_studio_config.json`. The SRT Translator settings are imported once on the first start; the old file is kept unchanged
- Settings dialog has pages: General, Output, Repair, Files
- Engine is chosen in a Provider drop-down (ready for more providers)
- Drag and drop works on the whole start screen, the source card and the table; `tkinterdnd2` is now a normal requirement. Without it, the start screen says "Open a subtitle" instead of "Drop"
- Cost amounts use one format everywhere (`~$0.0185`)

### Fixed
- **Times with a leading zero in the milliseconds were misread** (`,048` was read as 480 ms). This affected which context lines were sent with each batch; it would have broken repair and sync
- **Text after a blank line inside a block was silently dropped** by the SRT parser; it is now kept and reported
- MicroDVD files that declare their frame rate lost their first line

## v0.8.1 — 2026-10-15

Fix release. The translation engine and the layout are unchanged.

### Added
- **"Translation finished" message** after a saved translation: file and folder, blocks and flags, structure check, the real cost of the run next to the estimate, the **total for this subtitle** (run + sample runs + name detection) and where the prices came from (live page, cache, `pricing.json`, or the built-in table with an "may be out of date" warning). Buttons: Open folder, Show flagged blocks, OK. Settings → new **OUTPUT** section: "Show a message when a translation finishes" (on by default)
- Sample and cancelled runs show their cost in the status line ("Sample done — 20 blocks · cost $0.0031", "Cancelled — cost so far $0.0042")
- Model drop-down tooltip with the full model details

### Changed
- **Names belong to one subtitle.** The list starts empty; loading a different subtitle clears it and loads that file's `.names.txt`. If the list holds names that are not saved, the app asks first (Yes saves them next to the old subtitle, No discards them, Cancel keeps the old subtitle). A run never clears the list. The settings file now stores the list together with its file and restores it only for that file; the v0.8.0 list is not carried over
- Shorter model labels: `Claude Haiku 5.5 · $0.10/$0.50 · 1M ★` (fits the column; "recommended" is no longer cut off)
- Loading another subtitle is refused while a translation runs
- `tests/test_core.py` finds the app by version number (v0.10.0 sorts after v0.9.0) and accepts both `srt_translator_v*.py` and `srt_translator_gui_v*.py`
- `SRT Translator.bat` starts the highest-version app file in its own folder, never a helper module or simply the newest `.py`

### Fixed
- **Subtitles saved as UTF-16 or UTF-32 did not load** ("No subtitle blocks found in file"). Windows Notepad's "Unicode" and many downloaded subtitles use UTF-16; the app tried only UTF-8 and Western codepages and mis-read every character. Byte-order marks (UTF-8, UTF-16 LE/BE, UTF-32) are now checked first, UTF-16 without a mark is recognised, and a decoding that produces NUL characters is rejected. The "no subtitles found" message now says which encoding was tried. The output is still UTF-8 with BOM
- **A failed save was reported as "Done"** and the cost of that run was never shown. Now the status says "Not saved — <reason>", a message shows the reason and the cost, and **Save as…** saves the translation somewhere else
- The cost of **Auto-detect names** and of **Sample** runs was never added up; the finish message now shows the total for the subtitle
- The cost of a cancelled run was not reported
- **Settings could be lost**: the settings file was rewritten without a lock from the main thread and from the catalog refresh thread, and an unreadable file silently reset every setting (API key included). Writes are now locked and atomic (temp file, then replace); an unreadable file is kept as `.srt_translator_config.json.corrupt-<date-time>` and the Activity Log says so. `config_version: 2` is stored
- **Subtitles are written atomically** (temp file, then replace), so a crash or a full disk never leaves half a subtitle
- Built-in price table re-checked against the official pricing page: Sonnet 5.5 cache read is $0.10 (was $0.20)
- Settings dialog: the Close button no longer gets cut off when file paths wrap

## v0.8.0 — 2026-10-09

GUI redesign. Parsing, translation, quality control, pricing and catalog code are unchanged; `tests/test_core.py` passes unchanged.

### Changed
- One-screen layout: three headings (FILE, LANGUAGES, ENGINE) and a collapsible **Advanced** section (batch size, workers, cue checkbox, save-next-to-source). Nothing scrolls at the default 1000×700 window, even with Advanced open
- Fixed action bar at the bottom of the column: estimated cost (with ↻ exact), Start, Sample, Cancel and the progress bar are always visible
- Source and target languages side by side with a ⇄ swap button
- Engine is a two-way toggle (Claude API ★ | MyMemory (free)); the model drop-down and its ⟳ sit beside it and are greyed out for MyMemory
- Batch size and workers are spin boxes (5–60 and 1–8) instead of fixed radio choices; the auto-suggested batch size still fills in on load
- Context file is a compact row under the file box ("Context: none  + add")
- Settings dialog (⚙ in the header): API key, model/price catalog status with Refresh, pricing.json path, settings file path, last output folder, link to the console
- Preserve-names list moved to a **Names** tab in the right panel with full height, Auto-detect, Load from file, Save next to SRT, Clear and a count in the tab title
- Hint paragraphs replaced by hover tooltips; the status line at the bottom says the next step ("Load a .srt file", "Check the estimate, then press Start", "Translating… batch 12/23", "Done — 3 blocks flagged")
- The 01–07 section badges are gone
- Window size and position, and the Advanced open/closed state, are remembered

### Fixed
- Mouse wheel over the settings column no longer changes the drop-down or spin box under the pointer
- All settings are read on the main thread before a run starts and handed to the worker (Tk variables are no longer read from the worker thread)

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
