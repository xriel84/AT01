---
name: ffmpeg-media-ops
description: FFmpeg video/audio processing via ffmpeg-python wrapper. Format conversion, trimming, silence detection, audio extraction, overlay, subtitle burn, concatenation, codec selection, hardware acceleration. Triggers on encoding, extracting, filter chains, silence removal, format conversion, media processing. Never use raw subprocess.
---

# FFmpeg Media Operations

## Wrapper
- ALWAYS use `ffmpeg-python`, NEVER raw subprocess
- Import: `import ffmpeg`
- Probe: `ffmpeg.probe(path)` for metadata before any processing

## Common Patterns
```python
# Probe first
probe = ffmpeg.probe(input_path)
# Build pipeline
stream = ffmpeg.input(input_path)
stream = stream.filter('scale', 1080, -1)
stream = ffmpeg.output(stream, output_path, vcodec='libx264', preset='medium')
stream.overwrite_output().run()
# Verify output
assert os.path.exists(output_path) and os.path.getsize(output_path) > 0
```

## Hardware Acceleration
`.global_args('-hwaccel', 'cuda')` when A6000 available

## Codec Selection
- Video: libx264 (compatibility) or libx265 (size). ultrafast for preview, slow for production.
- Audio: aac for MP4, libopus for WebM, copy when no re-encode needed

## Silence Detection
- Use `silencedetect` filter → parse stderr for timestamps
- Parameters: silence_thresh (dB), silence_duration (seconds)
