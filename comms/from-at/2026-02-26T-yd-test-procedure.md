---
from: AriBot
to: YD
date: 2026-02-26
re: EdBot Tool Testing — YD Priority Tests
---

# EdBot Tool Testing — YD Priority Tests

Pre-screened by Ari. Run in order. Each test has PASS/FAIL criteria.

**Server:** `http://127.0.0.1:8901`
**Start server:** `py -3.12 C:\AT01\agents\edbot\server.py`
**Viewer:** Open `http://127.0.0.1:8901/` in browser (serves viewer_v2.html)

**Test video:** Use a video file accessible from one of these directories:
- `C:\AT01\input\`
- `C:\AT01\output\`
- `C:\AT01\temp\`

Place your test video (e.g., `IMG_5769.MOV`) in `C:\AT01\input\` before starting.
Replace `VIDEO_PATH` in all curl commands below with the full path (e.g., `C:\\AT01\\input\\IMG_5769.MOV`).

---

## PRIORITY 1: SEARCH TRANSCRIPTS

Estimated time: 10 minutes

### Test 1A — Transcribe a video

```powershell
curl -X POST http://127.0.0.1:8901/api/transcribe `
  -H "Content-Type: application/json" `
  -d '{\"input_path\": \"VIDEO_PATH\", \"output_dir\": \"output\"}'
```

**What to check:**
- Response returns JSON with `chunks` array
- Each chunk has: `id`, `text`, `start`, `end`, `duration`
- Text content matches spoken words in video
- Timestamps are in seconds, monotonically increasing

**PASS:** Chunks returned, text is accurate, timestamps align with audio.
**FAIL:** Empty chunks, garbled text, or request errors out.

### Test 1B — Search for a word that exists

After transcribing, pick a word you heard in the video and search for it:

```powershell
curl -X POST http://127.0.0.1:8901/api/search-transcripts `
  -H "Content-Type: application/json" `
  -d '{\"query\": \"WORD_FROM_TRANSCRIPT\", \"max_results\": 20}'
```

**What to check:**
- Response returns matches with video path, chunk text, timestamps
- Searched word appears in the matched text
- Timestamps point to correct moment in video

**In viewer:** After transcribing, use the search box in viewer_v2.html. Type the same word. Results should appear with clickable timestamps. Clicking a result should jump the video to that position.

**PASS:** Results returned with correct timestamps; clicking jumps to right position in viewer.
**FAIL:** No results for a word that was clearly spoken, or timestamps are wrong.

### Test 1C — Search for a word that does NOT exist

```powershell
curl -X POST http://127.0.0.1:8901/api/search-transcripts `
  -H "Content-Type: application/json" `
  -d '{\"query\": \"xyzzyplugh\", \"max_results\": 20}'
```

**PASS:** Empty results array returned (no false positives).
**FAIL:** Results returned for a nonsense word.

### Test 1D — Search for a partial phrase

Pick a 2-3 word phrase from the transcript:

```powershell
curl -X POST http://127.0.0.1:8901/api/search-transcripts `
  -H "Content-Type: application/json" `
  -d '{\"query\": \"PARTIAL_PHRASE\", \"max_results\": 20}'
```

**PASS:** Matches returned containing the phrase or close semantic match.
**FAIL:** No matches for a phrase clearly present in transcript.

---

## PRIORITY 2: SILENCE DETECTION

Estimated time: 10 minutes

### Test 2A — Detect silence in video

```powershell
curl -X POST http://127.0.0.1:8901/api/silence `
  -H "Content-Type: application/json" `
  -d '{\"input_path\": \"VIDEO_PATH\", \"output_dir\": \"output\"}'
```

**What to check:**
- Response returns JSON with silence map (array of silent segments)
- Each segment has `start` and `end` timestamps
- Silent segments correspond to actual pauses in the video
- No segment overlaps with clearly spoken audio

**PASS:** Silence map returned with plausible segments matching actual pauses.
**FAIL:** No segments detected, or segments cover speech regions.

### Test 2B — Verify silence map via API

```powershell
curl http://127.0.0.1:8901/api/silence_map
```

**What to check:**
- Returns the cached silence map from Test 2A
- Same data as the original response

**PASS:** Cached silence map matches original detection results.
**FAIL:** Empty response or different data than Test 2A.

### Test 2C — Compare input vs output duration

