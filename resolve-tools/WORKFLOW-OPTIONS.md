# EdBot Workflow Options -- Pick What to Try

EdBot's pipeline has modular stages. You don't have to run everything.
Pick a workflow below to test specific capabilities.

## Option A: Quick Test -- Footage Matching Only (no GPU, no Resolve)
**What it proves:** EdBot can scan a folder and group related footage
**Time:** 30 seconds
**Run:** double-click `tests/demos/demo_filename_match.ps1`

## Option B: Transcription Test (needs GPU, no Resolve)
**What it proves:** faster-whisper accurately transcribes speech with word-level timing
**Time:** ~1 min per minute of footage
**Run:** `py -3.12 resolve-tools/shot_align.py --file-a sample.mp4 --file-b sample.mp4`
(aligning a file with itself should return offset=0 with high confidence)

## Option C: Silence Removal Preview (no GPU, no Resolve)
**What it proves:** auto-editor correctly identifies and cuts silence
**Time:** ~1x realtime
**Run:** `auto-editor sample.mp4 --preview` (dry run, shows what would be cut)

## Option D: Full Resolve Pipeline (needs GPU + Resolve)
**What it proves:** End-to-end from footage to platform-ready clips
**Time:** 10-20 min depending on source length
**Run:** double-click `Run-EdBot.ps1` (after Resolve is open)

## Option E: Subtitle Generation + Burn-in (needs GPU for gen, no Resolve)
**What it proves:** Word-level captions appear correctly timed on video
**Time:** ~2 min per clip
**Run:** (scripts to be built -- Stage 7 + 8)

---

## What Next Tests Should Prove

### Test 1: footage_match.py correctly groups multi-camera recordings
- Input: folder with mixed filenames from different sessions
- Expected: groups sorted by session, no cross-contamination
- Validates: filename parsing + date proximity fallback

### Test 2: shot_align.py finds correct offset between two recordings
- Input: two recordings of the same event (different cameras)
- Expected: offset in seconds + high confidence score
- Validates: transcript matching + audio fingerprint fallback

### Test 3: Silence removal doesn't cut speech
- Input: clip with natural pauses between sentences
- Expected: silence trimmed, all speech preserved, no audio desync
- Validates: auto-editor threshold tuning

### Test 4: SmartReframe tracks speaker correctly
- Input: landscape clip with one speaker moving
- Expected: portrait crop follows speaker, no black bars
- Validates: Resolve API + Scaling=3 + SmartReframe()

### Test 5: Full pipeline produces valid platform output
- Input: raw livestream recording
- Expected: per-platform clips matching exact specs (resolution, codec, fps, duration)
- Validates: entire 8-stage chain end-to-end

---

## Social Media Production Best Practices (2026)

### What the platforms reward now
- **80% of viewers watch muted** -- subtitles are mandatory, not optional
- **Hook in first 3 seconds** -- silence removal eliminates dead intros
- **Vertical-first** -- 9:16 is default for TikTok/Reels/Shorts discovery
- **Consistency > virality** -- regular posting schedule beats one-hit attempts
- **Platform-native feels** -- each platform has different pacing expectations

### What EdBot automates
- **Clip selection:** AI finds highlight moments from hours of footage
- **Dead air removal:** auto-editor cuts silence professionally
- **Multi-platform reframing:** one source -> 5 platform-specific outputs
- **Subtitle generation:** word-level timing from faster-whisper
- **Spec compliance:** every output matches exact platform requirements

### What EdBot does NOT automate (human decisions)
- Hook writing / intro text overlay
- Music selection and timing
- Thumbnail design
- Caption copywriting for social posts
- Posting schedule and strategy
- Community engagement / replies
- A/B testing decisions
- Brand voice and tone

### Analytics tools to consider (not built yet -- future AnaBot scope)
- **TikTok Analytics API** -- views, watch time, completion rate
- **Instagram Insights API** -- reach, saves, shares
- **YouTube Analytics API** -- CTR, retention curves, subscriber conversion
- **LinkedIn Analytics** -- impressions, engagement rate, follower demographics
- **Cross-platform dashboard** -- compare performance across platforms
- **Trend detection** -- what topics/formats are gaining traction
- **Optimal posting times** -- per-platform, per-audience analysis
