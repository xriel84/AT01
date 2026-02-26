# JP01 → AT01: YD Priority Editing Tools Ready
# Date: 2026-02-26
# Type: HANDOFF

4 scripts on jp/contrib-edbot-tools branch, tested against
raptor-library.json (4 entries). Ready for YD testing.

YD PRIORITY ORDER:
1. edbot_transcript_search.py — search across all clip transcripts
   py -3.12 scripts\edbot_transcript_search.py --query "TERM" --manifest raptor-library.json

2. edbot_silence_detect.py — find dead air, export silence map
   py -3.12 scripts\edbot_silence_detect.py --all --manifest raptor-library.json
   Outputs: silence_map.json, optional .edl for Resolve markers

3. edbot_auto_chapter.py — split long clips into topic chapters
   py -3.12 scripts\edbot_auto_chapter.py --all --manifest raptor-library.json
   Outputs: chapters.json, optional .edl markers, optional .csv

4. edbot_smart_crop_preview.py — crop viability analysis (read-only)
   py -3.12 scripts\edbot_smart_crop_preview.py --manifest raptor-library.json
   Outputs: crop_report.json (does NOT crop — analysis only)

ALL SCRIPTS:
- Python 3.12, zero cloud deps, pure local
- Never modify source files
- Log + skip + continue on bad files
- Work with raptor-library.json schema (whisper_segments required)

TESTING:
- Tested on 4-entry raptor-library.json — all pass
- Full test needs 96-file batch transcription (jp_transcribe_all.py)
- Scripts export .edl for Resolve marker import

TO PULL:
  cd C:\AT01
  git remote add jp https://github.com/NewEccentric/JP01.git 2>$null
  git fetch jp jp/contrib-edbot-tools
  git checkout jp/jp/contrib-edbot-tools -- scripts/edbot_*.py

BLOCKED:
- Full 96-file raptor-library.json (need batch transcription run)
- AgileLens/edbot repo access for NewEccentric (still 404)
