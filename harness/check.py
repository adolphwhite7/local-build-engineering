"""Deterministic verification of the model's structured response.

A verified quote proves only that the words appear in the cited passage;
it does not prove the answer is true or semantically entailed.
"""

import re
from typing import Any, Dict, List, Optional, Tuple

from m1.scorer import _normalize, _token_quote_match


def _normalize_quote(text: Any) -> str:
    """Normalize the quote/passage text using M1 rules."""
    return _normalize(text)


def _find_passage(passage_id: Any, passages: List[Dict[str, Any]]) -> Dict[str, Any]:
    for p in passages:
        if p.get("passage_id") == passage_id:
            return p
    return {}


MEANING_JUDGMENTS = ("yes", "no", "unclear")


def validate_meaning_output(response: Any) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Validate the exact closed yes/no/unclear + sentence contract."""
    if not isinstance(response, dict):
        return False, "meaning output is not a JSON object", None

    required_set = {"judgment", "sentence"}
    if set(response.keys()) != required_set:
        missing = [k for k in sorted(required_set) if k not in response]
        if missing:
            return False, f"missing fields: {', '.join(missing)}", None
        unknown = [k for k in response if k not in required_set]
        return False, f"unknown fields: {', '.join(unknown)}", None

    judgment = response["judgment"]
    if not isinstance(judgment, str) or judgment not in MEANING_JUDGMENTS:
        return (
            False,
            f"judgment must be one of {', '.join(MEANING_JUDGMENTS)}",
            None,
        )

    sentence = response["sentence"]
    if not isinstance(sentence, str) or not sentence.strip():
        return False, "sentence must be a non-empty string", None

    return True, "", response


def _check_supporting_sentence(
    sentence: Any,
    passage: Dict[str, Any],
) -> Tuple[bool, str]:
    """Verify a supporting sentence appears in its cited candidate passage."""
    if not isinstance(sentence, str):
        return False, "sentence is not a string"
    normalized_sentence = _normalize_quote(sentence)
    if not normalized_sentence.strip():
        return False, "supporting sentence is empty"
    normalized_passage = _normalize_quote(passage.get("text", ""))
    if not _token_quote_match(normalized_sentence, normalized_passage):
        return False, "supporting sentence not found in cited passage"
    return True, ""


def check_meaning_response(
    response: Any,
    passage: Dict[str, Any],
    allowed_sentences: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Check a per-candidate meaning response against one candidate."""
    result: Dict[str, Any] = {
        "judgment": "",
        "sentence": "",
        "valid": False,
        "reason": "",
    }

    schema_ok, reason, _ = validate_meaning_output(response)
    if not schema_ok:
        result["reason"] = reason
        return result

    result["judgment"] = response["judgment"]
    result["sentence"] = response["sentence"]
    sentence_ok, reason = _check_supporting_sentence(
        response["sentence"],
        passage,
    )
    if not sentence_ok:
        result["reason"] = reason
        return result
    if allowed_sentences is not None and response["sentence"] not in allowed_sentences:
        result["reason"] = "supporting sentence not one of the exact candidate sentences"
        return result

    result["valid"] = True
    return result


def check_meaning_selection(
    response: Any,
    passage: Dict[str, Any],
    sentence_options: List[str],
) -> Dict[str, Any]:
    """Resolve an explicit model selection; software owns the source wording.

    This checks structure and attribution only, never the truth of a judgment.
    The legacy sentence-response checker remains available for old contracts.
    """
    result = {"judgment": "", "sentence": "", "valid": False,
              "reason": "", "sentence_index": None,
              "sentence_actor": "software_original_sentence_selection"}
    if not isinstance(response, dict) or set(response) != {"judgment", "sentence_index"}:
        # Retain rejected legacy words for the existing unaccepted-word panel.
        # They never become a resolved source selection or an accepted answer.
        if isinstance(response, dict) and isinstance(response.get("sentence"), str):
            result["sentence"] = response["sentence"]
            result["sentence_actor"] = "rejected_model_words"
        result["reason"] = "meaning selection requires exactly judgment and sentence_index"
        return result
    judgment = response["judgment"]
    if not isinstance(judgment, str) or judgment not in MEANING_JUDGMENTS:
        result["reason"] = f"judgment must be one of {', '.join(MEANING_JUDGMENTS)}"
        return result
    result["judgment"] = judgment
    index = response["sentence_index"]
    if type(index) is not int or not 0 <= index < len(sentence_options):
        result["reason"] = "sentence_index must be an integer within the supplied sentence list"
        return result
    result["sentence_index"] = index
    # Keep the exact-source membership and quotation checks after resolution.
    checked = check_meaning_response(
        {"judgment": judgment, "sentence": sentence_options[index]},
        passage, sentence_options,
    )
    result.update(checked)
    return result


