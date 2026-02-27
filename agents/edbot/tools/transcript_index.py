"""Searchable index across all transcribed videos. Keyword + entity lookup."""

import json
import re
import sys
from pathlib import Path
from typing import Any

_tools_dir = str(Path(__file__).resolve().parent)
if _tools_dir not in sys.path:
    sys.path.insert(0, _tools_dir)

_STOP_WORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "shall",
    "should", "may", "might", "must", "can", "could", "to", "of", "in",
    "for", "on", "with", "at", "by", "from", "as", "into", "through",
    "during", "before", "after", "and", "but", "or", "nor", "not", "so",
    "yet", "both", "it", "its", "this", "that", "these", "those",
    "i", "you", "he", "she", "we", "they", "me", "him", "her", "us", "them",
}


def _load_nlp():
    """Load spaCy English model, returning None on failure."""
    try:
        import spacy
        return spacy.load("en_core_web_sm")
    except Exception:
        return None


def build_index(manifest: dict, output_dir: str = "temp") -> dict[str, Any]:
    """Build a searchable inverted index from batch transcription manifest.

    Parameters
    ----------
    manifest : dict
        Batch manifest from batch_transcribe.
    output_dir : str
        Directory containing per-file chunk JSONs.

    Returns
    -------
    dict
        Index with word_count, entity_count, files_indexed, words, entities.
    """
    out_dir = Path(output_dir)

    word_index: dict[str, list[dict]] = {}
    entity_index: dict[str, list[dict]] = {}
    chunk_texts: dict[str, str] = {}  # "file:chunk" -> text
    filenames: list[str] = []
    files_indexed = 0
    total_words = 0

    nlp = _load_nlp()

    for file_idx, file_entry in enumerate(manifest.get("files", [])):
        stem = Path(file_entry["filename"]).stem
        chunks_path = out_dir / f"{stem}_chunks.json"

        if not chunks_path.exists():
            continue

        with open(chunks_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        chunks = data.get("chunks", []) if isinstance(data, dict) else data
        files_indexed += 1
        filenames.append(file_entry.get("filename", stem))

        for chunk in chunks:
            text = chunk.get("text", "")
            chunk_idx = chunk.get("id", 0)
            start = chunk.get("start", 0.0)
            if text.strip():
                chunk_texts[f"{file_idx}:{chunk_idx}"] = text.strip()

            words = re.findall(r"[a-zA-Z]+", text)
            for word in words:
                word_lower = word.lower()
                if word_lower not in _STOP_WORDS and len(word_lower) > 1:
                    total_words += 1
                    word_index.setdefault(word_lower, []).append({
                        "file": file_idx,
                        "chunk": chunk_idx,
                        "start": start,
                    })

            if nlp and text.strip():
                doc = nlp(text[:3000])
                for ent in doc.ents:
                    entity_index.setdefault(ent.text, []).append({
                        "file": file_idx,
                        "chunk": chunk_idx,
                        "type": ent.label_,
                        "start": start,
                    })

    index: dict[str, Any] = {
        "word_count": total_words,
        "entity_count": len(entity_index),
        "files_indexed": files_indexed,
        "words": word_index,
        "entities": entity_index,
        "chunk_texts": chunk_texts,
        "filenames": filenames,
    }

    index_path = out_dir / "transcript_index.json"
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2)

    return index


def auto_build_index(output_dir: str = "temp") -> dict[str, Any] | None:
    """Auto-build index from batch manifest or individual chunk files.

    Tries batch manifest first. Falls back to scanning for *_chunks.json files.
    Returns the index dict, or None if no chunk data exists.
    """
    out_dir = Path(output_dir)
    manifest_path = out_dir / "batch_manifest.json"

    if manifest_path.exists():
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        return build_index(manifest, output_dir)

    # Fallback: scan for individual _chunks.json files
    chunk_files = sorted(out_dir.glob("*_chunks.json"))
    if not chunk_files:
        return None

    # Synthesize a manifest from found chunk files
    manifest = {"files": []}
    for cf in chunk_files:
        stem = cf.stem.replace("_chunks", "")
        manifest["files"].append({"filename": f"{stem}.mov"})

    return build_index(manifest, output_dir)


def search_index(index: dict, query: str, max_results: int = 20) -> list[dict]:
    """Search the transcript index for query term(s).

    Multi-word queries intersect results across words.
    Case-insensitive. Partial match via startswith.

    Parameters
    ----------
    index : dict
        Index from build_index.
    query : str
        Search query (one or more words).
    max_results : int
        Maximum results to return.

    Returns
    -------
    list
        List of {file, chunk, start, match_type} dicts.
    """
    query_lower = query.lower().strip()
    query_words = re.findall(r"[a-zA-Z]+", query_lower)

    if not query_words:
        return []

    word_index = index.get("words", {})
    entity_index = index.get("entities", {})
    chunk_texts = index.get("chunk_texts", {})
    filenames = index.get("filenames", [])

    # Entity index (exact substring match on entity name)
    entity_results: list[dict] = []
    for entity_name, occurrences in entity_index.items():
        if query_lower in entity_name.lower():
            for occ in occurrences:
                entity_results.append({
                    "file": occ["file"],
                    "chunk": occ["chunk"],
                    "start": occ["start"],
                    "match_type": "entity",
                    "matched": entity_name,
                })

    # Word index (startswith partial match)
    per_word_hits: list[list[tuple[int, int, float]]] = []
    for qword in query_words:
        hits: list[tuple[int, int, float]] = []
        for indexed_word, occurrences in word_index.items():
            if indexed_word == qword or indexed_word.startswith(qword):
                for occ in occurrences:
                    hits.append((occ["file"], occ["chunk"], occ["start"]))
        per_word_hits.append(hits)

    if len(per_word_hits) == 1:
        word_results = [
            {"file": h[0], "chunk": h[1], "start": h[2], "match_type": "word"}
            for h in per_word_hits[0]
        ]
    else:
        sets = [{(h[0], h[1]) for h in hits} for hits in per_word_hits]
        common = sets[0]
        for s in sets[1:]:
            common &= s
        start_map = {(h[0], h[1]): h[2] for h in per_word_hits[0]}
        word_results = [
            {"file": fc[0], "chunk": fc[1],
             "start": start_map.get(fc, 0.0), "match_type": "word"}
            for fc in common
        ]

    seen: set[tuple[int, int]] = set()
    combined: list[dict] = []
    for r in entity_results + word_results:
        key = (r["file"], r["chunk"])
        if key not in seen:
            seen.add(key)
            combined.append(r)

    combined.sort(key=lambda x: (x["file"], x["chunk"]))

    # Enrich results with chunk text and filename
    for r in combined:
        key = f"{r['file']}:{r['chunk']}"
        r["chunk_text"] = chunk_texts.get(key, "")
        if filenames and r["file"] < len(filenames):
            r["filename"] = filenames[r["file"]]

    return combined[:max_results]
