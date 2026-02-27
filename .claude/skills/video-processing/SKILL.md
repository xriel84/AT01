---
name: video-processing
description: GPU-aware video transcription, FFmpeg operations, speaker diarization, and media pipeline tasks on RTX A6000. Use this skill when the user asks about transcription speed, audio extraction, video probing, silence detection, speaker identification, portrait cropping, multi-cam sync, or any faster-whisper/FFmpeg/pyannote operation. Also trigger on VRAM questions, GPU config, fallback chains, or "why is transcription slow".
---

# Video Processing Pipeline — RTX A6000

## Hardware
- GPU: RTX A6000 48GB VRAM (46.4GB usable)
- CPU: sufficient for MediaPipe face mesh (CPU-only on desktop Python)
- Storage: local NVMe

## GPU-Aware Transcription (faster-whisper)

### Fallback Chain (S12 pattern)
```
float16 (fastest, needs ≥6GB free VRAM)
  → int8 (if float16 OOM or Resolve consuming VRAM)
    → medium model + int8 (if large model fails)
      → small model + cpu (last resort, 3-5x slower)
```

### gpu_check.py Logic
1. Detect VRAM via `torch.cuda.get_device_properties(0).total_mem`
2. Check if Resolve is running (consumes 2-4GB VRAM)
3. Recommend compute_type based on free VRAM:
   - ≥8GB free → float16 + large-v2
   - 4-8GB free → int8 + large-v2
   - 2-4GB free → int8 + medium
   - <2GB free → cpu + small

### Audio Chunking (files >3 min)
- Split into 90-second chunks with 5-second overlap
- Transcribe each chunk independently
- Merge results, dedup overlapping segments by timestamp
- Short files (<2 min): process whole, no chunking

### Speed Targets
| File Length | Target | Model | Compute |
|-------------|--------|-------|---------|
| 30s clip | <5s | large-v2 | float16 |
| 2 min | <10s | large-v2 | float16 |
| 7 min | <30s | large-v2 | float16+chunking |
| 1 hour | <5 min | large-v2 | float16+chunking |

## FFmpeg Patterns

### Audio Extraction (pre-transcription)
```powershell
ffmpeg -i input.mp4 -vn -acodec pcm_s16le -ar 16000 -ac 1 output.wav
```

### Video Probe
```powershell
ffprobe -v quiet -print_format json -show_format -show_streams input.mp4
```

### Portrait Crop (9:16 from 16:9)
```powershell
# Center crop: extract 9:16 from center of 16:9
ffmpeg -i input.mp4 -vf "crop=ih*9/16:ih" -c:a copy output_portrait.mp4
# Face-tracked crop: use YOLO11 detection → dynamic crop coordinates
```

### Silence Detection
```powershell
ffmpeg -i input.mp4 -af silencedetect=noise=-30dB:d=0.5 -f null - 2>&1
# Parse: silence_start, silence_end, silence_duration
```

### TikTok Chunking
```powershell
# Split at chapter boundaries or every 60s
ffmpeg -i input.mp4 -ss {start} -t 60 -c copy chunk_{n}.mp4
```

## Speaker Diarization (pyannote-audio)

### Pipeline
```python
from pyannote.audio import Pipeline
pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1",
    use_auth_token="HF_TOKEN")
diarization = pipeline("audio.wav")
# Returns: speaker turns with start/end timestamps
```
- VRAM: 2-4GB
- Speed: ~30-45s per hour of audio
- Overlap detection: `diarization.get_overlap()`

### Energy-Based Fallback (no GPU)
When pyannote unavailable:
- RMS energy per frame → voice activity detection
- Simple clustering by energy patterns
- Less accurate but zero-dependency

## Person Detection (YOLO11)

```python
from ultralytics import YOLO
model = YOLO("yolo11n.pt")  # nano: 180-220 FPS at 1080p
results = model(frame)
# Person bounding boxes + 17 keypoints
```
- VRAM: <1GB
- Use for: portrait crop tracking, person-on-screen detection

## Multi-Cam Audio Sync

```python
from scipy import signal
import numpy as np, librosa

def find_offset(ref_path, target_path, sr=16000):
    y1, _ = librosa.load(ref_path, sr=sr)
    y2, _ = librosa.load(target_path, sr=sr)
    corr = signal.correlate(y1, y2, mode='full', method='fft')
    lag = np.argmax(np.abs(corr)) - len(y2) + 1
    return lag / sr  # offset in seconds
```

## VRAM Budget (sequential loading)

| Stage | Tool | VRAM | Time (1hr video) |
|-------|------|------|-------------------|
| Audio extract | FFmpeg | 0 | ~10s |
| Multi-cam sync | scipy | 0 | ~5-10s |
| Diarization | pyannote | 2-4GB | ~30-45s |
| Transcription | faster-whisper large-v2 | 6-8GB | ~1-2 min |
| Person detection | YOLO11 | <1GB | variable |
| Scene detection | PySceneDetect+TransNetV2 | <1GB | ~30s |
| Content analysis | Qwen2.5-VL-7B | ~18GB | ~5-10 min |
| **Peak** | | **~23GB** | **~10-15 min** |