def validate_ollama_output(response: Any) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Validate the exact structural contract of the model response.

    Returns ``(valid, reason, normalized)``.  A schema-valid response has exactly
    the required keys, the required types, and an internally consistent
    ``found`` contract.  Quote correctness is *not* checked here.
    """
    if not isinstance(response, dict):
        return False, "model output is not a JSON object", None

    required = ("answer", "quote", "passage_id", "found")
    required_set = set(required)
    if set(response.keys()) != required_set:
        missing = [k for k in required if k not in response]
        if missing:
            return False, f"missing fields: {', '.join(missing)}", None
        unknown = [k for k in response if k not in required_set]
        return False, f"unknown fields: {', '.join(unknown)}", None

    for key in required:
        if key == "found":
            if not isinstance(response[key], bool):
                return False, f"{key} is not a boolean", None
        elif not isinstance(response[key], str):
            return False, f"{key} is not a string", None

    if response["found"] is True:
        if not response["answer"].strip():
            return False, "found=true requires a non-empty answer", None
    else:
        if response["answer"] or response["quote"] or response["passage_id"]:
            return False, "found=false requires empty answer/quote/passage_id", None

    return True, "", response


def _check_quote(
    quote: Any,
    passage_id: Any,
    passages: List[Dict[str, Any]],
) -> Tuple[bool, str]:
    """Verify a purported quote against its cited passage.

    Returns (ok, reason).
    """
    if not isinstance(quote, str):
        return False, "quote is not a string"
    if not isinstance(passage_id, str):
        return False, "passage_id is not a string"

    normalized_quote = _normalize_quote(quote)
    if not normalized_quote:
        return False, "quote is empty after normalization"

    passage = _find_passage(passage_id, passages)
    if not passage:
        return False, f"passage_id {passage_id} was not sent"

    normalized_passage = _normalize_quote(passage.get("text", ""))
    if not _token_quote_match(normalized_quote, normalized_passage):
        return False, "quote text not found in cited passage"
    return True, ""


def source_preview(quote: str, passage: Dict[str, Any], accepted: bool) -> Dict[str, Any]:
    """Project the existing quote rule onto same-read original code points."""
    paragraph = passage["original_paragraph"]
    start, end = passage["piece_span"]
    preview = {
        "file_id": passage["file_id"],
        "passage_id": passage["passage_id"],
        "file_sha256": passage["file_sha256"],
        "original_paragraph_index": passage["original_paragraph_index"],
        "paragraph": paragraph,
        "piece_span": [start, end],
        "coordinate_unit": "unicode_codepoint",
        "quote": quote,
        "quote_accepted": False,
        "supporting_span": None,
        "match_count": 0,
    }
    if not accepted or not _check_quote(quote, passage["passage_id"], [passage])[0]:
        return preview
    tokens = list(re.finditer(r"\S+", paragraph[start:end]))
    normalized = [_normalize_quote(token.group()) for token in tokens]
    wanted = _normalize_quote(quote).split()
    matches = [i for i in range(len(tokens) - len(wanted) + 1)
               if normalized[i:i + len(wanted)] == wanted]
    if matches:
        first = matches[0]
        preview.update(
            quote_accepted=True,
            supporting_span=[start + tokens[first].start(),
                             start + tokens[first + len(wanted) - 1].end()],
            match_count=len(matches),
        )
    return preview


def check_response(
    response: Dict[str, Any],
    passages: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Check the parsed model response.

    Returns a result dictionary with R10 status in ``status`` and the
    original synthetic parsed output preserved in ``model_output``.
    """
    result: Dict[str, Any] = {
        "status": "unverified",
        "answer": "",
        "quote": "",
        "passage_id": "",
        "found": False,
        "verified": False,
        "model_output": response,
        "details": {"reason": ""},
    }

    schema_ok, reason, _ = validate_ollama_output(response)
    if not schema_ok:
        result["details"]["reason"] = reason
        return result

    result["answer"] = response["answer"]
    result["quote"] = response["quote"]
    result["passage_id"] = response["passage_id"]
    result["found"] = response["found"]

    if response["found"] is False:
        result["status"] = "not_found"
        result["details"]["reason"] = "model reported no relevant passage"
        return result

    quote_ok, reason = _check_quote(
        response["quote"], response["passage_id"], passages
    )
    if quote_ok:
        result["status"] = "verified"
        result["verified"] = True
        result["details"]["reason"] = "quote verified"
    else:
        result["status"] = "unverified"
        result["details"]["reason"] = reason
    return result