If silence removal produces output, check:
- Output video is shorter than input
- No speech is cut off in the output
- Transitions between kept segments are clean (no audio pops/glitches)

**PASS:** Output shorter than input, speech intact, clean transitions.
**FAIL:** Output same length, speech cut off, or audio artifacts.

---

## PRIORITY 3: AUTO CHAPTER

Estimated time: 10 minutes

### Test 3A — Generate chapters

Requires transcription to be cached first (run Priority 1 tests first).

```powershell
curl -X POST http://127.0.0.1:8901/api/auto-chapter `
  -H "Content-Type: application/json" `
  -d '{\"video_path\": \"VIDEO_PATH\"}'
```

**What to check:**
- Response returns array of chapters
- Each chapter has: title, summary, start timestamp, end timestamp
- Titles are descriptive (not generic like "Chapter 1")
- Summaries reflect actual content of that section

**PASS:** Chapters returned with meaningful titles, summaries, and timestamps that align with topic changes.
**FAIL:** No chapters, generic titles, or timestamps that don't match content shifts.

### Test 3B — Verify chapter structure

```powershell
curl http://127.0.0.1:8901/api/chapters
```

**What to check:**
- Chapters cover the full video duration (first chapter starts near 0, last chapter ends near video end)
- No chapter is shorter than 30 seconds (except possibly the last one)
- Chapters don't overlap
- Chapter boundaries align with natural topic transitions

**PASS:** Full coverage, no overlap, minimum 30s duration, boundaries at topic shifts.
**FAIL:** Gaps in coverage, overlapping chapters, or very short chapters in the middle.

### Test 3C — Long-form test (if second video available)

If you have a longer video (10+ minutes), repeat Tests 3A-3B. Longer content should produce more chapters with more distinct topics.

**PASS:** More chapters than the short video, each with distinct topics.
**FAIL:** Same number of chapters regardless of length, or topics repeat.

---

## PRIORITY 4: SMART CROP (Conditional)

**Only run if Priorities 1-3 pass cleanly.**

Estimated time: 15 minutes

### Test 4A — Portrait crop to 9:16

```powershell
curl -X POST http://127.0.0.1:8901/api/portrait_crop `
  -H "Content-Type: application/json" `
  -d '{\"input_path\": \"VIDEO_PATH\", \"output_dir\": \"output\", \"method\": \"face\"}'
```

**What to check:**
- Output video exists in `C:\AT01\output\`
- Output aspect ratio is 9:16 (portrait)
- Face/subject is centered in frame throughout
- No black bars or stretched content

**PASS:** 9:16 output with subject centered, no visual artifacts.
**FAIL:** Wrong aspect ratio, subject cut off, or processing error.

### Test 4B — Verify face tracking

Play the output from Test 4A:
- Subject's face should stay centered or near-center throughout
- When subject moves, the crop should follow smoothly
- No jarring jumps or sudden repositions
- If multiple people, the primary speaker should be tracked

**PASS:** Face stays in frame, smooth tracking, no jarring jumps.
**FAIL:** Face leaves frame, tracking jumps erratically, or wrong person tracked.

### Test 4C — Compare center vs face crop

```powershell
curl -X POST http://127.0.0.1:8901/api/portrait_crop `
  -H "Content-Type: application/json" `
  -d '{\"input_path\": \"VIDEO_PATH\", \"output_dir\": \"output\", \"method\": \"center\"}'
```

Compare the `center` crop output with the `face` crop from Test 4A. The `face` method should keep the subject better framed when they're not centered in the original.

**PASS:** Face method visibly outperforms center method when subject is off-center.
**FAIL:** No visible difference, or face method produces worse framing.

---

## DEPRIORITIZED (skip unless time permits)

- **Auto-name** (`/api/auto-name`) — batch file renaming from transcripts
- **Shot matcher** (`/api/match-shots`) — cross-video similarity matching

These are lower-priority and can wait for a future test round.

---

## FEEDBACK FORMAT

Write results to: `comms/from-yd/2026-02-26T-test-results.md` on the `AL` branch.

Format per test:

```
### Test [NUMBER] — [NAME]
**Result:** PASS / FAIL
**Notes:** [What you observed, any unexpected behavior]
**Timestamp:** [When you ran the test]
```

Include at the top:
- Machine/OS you tested on
- Server start time
- Video file used (name + duration)

Push to `AL` branch when complete. AT will fetch and review.
