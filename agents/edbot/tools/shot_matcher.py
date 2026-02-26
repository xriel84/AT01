"""Match similar shots/segments across multiple transcribed videos.

Uses transcript text similarity via SequenceMatcher — NOT visual matching.
"""

import json
import sys
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

_tools_dir = str(Path(__file__).resolve().parent)
if _tools_dir not in sys.path:
    sys.path.insert(0, _tools_dir)


def find_matching_shots(
    manifest: dict,
    output_dir: str = "temp",
    similarity_threshold: float = 0.6,
) -> list[dict[str, Any]]:
    """Find similar text segments across multiple transcribed videos.

    Compares chunk text across different files using SequenceMatcher.
    Skips same-file comparisons and chunks with fewer than 10 words.
    Limits to first 100 chunks per file for performance.

    Parameters
    ----------
    manifest : dict
        Batch manifest from batch_transcribe.
    output_dir : str
        Directory containing per-file chunk JSONs.
    similarity_threshold : float
        Minimum similarity ratio to include in results.

    Returns
    -------
    list
        List of match dicts with file_a/b, chunk_a/b, similarity, preview.
    """
    out_dir = Path(output_dir)

    file_chunks: list[tuple[str, list[dict]]] = []

    for file_entry in manifest.get("files", []):
        stem = Path(file_entry["filename"]).stem
        chunks_path = out_dir / f"{stem}_chunks.json"

        if not chunks_path.exists():
            continue

        with open(chunks_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        chunks = data.get("chunks", []) if isinstance(data, dict) else data
        file_chunks.append((file_entry["filename"], chunks[:100]))

    matches: list[dict[str, Any]] = []

    for i in range(len(file_chunks)):
        for j in range(i + 1, len(file_chunks)):
            name_a, chunks_a = file_chunks[i]
            name_b, chunks_b = file_chunks[j]

            for ca in chunks_a:
                text_a = ca.get("text", "")
                if len(text_a.split()) < 10:
                    continue

                for cb in chunks_b:
                    text_b = cb.get("text", "")
                    if len(text_b.split()) < 10:
                        continue

                    similarity = SequenceMatcher(
                        None, text_a.lower(), text_b.lower(),
                    ).ratio()

                    if similarity >= similarity_threshold:
                        preview_words = text_a.split()[:15]
                        preview = " ".join(preview_words) + "..."

                        matches.append({
                            "file_a": name_a,
                            "chunk_a": ca.get("id", 0),
                            "start_a": ca.get("start", 0.0),
                            "file_b": name_b,
                            "chunk_b": cb.get("id", 0),
                            "start_b": cb.get("start", 0.0),
                            "similarity": round(similarity, 2),
                            "shared_text_preview": preview,
                        })

    matches.sort(key=lambda m: m["similarity"], reverse=True)
    return matches
