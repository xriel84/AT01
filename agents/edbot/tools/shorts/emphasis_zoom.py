"""EdBot emphasis zoom -- librosa audio energy -> zoom keyframe suggestions.

Detects loud/emphatic speech moments for "punch zoom" effect.
Filters for meaningful emphasis only -- not every loud moment.
"""

import json
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import librosa
import numpy as np

logger = logging.getLogger(__name__)


def detect_emphasis_points(
    video_path: str,
    output_dir: str = "temp",
    energy_threshold_percentile: float = 85.0,
    min_gap_seconds: float = 3.0,
    min_duration: float = 0.3,
    max_duration: float = 1.5,
) -> dict[str, Any]:
    """Detect emphasis points from audio energy analysis.

    Parameters
    ----------
    video_path : str
        Path to source video.
    output_dir : str
        Directory for output JSON.
    energy_threshold_percentile : float
        Percentile threshold for RMS energy peaks (0-100).
    min_gap_seconds : float
        Minimum gap between consecutive emphasis points.
    min_duration : float
        Minimum zoom duration for each emphasis point.
    max_duration : float
        Maximum zoom duration.

    Returns
    -------
    dict
        Emphasis keyframes with timestamps and zoom suggestions.
    """
    vpath = Path(video_path)
    if not vpath.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    # Extract audio to temp WAV
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    wav_path = out_dir / f"{vpath.stem}_audio.wav"

    cmd = [
        "ffmpeg", "-i", str(vpath),
        "-ar", "16000", "-ac", "1",
        "-y", str(wav_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(f"Audio extraction failed: {proc.stderr[:200]}")

    # Load audio
    audio, sr = librosa.load(str(wav_path), sr=16000)
    audio_duration = len(audio) / sr

    # Compute RMS energy
    hop_length = 512
    rms = librosa.feature.rms(y=audio, hop_length=hop_length)[0]

    if len(rms) == 0:
        return {
            "source": vpath.name,
            "audio_duration": round(audio_duration, 2),
            "emphasis_count": 0,
            "keyframes": [],
        }

    # Find peaks above threshold
    threshold = float(np.percentile(rms, energy_threshold_percentile))
    max_rms = float(np.max(rms))

    if max_rms < 1e-6:
        # Effectively silent
        return {
            "source": vpath.name,
            "audio_duration": round(audio_duration, 2),
            "emphasis_count": 0,
            "keyframes": [],
        }

    # Find frames above threshold
    peak_indices = []
    for i in range(len(rms)):
        if rms[i] >= threshold:
            peak_indices.append(i)

    # Group consecutive peaks and find local maxima
    peak_groups: list[int] = []
    if peak_indices:
        group_start = peak_indices[0]
        group_max_idx = peak_indices[0]
        group_max_val = rms[peak_indices[0]]

        for i in range(1, len(peak_indices)):
            if peak_indices[i] - peak_indices[i - 1] <= 3:
                # Consecutive -- check if this is the group max
                if rms[peak_indices[i]] > group_max_val:
                    group_max_idx = peak_indices[i]
                    group_max_val = rms[peak_indices[i]]
            else:
                peak_groups.append(group_max_idx)
                group_start = peak_indices[i]
                group_max_idx = peak_indices[i]
                group_max_val = rms[peak_indices[i]]

        peak_groups.append(group_max_idx)

    # Filter by minimum gap
    keyframes: list[dict[str, Any]] = []
    last_timestamp = -min_gap_seconds

    for peak_idx in peak_groups:
        timestamp = peak_idx * hop_length / sr
        if timestamp - last_timestamp < min_gap_seconds:
            continue

        energy_level = round(float(rms[peak_idx]) / max_rms, 3)
        zoom_factor = round(1.1 + 0.2 * energy_level, 2)
        duration = round(
            min_duration + (max_duration - min_duration) * energy_level, 2
        )

        keyframes.append({
            "timestamp": round(timestamp, 3),
            "energy_level": energy_level,
            "zoom_factor": zoom_factor,
            "duration": duration,
            "ease": "ease_in_out",
        })
        last_timestamp = timestamp

    # Clean up temp wav
    try:
        wav_path.unlink()
    except OSError:
        pass

    result: dict[str, Any] = {
        "source": vpath.name,
        "audio_duration": round(audio_duration, 2),
        "emphasis_count": len(keyframes),
        "keyframes": keyframes,
    }

    # Write output
    out_path = out_dir / f"{vpath.stem}_emphasis_keyframes.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    return result
