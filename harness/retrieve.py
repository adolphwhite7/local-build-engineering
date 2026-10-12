"""File retrieval and paragraph-first passage splitting.

Only files explicitly listed in manifest.json are reachable through
configured allowed roots.  File entries carry a root ID and a
root-relative path; root IDs are resolved from settings.json.
Reads are binary-bounded, size-checked, and decoded as UTF-8 only after
the byte limit is validated.
"""

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_SUFFIXES = (".md", ".txt")

STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "if", "then", "else", "when", "where",
    "how", "why", "what", "which", "who", "whom", "is", "are", "was", "were",
    "be", "been", "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "shall", "should", "can", "could", "may", "might", "must", "of",
    "in", "on", "at", "by", "for", "with", "about", "against", "between",
    "into", "through", "during", "before", "after", "above", "below", "to",
    "from", "up", "down", "out", "off", "over", "under", "again", "further",
    "then", "once", "here", "there", "all", "any", "both", "each", "few",
    "more", "most", "other", "some", "such", "no", "nor", "not", "only", "own",
    "same", "so", "than", "too", "very", "s", "t", "don", "now", "its", "it",
}

DEFAULT_MAX_CANDIDATES = 5


def _load_json(relative_path: str) -> Any:
    with open(ROOT / relative_path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_settings() -> Dict[str, Any]:
    """Load settings; retrieval validates its policy inside the refusal boundary."""
    return _load_json("settings.json")


def load_manifest() -> Dict[str, Any]:
    """Load ``manifest.json`` from the project root."""
    return _load_json("manifest.json")


def _positive_int(value: Any, name: str) -> int:
    """Return *value* if it is a positive integer and not a bool."""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer, got {value!r}")
    return value


def _model_passage_limits(model_cfg: Any) -> Tuple[int, int]:
    """Return validated passage_chars and max_passages model limits."""
    if not isinstance(model_cfg, dict):
        raise ValueError("settings.model must be a JSON object")
    target_chars = _positive_int(
        model_cfg.get("passage_chars", 800), "settings.model.passage_chars"
    )
    max_passages = _positive_int(
        model_cfg.get("max_passages", 3), "settings.model.max_passages"
    )
    return target_chars, max_passages


def _real_path(path: Path) -> Path:
    try:
        return path.resolve()
    except (OSError, RuntimeError) as exc:
        raise ValueError(f"Cannot resolve allowed file path: {path}: {exc}") from exc


def _resolve_roots(raw_roots: Any) -> Dict[str, Path]:
    """Resolve root settings to an absolute map keyed by root ID."""
    if not isinstance(raw_roots, dict) or not raw_roots:
        raise ValueError("settings retrieval.roots must be a non-empty object")

    roots: Dict[str, Path] = {}
    for root_id, raw_path in raw_roots.items():
        if not isinstance(root_id, str) or not root_id.strip():
            raise ValueError(
                "settings retrieval root ids must be non-empty strings"
            )
        if isinstance(raw_path, Path):
            path = raw_path
        elif isinstance(raw_path, str) and raw_path.strip():
            path = Path(raw_path)
        else:
            raise ValueError(
                f"settings retrieval root {root_id!r} path must be a non-empty string"
            )
        path = _real_path(path if path.is_absolute() else ROOT / path)
        if not path.is_dir():
            raise ValueError(
                f"settings retrieval root {root_id!r} must be an existing directory"
            )
        roots[root_id] = path
    return roots


def _normalize_settings(settings: Dict[str, Any]) -> Dict[str, Any]:
    """Validate retrieval settings and normalize roots to absolute paths."""
    if not isinstance(settings, dict):
        raise ValueError("settings must be a JSON object")
    retrieval = settings.get("retrieval")
    if not isinstance(retrieval, dict):
        raise ValueError("settings retrieval config is missing or not an object")
    max_file_bytes = _positive_int(
        retrieval.get("max_file_bytes"), "settings retrieval.max_file_bytes"
    )
    max_total_bytes = _positive_int(
        retrieval.get("max_total_bytes"), "settings retrieval.max_total_bytes"
    )
    normalized = dict(settings)
    normalized["retrieval"] = {
        "roots": _resolve_roots(retrieval.get("roots")),
        "max_file_bytes": max_file_bytes,
        "max_total_bytes": max_total_bytes,
    }
    return normalized


def _validate_manifest_files(manifest: Dict[str, Any]) -> None:
    """Validate the explicit root/path manifest file objects."""
    if not isinstance(manifest, dict):
        raise ValueError("manifest must be a JSON object")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("manifest files must be a non-empty object")
    for file_id, entry in files.items():
        if not isinstance(file_id, str) or not file_id.strip():
            raise ValueError("manifest file ids must be non-empty strings")
        if not isinstance(entry, dict):
            raise ValueError(f"manifest file {file_id!r} must be an object")
        root_id = entry.get("root")
        relative_path = entry.get("path")
        if not isinstance(root_id, str) or not root_id.strip():
            raise ValueError(
                f"manifest file {file_id!r} root must be a non-empty string"
            )
        if not isinstance(relative_path, str) or not relative_path.strip():
            raise ValueError(
                f"manifest file {file_id!r} path must be a non-empty string"
            )
        path = Path(relative_path)
        if path.is_absolute():
            raise ValueError(f"manifest file {file_id!r} path must be relative")


def _safe_path(
    file_id: str,
    manifest: Dict[str, Any],
    settings: Dict[str, Any],
) -> Path:
    """Return the absolute, contained, allowlisted path for a known file_id."""
    _validate_manifest_files(manifest)
    normalized = _normalize_settings(settings)

    entry = manifest["files"].get(file_id)
    if entry is None:
        raise FileNotFoundError(f"Unknown file_id: {file_id}")

    root_id = entry["root"]
    relative_path = entry["path"]
    roots = normalized["retrieval"]["roots"]
    if root_id not in roots:
        raise ValueError(f"Path for {file_id} uses unconfigured root {root_id!r}")

    root = roots[root_id]
    target = _real_path(root / relative_path)
    if target != root and root not in target.parents:
        raise ValueError(f"Path for {file_id} escapes root {root_id!r}: {target}")
    suffix = target.suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise ValueError(
            f"Path for {file_id} has disallowed extension {suffix!r}; "
            f"allowed: {ALLOWED_SUFFIXES}"
        )
    if not target.is_file():
        raise FileNotFoundError(f"File not found for {file_id}: {target}")
    return target


def _split_text(text: str, target_chars: int) -> List[str]:
    """Split a paragraph at sentence boundaries; never cut words.

    If any sentence is longer than ``target_chars``, raise ValueError so
    callers return a visible refusal instead of silently dropping text.
    """
    if len(text) <= target_chars:
        return [text]

    sentences = re.split(r"(?<=[.!?])\s+", text)
    pieces: List[str] = []
    current = ""
    for sentence in sentences:
        if not sentence:
            continue
        if len(sentence) > target_chars:
            raise ValueError(
                f"sentence exceeds passage_chars limit of {target_chars}; "
                "refusing to split words or drop content"
            )
        if len(current) + len(sentence) + 1 <= target_chars:
            current = f"{current} {sentence}" if current else sentence
        else:
            if current:
                pieces.append(current)
            current = sentence
    if current:
        pieces.append(current)
    return pieces


def _read_bounded_utf8(
    path: Path,
    max_file_bytes: int,
    max_total_bytes: int,
) -> Tuple[str, str]:
    """Read bounded bytes; return decoded text and the read-bytes SHA-256."""
    allowed = min(max_file_bytes, max_total_bytes)
    try:
        with open(path, "rb") as f:
            data = f.read(allowed + 1)
    except OSError as exc:
        raise FileNotFoundError(f"File not readable: {path}: {exc}") from exc
    if len(data) > allowed:
        if max_file_bytes <= max_total_bytes:
            limit_name = "per-file"
        else:
            limit_name = "per-request total"
        raise ValueError(
            f"File {path} exceeds {limit_name} byte limit of {allowed}"
        )
    file_sha256 = hashlib.sha256(data).hexdigest()
    try:
        return data.decode("utf-8"), file_sha256
    except UnicodeDecodeError as exc:
        raise ValueError(f"File {path} is not valid UTF-8") from exc


def _filename_tokens(relative_path: Any) -> List[str]:
    """Return normalized tokens from a manifest relative path stem."""
    if not isinstance(relative_path, str):
        return []
    return re.findall(r"[a-z0-9]+", Path(relative_path).stem.lower())


def _text_tokens(text: Any) -> List[str]:
    """Return lowercased alphanumeric tokens from text."""
    if not isinstance(text, str):
        return []
    return re.findall(r"[a-z0-9]+", text.lower())


def _normalize_query_tokens(question: str) -> List[str]:
    """Return query words with common words ignored. Keywords nominate only."""
    if not isinstance(question, str):
        return []
    return [
        token for token in re.findall(r"[a-z0-9]+", question.lower())
        if token not in STOPWORDS
    ]


def _token_sequence_in(needle_tokens: List[str], haystack_tokens: List[str]) -> bool:
    """Return True when needle tokens appear as a contiguous sequence."""
    if not needle_tokens:
        return False
    count = len(needle_tokens)
    limit = len(haystack_tokens) - count + 1
    for i in range(limit):
        if haystack_tokens[i:i + count] == needle_tokens:
            return True
    return False


def _score_passage(
    file_name_tokens: List[str],
    query_tokens: List[str],
    passage_text: str,
) -> int:
    """Score one passage for nomination. Score is never a relevance verdict."""
    if not query_tokens:
        return 0
    filename_hits = len(set(file_name_tokens) & set(query_tokens))
    passage_tokens = _text_tokens(passage_text)
    query_word_hits = len(set(query_tokens) & set(passage_tokens))

    exact_phrase_score = 0
    for n in range(len(query_tokens), 1, -1):
        for i in range(0, len(query_tokens) - n + 1):
            phrase_tokens = query_tokens[i:i + n]
            if _token_sequence_in(phrase_tokens, passage_tokens):
                exact_phrase_score = n * 2
                break
        if exact_phrase_score:
            break

    return (3 * filename_hits) + exact_phrase_score + query_word_hits


def nominate_candidates(
    question: str,
    passages: List[Dict[str, Any]],
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
) -> List[Dict[str, Any]]:
    """Rank passages deterministically. Ranking never decides relevance."""
    if (
        isinstance(max_candidates, bool)
        or not isinstance(max_candidates, int)
        or max_candidates <= 0
    ):
        raise ValueError("max_candidates must be a positive integer")
    if not isinstance(question, str):
        raise ValueError("question must be a string")
    if not isinstance(passages, list):
        raise ValueError("passages must be a list")

    query_tokens = _normalize_query_tokens(question)
    scored: List[Dict[str, Any]] = []
    for passage in passages:
        if not isinstance(passage, dict):
            raise ValueError("candidate passages must be objects")
        item = dict(passage)
        item["score"] = _score_passage(
            _filename_tokens(passage.get("file_name", "")),
            query_tokens,
            passage.get("text", ""),
        )
        scored.append(item)

    scored.sort(key=lambda item: (-item["score"], item["passage_id"]))
    return scored[:max_candidates]


def read_candidate_passages(
    file_ids: Any,
    manifest: Dict[str, Any] = None,
    settings: Dict[str, Any] = None,
) -> List[Dict[str, Any]]:
    """Read all explicitly allowed files under one shared byte budget.

    Uses the same manifest/root/extension authorization as ``read_passages``
    and returns paragraph-first passages for candidate nomination.
    """
    if manifest is None:
        manifest = load_manifest()
    if settings is None:
        settings = load_settings()

    settings = _normalize_settings(settings)
    _validate_manifest_files(manifest)
    if not isinstance(file_ids, (list, tuple)) or not file_ids:
        raise ValueError("find requires a non-empty allowed_files list")

    retrieval = settings["retrieval"]
    target_chars, _ = _model_passage_limits(settings.get("model", {}))

    remaining = retrieval["max_total_bytes"]
    seen = set()
    passages: List[Dict[str, Any]] = []

    for file_id in file_ids:
        if not isinstance(file_id, str) or not file_id.strip():
            raise ValueError("allowed_files entries must be non-empty strings")
        if file_id in seen:
            continue
        seen.add(file_id)

        path = _safe_path(file_id, manifest, settings)
        text, file_sha256 = _read_bounded_utf8(
            path,
            retrieval["max_file_bytes"],
            remaining,
        )
        remaining -= len(text.encode("utf-8"))

        raw_paragraphs = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
        paragraph_count = 0
        for original_index, paragraph in enumerate(raw_paragraphs, 1):
            cursor = 0
            for piece in _split_text(paragraph.strip(), target_chars):
                sentence_spans = []
                for sentence in re.split(r"(?<=[.!?])\s+", piece):
                    sentence = sentence.strip()
                    if not sentence:
                        continue
                    start = paragraph.index(sentence, cursor)
                    end = start + len(sentence)
                    sentence_spans.append({"text": sentence, "span": [start, end]})
                    cursor = end
                paragraph_count += 1
                passages.append(
                    {
                        "file_id": file_id,
                        "passage_id": f"{file_id}-P{paragraph_count:02d}",
                        "text": piece,
                        "paragraph_index": paragraph_count,
                        "file_sha256": file_sha256,
                        "file_name": manifest["files"][file_id]["path"],
                        "original_paragraph_index": original_index,
                        "original_paragraph": paragraph,
                        "piece_span": [sentence_spans[0]["span"][0],
                                       sentence_spans[-1]["span"][1]],
                        "sentence_spans": sentence_spans,
                    }
                )

    return passages


def read_passages(
    file_id: str,
    manifest: Dict[str, Any] = None,
    settings: Dict[str, Any] = None,
) -> Tuple[List[Dict[str, Any]], str]:
    """Read a file and return paragraph-first numbered passages.

    The returned list is capped to ``model.max_passages``; the second
    return value is a short coverage string such as
    ``sent 3 of 5 paragraphs``.  The per-request byte budget applies to
    this single read call; summarize currently reads one file and does not
    aggregate bytes across files.
    """
    if manifest is None:
        manifest = load_manifest()
    if settings is None:
        settings = load_settings()

    settings = _normalize_settings(settings)
    _validate_manifest_files(manifest)

    target_chars, max_passages = _model_passage_limits(settings.get("model", {}))

    retrieval = settings["retrieval"]
    path = _safe_path(file_id, manifest, settings)
    text, file_sha256 = _read_bounded_utf8(
        path,
        retrieval["max_file_bytes"],
        retrieval["max_total_bytes"],
    )

    # Paragraph-first: blank lines separate paragraphs.
    raw_paragraphs = [
        p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()
    ]

    passages: List[Dict[str, Any]] = []
    paragraph_count = 0
    for paragraph in raw_paragraphs:
        for piece in _split_text(paragraph, target_chars):
            paragraph_count += 1
            passages.append(
                {
                    "file_id": file_id,
                    "passage_id": f"{file_id}-P{paragraph_count:02d}",
                    "text": piece,
                    "paragraph_index": paragraph_count,
                    "file_sha256": file_sha256,
                }
            )

    sent = passages[:max_passages]
    total = len(passages)
    coverage = (
        f"sent {len(sent)} of {total} passage{'s' if total != 1 else ''}"
        if total <= max_passages
        else f"sent {len(sent)} of {total} passages"
    )
    return sent, coverage
