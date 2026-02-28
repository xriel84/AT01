"""Whisper model comparison benchmark.

Runs multiple whisper model sizes on a test video and compares speed vs quality.
Quality measured as word overlap % against large-v3 baseline.

Usage:
    py -3.12 benchmarks/model_comparison.py --video input/IMG_5769.MOV
    py -3.12 benchmarks/model_comparison.py --video input/test_with_silence.mov --models medium,small
"""

import argparse
import gc
import json
import re
import time
from pathlib import Path
from typing import Any


MODELS = ["large-v3", "medium", "small", "base"]
DEFAULT_VIDEO = "input/IMG_5769.MOV"


def compute_word_overlap(text_a: str, text_b: str) -> float:
    """Compute word overlap ratio between two texts.

    Returns the Jaccard similarity of word sets (intersection / union).
    Returns 1.0 if both are empty, 0.0 if one is empty.
    """
    words_a = set(re.findall(r"[a-zA-Z]+", text_a.lower()))
    words_b = set(re.findall(r"[a-zA-Z]+", text_b.lower()))

    if not words_a and not words_b:
        return 1.0
    if not words_a or not words_b:
        return 0.0

    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)


def extract_audio(video_path: str, output_path: str) -> str:
    """Extract audio from video using ffmpeg CLI. Returns audio path."""
    import subprocess
    if Path(output_path).exists():
        return output_path
    subprocess.run(
        ["ffmpeg", "-i", video_path, "-acodec", "pcm_s16le",
         "-ac", "1", "-ar", "16000", "-y", output_path],
        capture_output=True, check=True,
    )
    return output_path


def probe_duration(video_path: str) -> float:
    """Get video duration in seconds using ffprobe."""
    import subprocess
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", video_path],
        capture_output=True, text=True, check=True,
    )
    return float(result.stdout.strip())


def benchmark_model(
    model_name: str,
    audio_path: str,
    compute_type: str = "float16",
) -> dict[str, Any]:
    """Benchmark a single whisper model. Returns timing and transcript."""
    from faster_whisper import WhisperModel
    import torch

    t0 = time.perf_counter()
    model = WhisperModel(model_name, device="cuda", compute_type=compute_type)
    load_time = time.perf_counter() - t0

    t1 = time.perf_counter()
    segments, info = model.transcribe(audio_path, beam_size=5)
    text = " ".join(seg.text.strip() for seg in segments)
    transcribe_time = time.perf_counter() - t1

    word_count = len(text.split())

    del model
    gc.collect()
    torch.cuda.empty_cache()

    return {
        "model": model_name,
        "compute_type": compute_type,
        "load_s": round(load_time, 2),
        "transcribe_s": round(transcribe_time, 2),
        "total_s": round(load_time + transcribe_time, 2),
        "word_count": word_count,
        "language": info.language if info else "unknown",
        "language_prob": round(info.language_probability, 3) if info else 0.0,
        "text": text,
    }


def run_comparison(
    video_path: str,
    models: list[str] | None = None,
    output_path: str | None = None,
) -> list[dict[str, Any]]:
    """Run benchmark across multiple models. Returns results list."""
    if models is None:
        models = MODELS

    audio_path = str(Path(video_path).with_suffix(".wav"))
    if not Path(audio_path).exists():
        audio_dir = Path("temp")
        audio_dir.mkdir(exist_ok=True)
        audio_path = str(audio_dir / (Path(video_path).stem + "_bench.wav"))

    print(f"Extracting audio from {video_path}...")
    extract_audio(video_path, audio_path)

    duration = probe_duration(video_path)
    print(f"Video duration: {duration:.1f}s ({duration/60:.1f} min)")

    results: list[dict[str, Any]] = []
    baseline_text: str | None = None

    for model_name in models:
        print(f"\n--- Benchmarking {model_name} ---")
        try:
            result = benchmark_model(model_name, audio_path)
            result["video"] = Path(video_path).name
            result["video_duration_s"] = round(duration, 1)
            result["realtime_factor"] = round(duration / result["transcribe_s"], 2) if result["transcribe_s"] > 0 else 0

            if model_name == "large-v3" or baseline_text is None:
                if model_name == "large-v3":
                    baseline_text = result["text"]
                    result["word_match_pct"] = 100.0
                else:
                    result["word_match_pct"] = 100.0
            else:
                result["word_match_pct"] = round(
                    compute_word_overlap(result["text"], baseline_text) * 100, 1
                )

            # Remove full text from saved results (too large for JSON)
            result_clean = {k: v for k, v in result.items() if k != "text"}
            results.append(result_clean)

            speed = "FAST" if result["transcribe_s"] < 30 else "SLOW"
            quality = "GOOD" if result.get("word_match_pct", 0) >= 90 else "LOW"
            print(f"  Load: {result['load_s']}s | Transcribe: {result['transcribe_s']}s | "
                  f"Total: {result['total_s']}s | Words: {result['word_count']} | "
                  f"Match: {result.get('word_match_pct', '?')}% | "
                  f"RTF: {result['realtime_factor']}x | [{speed}] [{quality}]")

        except Exception as e:
            print(f"  ERROR: {e}")
            results.append({
                "model": model_name,
                "error": str(e),
                "video": Path(video_path).name,
            })

    # Save results
    if output_path is None:
        output_path = "benchmarks/model_comparison.json"
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({"results": results, "video": Path(video_path).name,
                    "duration_s": round(duration, 1)}, f, indent=2)
    print(f"\nResults saved to {output_path}")

    # Summary table
    print(f"\n{'Model':<12} {'Load':>6} {'Trans':>6} {'Total':>6} {'RTF':>5} {'Match':>6} {'Words':>6}")
    print("-" * 55)
    for r in results:
        if "error" not in r:
            print(f"{r['model']:<12} {r['load_s']:>5.1f}s {r['transcribe_s']:>5.1f}s "
                  f"{r['total_s']:>5.1f}s {r['realtime_factor']:>4.1f}x "
                  f"{r.get('word_match_pct', 0):>5.1f}% {r['word_count']:>5}")

    return results


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Whisper model comparison benchmark")
    parser.add_argument("--video", default=DEFAULT_VIDEO, help="Video file to benchmark")
    parser.add_argument("--models", default=None, help="Comma-separated model list")
    parser.add_argument("--output", default=None, help="Output JSON path")
    args = parser.parse_args()

    models = args.models.split(",") if args.models else None
    run_comparison(args.video, models=models, output_path=args.output)


if __name__ == "__main__":
    main()
