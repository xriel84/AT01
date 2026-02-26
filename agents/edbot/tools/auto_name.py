"""Auto-generate descriptive filenames from transcript content using spaCy NER."""

import json
import re
import sys
from pathlib import Path
from typing import Any

_tools_dir = str(Path(__file__).resolve().parent)
if _tools_dir not in sys.path:
    sys.path.insert(0, _tools_dir)

try:
    import spacy
except ImportError:
    spacy = None  # type: ignore[assignment]

_NER_LABELS = {"PERSON", "ORG", "EVENT", "GPE", "WORK_OF_ART"}


def _load_nlp():
    """Load spaCy English model, returning None on failure."""
    if spacy is None:
        return None
    try:
        return spacy.load("en_core_web_sm")
    except Exception:
        return None


def _sanitize(name: str) -> str:
    """Sanitize a name for filesystem use: lowercase, hyphens, no specials."""
    name = name.lower().strip()
    name = re.sub(r"[^a-z0-9\s-]", "", name)
    name = re.sub(r"\s+", "-", name)
    name = re.sub(r"-+", "-", name)
    name = name.strip("-")
    return name


def auto_name(transcript: dict, max_words: int = 6) -> str:
    """Generate a descriptive filename from transcript content.

    Parameters
    ----------
    transcript : dict
        Transcript dict with "chunks" key (from transcribe_video).
    max_words : int
        Maximum words in generated name.

    Returns
    -------
    str
        Suggested filename (without extension), filesystem-safe.
    """
    if not transcript or not transcript.get("chunks"):
        return "untitled"

    chunks = transcript["chunks"][:5]
    text = " ".join(c.get("text", "") for c in chunks).strip()

    if not text:
        if chunks and "start" in chunks[0]:
            return f"clip-{int(chunks[0]['start'])}"
        return "untitled"

    nlp = _load_nlp()
    if nlp is None:
        words = [w for w in text.split() if len(w) > 2][:max_words]
        return _sanitize(" ".join(words)) or "untitled"

    doc = nlp(text[:5000])

    entities = [
        (ent.text, ent.label_)
        for ent in doc.ents
        if ent.label_ in _NER_LABELS
    ]

    if entities:
        top_entity = entities[0][0]
        entity_texts = {e[0].lower() for e in entities}
        topic_words = [
            token.text for token in doc
            if not token.is_stop and not token.is_punct
            and token.text.lower() not in entity_texts
            and len(token.text) > 2
        ]
        parts = [top_entity]
        if topic_words:
            parts.append(topic_words[0])
        name = " ".join(parts[:max_words])
    else:
        words = [
            token.text for token in doc
            if not token.is_stop and not token.is_punct
            and len(token.text) > 2
        ][:max_words]
        name = " ".join(words)

    result = _sanitize(name)
    return result if result else "untitled"


def batch_auto_name(manifest: dict, output_dir: str = "temp") -> dict:
    """Generate names for all files in a batch manifest.

    Parameters
    ----------
    manifest : dict
        Batch manifest from batch_transcribe.
    output_dir : str
        Directory containing per-file chunk JSONs.

    Returns
    -------
    dict
        Updated manifest with 'suggested_name' in each file entry.
    """
    out_dir = Path(output_dir)
    seen_names: dict[str, int] = {}

    for file_entry in manifest.get("files", []):
        stem = Path(file_entry["filename"]).stem
        chunks_path = out_dir / f"{stem}_chunks.json"

        if chunks_path.exists():
            with open(chunks_path, "r", encoding="utf-8") as f:
                transcript = json.load(f)
        else:
            transcript = {}

        suggested = auto_name(transcript)

        if suggested in seen_names:
            seen_names[suggested] += 1
            suggested = f"{suggested}-{seen_names[suggested]}"
        else:
            seen_names[suggested] = 1

        file_entry["suggested_name"] = suggested

    manifest_path = out_dir / "batch_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    return manifest
