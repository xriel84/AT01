"""Enhanced chapter detection combining detect_chapters with NLP titles.

Wraps chapter_detect.detect_chapters() — does NOT rewrite detection logic.
"""

import json
import sys
from pathlib import Path
from typing import Any

_tools_dir = str(Path(__file__).resolve().parent)
if _tools_dir not in sys.path:
    sys.path.insert(0, _tools_dir)

from chapter_detect import detect_chapters

_NER_LABELS = {"PERSON", "ORG", "EVENT", "GPE"}


def _load_nlp():
    """Load spaCy English model, returning None on failure."""
    try:
        import spacy
        return spacy.load("en_core_web_sm")
    except Exception:
        return None


def _chapter_text(chunks: list[dict], chunk_ids: list[int]) -> str:
    """Concatenate text from chunks matching the given IDs."""
    by_id = {c["id"]: c for c in chunks}
    texts = []
    for cid in chunk_ids:
        c = by_id.get(cid)
        if c and c.get("text"):
            texts.append(c["text"])
    return " ".join(texts)


def _generate_title(nlp, text: str, max_words: int = 8) -> str:
    """Generate an NER-informed chapter title."""
    if not text.strip():
        return ""
    doc = nlp(text[:3000])
    entities = [ent.text for ent in doc.ents if ent.label_ in _NER_LABELS]

    significant = [
        token.text for token in doc
        if not token.is_stop and not token.is_punct
        and token.pos_ in ("NOUN", "VERB", "PROPN")
        and len(token.text) > 2
    ]

    parts = []
    if entities:
        parts.append(entities[0])
    parts.extend(significant[:max_words - len(parts)])

    title = " ".join(parts[:max_words])
    return title.title() if title else ""


def _extract_entities(nlp, text: str) -> list[str]:
    """Extract unique PERSON/ORG/GPE entities from text."""
    if not text.strip():
        return []
    doc = nlp(text[:3000])
    seen: set[str] = set()
    entities: list[str] = []
    for ent in doc.ents:
        if ent.label_ in _NER_LABELS and ent.text not in seen:
            seen.add(ent.text)
            entities.append(ent.text)
    return entities


def _first_sentence(text: str) -> str:
    """Extract the first sentence from text."""
    if not text.strip():
        return ""
    for end in [".", "!", "?"]:
        idx = text.find(end)
        if idx > 0:
            return text[:idx + 1].strip()
    words = text.split()[:20]
    return " ".join(words)


def auto_chapter(video_path: str, output_dir: str = "temp") -> dict[str, Any]:
    """Generate enhanced chapters with NLP titles, summaries, and entities.

    Parameters
    ----------
    video_path : str
        Path to source video file.
    output_dir : str
        Directory containing transcription output / for writing results.

    Returns
    -------
    dict
        Enhanced chapters with title, summary, key_entities per chapter.
    """
    vpath = Path(video_path)
    out_dir = Path(output_dir)
    stem = vpath.stem

    # Load transcript chunks
    chunks_path = out_dir / f"{stem}_chunks.json"
    chunks_data = None

    if chunks_path.exists():
        with open(chunks_path, "r", encoding="utf-8") as f:
            chunks_data = json.load(f)
    else:
        generic = out_dir / "chunks.json"
        if generic.exists():
            with open(generic, "r", encoding="utf-8") as f:
                chunks_data = json.load(f)

    if chunks_data is None:
        try:
            from transcribe import transcribe_video
            chunks_data = transcribe_video(str(vpath), str(out_dir))
        except Exception as exc:
            return {"error": f"transcription failed: {exc}", "chapters": []}

    if isinstance(chunks_data, dict):
        chunks = chunks_data.get("chunks", [])
        duration = chunks_data.get("duration")
    else:
        chunks = chunks_data
        duration = None

    if not chunks:
        return {"chapters": [], "source": vpath.name}

    # Load silence map if exists
    silence_path = out_dir / f"{stem}_silence.json"
    silence_map = None
    if silence_path.exists():
        with open(silence_path, "r", encoding="utf-8") as f:
            silence_map = json.load(f)

    raw_chapters = detect_chapters(chunks, silence_map=silence_map, duration=duration)

    nlp = _load_nlp()

    enhanced: list[dict[str, Any]] = []
    for ch in raw_chapters:
        chunk_ids = ch.get("chunk_ids", [])
        text = _chapter_text(chunks, chunk_ids)
        word_count = len(text.split()) if text else 0

        if nlp:
            title = _generate_title(nlp, text)
            key_entities = _extract_entities(nlp, text)
        else:
            title = ch.get("title", "")
            key_entities = []

        summary = _first_sentence(text)

        enhanced.append({
            "id": ch["chapter_id"],
            "start": ch["start"],
            "end": ch["end"],
            "title": title or ch.get("title", ""),
            "summary": summary,
            "key_entities": key_entities,
            "bullet_count": max(1, word_count // 80),
            "word_count": word_count,
        })

    result: dict[str, Any] = {
        "source": vpath.name,
        "chapters": enhanced,
    }

    out_path = out_dir / f"{stem}_enhanced_chapters.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    return result
