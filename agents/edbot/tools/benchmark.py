"""EdBot pipeline benchmark — timed runs of core stages."""

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def run_benchmark(video_path: str, runs: int = 3) -> dict[str, Any]:
    """Run timed benchmarks on core pipeline stages.

    Args:
        video_path: Absolute path to a video file.
        runs: Number of timed runs per stage (default 3).

    Returns dict with per-stage results and metadata.
    """
    p = Path(video_path)
    if not p.exists():
        return {"error": f"file not found: {video_path}"}

    if runs < 1:
        runs = 1

    results: dict[str, Any] = {
        "video_path": video_path,
        "runs": runs,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Stage 1: transcribe
    from transcribe import transcribe_video

    transcribe_times = []
    transcribe_result = None
    for _ in range(runs):
        t0 = time.perf_counter()
        transcribe_result = transcribe_video(video_path, "temp")
        transcribe_times.append(time.perf_counter() - t0)

    mean_t = sum(transcribe_times) / len(transcribe_times)
    results["transcribe"] = {
        "mean_s": round(mean_t, 3),
        "target_s": 30,
        "pass": mean_t < 30,
    }

    # Stage 2: search (stress test with common word)
    from transcript_index import build_index, search_index

    chunks = (transcribe_result or {}).get("chunks", [])
    index = build_index({"test": {"chunks": chunks}})
    search_times = []
    for _ in range(runs):
        t0 = time.perf_counter()
        search_index(index, "the", max_results=20)
        search_times.append(time.perf_counter() - t0)

    mean_s = sum(search_times) / len(search_times)
    results["search"] = {
        "mean_s": round(mean_s, 6),
        "target_s": 0.1,
        "pass": mean_s < 0.1,
    }

    # Stage 3: silence detection
    from silence_detect import detect_silence

    silence_times = []
    for _ in range(runs):
        t0 = time.perf_counter()
        detect_silence(video_path, output_dir="temp")
        silence_times.append(time.perf_counter() - t0)

    mean_si = sum(silence_times) / len(silence_times)
    results["silence_detect"] = {
        "mean_s": round(mean_si, 3),
        "target_s": 10,
        "pass": mean_si < 10,
    }

    # Stage 4: chapter detection
    from chapter_detect import detect_chapters

    chapter_times = []
    for _ in range(runs):
        t0 = time.perf_counter()
        detect_chapters(chunks)
        chapter_times.append(time.perf_counter() - t0)

    mean_ch = sum(chapter_times) / len(chapter_times)
    results["chapter_detect"] = {
        "mean_s": round(mean_ch, 6),
        "target_s": 5,
        "pass": mean_ch < 5,
    }

    # Stage 5: full pipeline (sequential)
    pipeline_times = []
    for _ in range(runs):
        t0 = time.perf_counter()
        tr = transcribe_video(video_path, "temp")
        detect_silence(video_path, output_dir="temp")
        detect_chapters(tr.get("chunks", []))
        idx = build_index({"test": {"chunks": tr.get("chunks", [])}})
        search_index(idx, "the", max_results=20)
        pipeline_times.append(time.perf_counter() - t0)

    mean_fp = sum(pipeline_times) / len(pipeline_times)
    results["full_pipeline"] = {
        "mean_s": round(mean_fp, 3),
        "target_s": 60,
        "pass": mean_fp < 60,
    }

    return results
