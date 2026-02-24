"""resolve_detect_test.py -- Detection library test harness for NB11 Resolve tools.

Provides 6 media detectors (4 ffmpeg-based, 2 stubs) that scan media files
for edit-relevant events (silence, scene changes, black frames, audio peaks,
speaker changes, breaths).  Results are saved as JSON and can be injected as
Yellow markers into a DaVinci Resolve timeline.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from resolve_common import TOOLS_DIR, connect_resolve


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class DetectionResult:
    """A single detected event in a media file."""

    start_tc: float       # seconds
    end_tc: float         # seconds
    confidence: float     # 0.0 .. 1.0
    label: str            # human-readable description
    detector_name: str    # which detector produced this


# ---------------------------------------------------------------------------
# Abstract detector
# ---------------------------------------------------------------------------

class Detector(ABC):
    """Base class for all media detectors."""

    name: str = ""

    @abstractmethod
    def detect(self, media_path: str) -> list[DetectionResult]:
        """Scan *media_path* and return a list of DetectionResult."""
        ...


# ---------------------------------------------------------------------------
# ffmpeg-based detectors
# ---------------------------------------------------------------------------

class SilenceDetector(Detector):
    """Detect silent regions using ffmpeg silencedetect."""

    name = "silence"

    def __init__(self, threshold_db: float = -30.0, min_duration: float = 0.5):
        self.threshold_db = threshold_db
        self.min_duration = min_duration

    def detect(self, media_path: str) -> list[DetectionResult]:
        cmd = [
            "ffmpeg", "-i", media_path, "-af",
            f"silencedetect=noise={self.threshold_db}dB:d={self.min_duration}",
            "-f", "null", "-",
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return []

        results: list[DetectionResult] = []
        stderr = proc.stderr

        # Parse pairs: silence_start / silence_end
        starts = re.findall(r"silence_start:\s*([\d.]+)", stderr)
        ends = re.findall(r"silence_end:\s*([\d.]+)", stderr)

        for s, e in zip(starts, ends):
            start_f = float(s)
            end_f = float(e)
            results.append(DetectionResult(
                start_tc=start_f,
                end_tc=end_f,
                confidence=0.95,
                label=f"silence ({end_f - start_f:.2f}s)",
                detector_name=self.name,
            ))
        return results


class SceneChangeDetector(Detector):
    """Detect scene changes using ffmpeg scene filter."""

    name = "scene_change"

    def __init__(self, threshold: float = 0.3):
        self.threshold = threshold

    def detect(self, media_path: str) -> list[DetectionResult]:
        cmd = [
            "ffmpeg", "-i", media_path,
            "-vf", f"select='gt(scene,{self.threshold})',showinfo",
            "-f", "null", "-",
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return []

        results: list[DetectionResult] = []
        stderr = proc.stderr

        # Parse showinfo pts_time lines
        for match in re.finditer(r"pts_time:\s*([\d.]+)", stderr):
            tc = float(match.group(1))
            results.append(DetectionResult(
                start_tc=tc,
                end_tc=tc,
                confidence=0.85,
                label="scene change",
                detector_name=self.name,
            ))
        return results


class AudioPeakDetector(Detector):
    """Detect audio peaks using ffmpeg astats."""

    name = "audio_peak"

    def __init__(self, peak_threshold_db: float = -3.0):
        self.peak_threshold_db = peak_threshold_db

    def detect(self, media_path: str) -> list[DetectionResult]:
        cmd = [
            "ffmpeg", "-i", media_path,
            "-af", "astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.Peak_level",
            "-f", "null", "-",
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return []

        results: list[DetectionResult] = []
        stderr = proc.stderr

        # Parse frame timestamps and peak levels
        current_time: float | None = None
        for line in stderr.splitlines():
            time_match = re.search(r"pts_time:\s*([\d.]+)", line)
            if time_match:
                current_time = float(time_match.group(1))

            peak_match = re.search(r"lavfi\.astats\.Overall\.Peak_level=(-?[\d.]+)", line)
            if peak_match and current_time is not None:
                peak_db = float(peak_match.group(1))
                if peak_db >= self.peak_threshold_db:
                    results.append(DetectionResult(
                        start_tc=current_time,
                        end_tc=current_time,
                        confidence=0.80,
                        label=f"audio peak ({peak_db:.1f} dB)",
                        detector_name=self.name,
                    ))
        return results


class BlackFrameDetector(Detector):
    """Detect black frames using ffmpeg blackdetect."""

    name = "black_frame"

    def __init__(self, duration: float = 0.1, pix_th: float = 0.10):
        self.duration = duration
        self.pix_th = pix_th

    def detect(self, media_path: str) -> list[DetectionResult]:
        cmd = [
            "ffmpeg", "-i", media_path,
            "-vf", f"blackdetect=d={self.duration}:pix_th={self.pix_th}",
            "-f", "null", "-",
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return []

        results: list[DetectionResult] = []
        stderr = proc.stderr

        for match in re.finditer(
            r"black_start:\s*([\d.]+)\s+black_end:\s*([\d.]+)\s+black_duration:\s*([\d.]+)",
            stderr,
        ):
            start_f = float(match.group(1))
            end_f = float(match.group(2))
            dur_f = float(match.group(3))
            results.append(DetectionResult(
                start_tc=start_f,
                end_tc=end_f,
                confidence=0.90,
                label=f"black frame ({dur_f:.2f}s)",
                detector_name=self.name,
            ))
        return results


# ---------------------------------------------------------------------------
# Stub detectors (future implementation)
# ---------------------------------------------------------------------------

class SpeakerChangeDetector(Detector):
    """Stub: detect speaker changes. Returns empty list."""

    name = "speaker_change"

    def detect(self, media_path: str) -> list[DetectionResult]:
        return []


class BreathDetector(Detector):
    """Stub: detect breaths. Returns empty list."""

    name = "breath"

    def detect(self, media_path: str) -> list[DetectionResult]:
        return []


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

ALL_DETECTORS: list[Detector] = [
    SilenceDetector(),
    SceneChangeDetector(),
    AudioPeakDetector(),
    BlackFrameDetector(),
    SpeakerChangeDetector(),
    BreathDetector(),
]


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def results_to_json(results: list[DetectionResult]) -> str:
    """Serialize a list of DetectionResult to a JSON string."""
    return json.dumps([asdict(r) for r in results], indent=2)


def save_results(
    media_path: str,
    results: list[DetectionResult],
    timings: dict[str, float],
) -> Path:
    """Save detection results to TOOLS_DIR/detect_results/{stem}_{timestamp}.json.

    Returns the path to the saved file.
    """
    output_dir = TOOLS_DIR / "detect_results"
    output_dir.mkdir(parents=True, exist_ok=True)

    stem = Path(media_path).stem
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{stem}_{timestamp}.json"
    out_path = output_dir / filename

    payload = {
        "media_path": str(media_path),
        "timestamp": timestamp,
        "total_detections": len(results),
        "timings": timings,
        "results": [asdict(r) for r in results],
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    print(f"[OK] Results saved to {out_path}")
    return out_path


# ---------------------------------------------------------------------------
# Run / show / inject
# ---------------------------------------------------------------------------

def run_test(media_path: str, only: list[str] | None = None) -> None:
    """Run detectors against *media_path*, print summary, and save results."""
    path = Path(media_path)
    if not path.exists():
        print(f"[ERROR] File not found: {media_path}")
        sys.exit(1)

    detectors = ALL_DETECTORS
    if only:
        detectors = [d for d in ALL_DETECTORS if d.name in only]
        if not detectors:
            print(f"[ERROR] No matching detectors for: {only}")
            sys.exit(1)

    print(f"[DETECT] Scanning: {path.name}")
    print(f"[DETECT] Detectors: {', '.join(d.name for d in detectors)}")
    print()

    all_results: list[DetectionResult] = []
    timings: dict[str, float] = {}

    for detector in detectors:
        t0 = time.time()
        results = detector.detect(media_path)
        elapsed = time.time() - t0
        timings[detector.name] = round(elapsed, 3)

        all_results.extend(results)
        print(f"  {detector.name:20s}  {len(results):4d} detections  ({elapsed:.2f}s)")

    print()
    print(f"[DETECT] Total: {len(all_results)} detections")

    save_results(media_path, all_results, timings)


def show_results() -> None:
    """List past detection runs from the detect_results directory."""
    results_dir = TOOLS_DIR / "detect_results"
    if not results_dir.exists():
        print("[INFO] No detect_results directory found.")
        return

    files = sorted(results_dir.glob("*.json"), reverse=True)
    if not files:
        print("[INFO] No results files found.")
        return

    print(f"[RESULTS] {len(files)} run(s) in {results_dir}\n")
    for f in files:
        try:
            with open(f, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            media = Path(data.get("media_path", "unknown")).name
            total = data.get("total_detections", "?")
            ts = data.get("timestamp", "?")
            print(f"  {f.name:50s}  {media:30s}  {total:>4} detections  ({ts})")
        except Exception:
            print(f"  {f.name:50s}  (could not parse)")


def inject_results(results_path: str, resolve=None) -> None:
    """Place Yellow markers in Resolve for each detection in *results_path*.

    If *resolve* is None, connect_resolve() is called to obtain the Resolve object.
    """
    path = Path(results_path)
    if not path.exists():
        print(f"[ERROR] Results file not found: {results_path}")
        sys.exit(1)

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    results_data = data.get("results", [])
    if not results_data:
        print("[INFO] No detections to inject.")
        return

    if resolve is None:
        resolve = connect_resolve()

    project = resolve.GetProjectManager().GetCurrentProject()
    if project is None:
        print("[ERROR] No project open in Resolve.")
        sys.exit(1)

    timeline = project.GetCurrentTimeline()
    if timeline is None:
        print("[ERROR] No timeline selected in Resolve.")
        sys.exit(1)

    fps = float(timeline.GetSetting("timelineFrameRate") or 24.0)
    marker_count = 0

    for r in results_data:
        start_tc = r.get("start_tc", 0.0)
        label = r.get("label", "detection")
        detector = r.get("detector_name", "unknown")

        frame = int(start_tc * fps)
        note = f"[{detector}] {label}"

        success = timeline.AddMarker(
            frame,
            "Yellow",
            detector,
            note,
            1,  # duration = 1 frame
        )
        if success:
            marker_count += 1

    print(f"[OK] Injected {marker_count}/{len(results_data)} markers into timeline '{timeline.GetName()}'")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="NB11 Resolve detection test harness",
    )
    parser.add_argument(
        "--test", metavar="FILE",
        help="Run detectors against a media file",
    )
    parser.add_argument(
        "--results", action="store_true",
        help="List past detection runs",
    )
    parser.add_argument(
        "--inject", metavar="JSON",
        help="Inject detection results as Yellow markers into Resolve",
    )
    parser.add_argument(
        "--only", metavar="DETECTORS",
        help="Comma-separated list of detector names to run (e.g. silence,scene_change)",
    )

    args = parser.parse_args()

    if args.results:
        show_results()
    elif args.inject:
        inject_results(args.inject)
    elif args.test:
        only = [s.strip() for s in args.only.split(",")] if args.only else None
        run_test(args.test, only=only)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
