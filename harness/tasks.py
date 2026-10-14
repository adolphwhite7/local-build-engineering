"""Fixed-task prompts and orchestration.

Prompts live here, not in configuration. The harness decides how to
split the job; the model is asked one narrow judgment at a time.
"""

import json
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from .check import _check_quote, check_meaning_selection, check_response, source_preview, validate_ollama_output
from .model import (
    APIFailureError,
    LOCAL_OLLAMA_SCHEMA,
    ModelUnavailableError,
    ModelVerificationError,
    OllamaClient,
    _observed_thinking,
)
from .retrieve import (
    DEFAULT_MAX_CANDIDATES,
    load_manifest,
    load_settings,
    nominate_candidates,
    read_candidate_passages,
    read_passages,
)


_FILE_TARGET = r"[A-Za-z0-9_./-]+\.(?:md|txt)\b"
_WRITE_LEAD = re.compile(
    r"^\s*(?:please\s+)?"
    r"(update|append|delete|write|overwrite|replace|modify|edit|remove|create|add|insert|save)\b\s+"
    r"(.*)$",
    re.IGNORECASE,
)
_DIRECT_FILE_TARGET = re.compile(
    rf"^(?:(?:the|a|an|my|this)\s+)?(?:new\s+)?(?:file\s+)?{_FILE_TARGET}",
    re.IGNORECASE,
)
_FILE_CONTENT_TARGET = re.compile(
    rf"\b(?:to|into)\s+(?:the\s+)?(?:file\s+)?{_FILE_TARGET}",
    re.IGNORECASE,
)
_FILE_REMOVAL_TARGET = re.compile(
    rf"\bfrom\s+(?:the\s+)?(?:file\s+)?{_FILE_TARGET}",
    re.IGNORECASE,
)
_READ_SHAPED_OBJECT = re.compile(
    r"^(?:a|an|the)\s+(?:summary|report|analysis|overview)\s+"
    r"(?:of|on|about|from)\b",
    re.IGNORECASE,
)
_READ_SHAPED_TO_DESTINATION = re.compile(
    rf"^(?:a|an|the)\s+(?:summary|report|analysis|overview)\s+"
    rf"(?:of|on|about|from)\s+{_FILE_TARGET}\s+"
    rf"(?:to|into)\s+(?:the\s+)?(?:file\s+)?{_FILE_TARGET}",
    re.IGNORECASE,
)


def _explicit_file_write_request(question: str) -> bool:
    """Recognize a narrow, direct file-edit command before any file is read.

    This improves refusal wording; the read-only file boundary is independent
    and also protects against indirect or unrecognized write requests.
    """
    match = _WRITE_LEAD.match(question)
    if not match:
        return False
    rest = match.group(2)
    if _READ_SHAPED_OBJECT.match(rest):
        return bool(_READ_SHAPED_TO_DESTINATION.match(rest))
    verb = match.group(1).casefold()
    return bool(
        _DIRECT_FILE_TARGET.match(rest)
        or _FILE_CONTENT_TARGET.search(rest)
        or (verb in {"delete", "remove"} and _FILE_REMOVAL_TARGET.search(rest))
    )


def _summarize_prompt(question: str, passages: List[Dict[str, Any]]) -> str:
    texts = []
    for p in passages:
        texts.append(f"[{p['passage_id']}]:\n{p['text']}")
    joined = "\n\n".join(texts)
    return (
        "Answer the question using only the numbered passages below.\n"
        "If none of the passages answer the question, return\n"
        '{"answer": "", "quote": "", "passage_id": "", "found": false}.\n'
        "If a passage answers the question, return a JSON object with exactly\n"
        "these keys and types:\n"
        '  answer: string (a concise answer)\n'
        '  quote: string (a nonempty exact contiguous quotation from the cited passage)\n'
        '  passage_id: string (one of the passage identifiers shown below)\n'
        '  found: boolean (true)\n'
        "Do not include anything outside the JSON object.\n\n"
        f"Question: {question}\n\n"
        f"Passages:\n{joined}"
    )


def _candidate_sentences(candidate: Dict[str, Any]) -> List[str]:
    """Offer only verbatim source spans, using the retrieval sentence boundary."""
    return list(dict.fromkeys(
        part.strip()
        for part in re.split(r"(?<=[.!?])\s+", candidate["text"])
        if part.strip()
    ))


def MEANING_SCHEMA(sentence_options: Optional[List[str]] = None) -> Dict[str, Any]:
    """JSON schema for the closed per-candidate meaning question."""
    sentence_schema: Dict[str, Any] = {"type": "integer", "minimum": 0}
    if sentence_options is not None:
        sentence_schema["enum"] = list(range(len(sentence_options)))
    return {
        "type": "object",
        "properties": {
            "judgment": {"type": "string", "enum": ["yes", "no", "unclear"]},
            "sentence_index": sentence_schema,
        },
        "required": ["judgment", "sentence_index"],
        "additionalProperties": False,
    }


def _meaning_prompt(question: str, candidate: Dict[str, Any]) -> str:
    """One bounded yes/no/unclear question over one candidate passage."""
    sentences = _candidate_sentences(candidate)
    return (
        "Does this passage answer the question?\n"
        'Use "yes" when it states the answer, including an explicit negative answer.\n'
        'Use "no" when it does not answer, even if some words match.\n'
        'Use "unclear" only when the passage is relevant but genuinely ambiguous.\n'
        "Return a JSON object with exactly these keys and types:\n"
        '  judgment: string, exactly one of "yes", "no", or "unclear"\n'
        '  sentence_index: integer (choose the number of one source sentence '
        'supporting your judgment, including for "no" or "unclear")\n'
        "Numbers start at 0. Software copies that original sentence; do not copy it yourself.\n"
        f"Numbered source sentences: {json.dumps(dict(enumerate(sentences)), ensure_ascii=False)}\n"
        "Do not include anything outside the JSON object.\n\n"
        f"Question: {question}\n\n"
        f"CANDIDATE_ID: {candidate['passage_id']}\n"
        f"Passage:\n{candidate['text']}"
    )


_ONE_FIELD_ORDER = ("found", "passage_id", "quote", "answer")


def _one_field_schema(field: str) -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": {field: {"type": "boolean" if field == "found" else "string"}},
        "required": [field],
        "additionalProperties": False,
    }


def _one_field_prompt(
    question: str,
    passages: List[Dict[str, Any]],
    field: str,
    cited_passage_id: Optional[str] = None,
) -> str:
    # Reuse the concise prompt exercised on the target. Once chosen, only the
    # cited passage is used for quote/answer, so evidence cannot drift silently.
    selected = [p for p in passages if p["passage_id"] == cited_passage_id] if cited_passage_id else passages
    texts = " ".join(f"Passage [{p['passage_id']}]: {p['text']}" for p in selected)
    instruction = {
        "found": "Does the passage answer the question? Return true or false.",
        "passage_id": "Return the passage identifier.",
        "quote": "Copy a nonempty exact contiguous quote from the cited passage supporting the answer.",
        "answer": "Answer the question briefly using the passage.",
    }[field]
    return (
        f"{texts} Question: {question} {instruction} Return one JSON key: {field}"
    )


def _validate_singleton_field(field: str, response: Any) -> Tuple[bool, str]:
    if not isinstance(response, dict):
        return False, f"one-field {field} response is not a JSON object"
    if set(response.keys()) != {field}:
        return False, f"one-field {field} response must contain exactly one key {field!r}"
    value = response[field]
    if field == "found":
        if not isinstance(value, bool):
            return False, "one-field found response is not a boolean"
    elif not isinstance(value, str):
        return False, f"one-field {field} response is not a string"
    return True, ""


def _run_one_field_calls(
    client: Any,
    question: str,
    passages: List[Dict[str, Any]],
    *,
    file_id: str,
    coverage: str,
    evidence: str,
    request_mode: str,
    trace: List[Dict[str, Any]],
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    assembled: Dict[str, Any] = {"answer": "", "quote": "", "passage_id": "", "found": False}
    cited_passage_id: Optional[str] = None
    for field in _ONE_FIELD_ORDER:
        prompt = _one_field_prompt(question, passages, field, cited_passage_id)
        raw_output = None
        try:
            message = client.chat(
                messages=[{"role": "user", "content": prompt}],
                format_schema=_one_field_schema(field),
            )
            raw_output = message.get("raw_content", message.get("content", ""))
            content = message.get("content", "")
            trace.append({
                "field": field,
                "done_reason": message.get("done_reason"),
                "eval_count": message.get("eval_count"),
                "num_predict": getattr(client, "num_predict", None),
                "observed_thinking": _observed_thinking(raw_output, content, message.get("thinking")),
            })
            if message.get("done_reason") == "length":
                return None, _error_result(
                    file_id, question, coverage, client, "unverified",
                    f"one-field {field} call truncated before completion",
                    evidence=evidence, request_mode=request_mode, model_output=raw_output,
                )
            parsed = client.parse_json_content(content)
        except ModelUnavailableError as exc:
            return None, _error_result(
                file_id, question, coverage, client, "interrupted", str(exc),
                evidence=evidence, request_mode=request_mode,
            )
        except (APIFailureError, ValueError) as exc:
            return None, _error_result(
                file_id, question, coverage, client, "unverified", str(exc),
                evidence=evidence, request_mode=request_mode, model_output=raw_output,
            )
        valid, reason = _validate_singleton_field(field, parsed)
        if not valid:
            return None, _error_result(
                file_id, question, coverage, client, "unverified", reason,
                evidence=evidence, request_mode=request_mode, model_output=parsed,
            )
        value = parsed[field]
        if field == "found":
            if value is False:
                return dict(assembled), None
            assembled["found"] = True
        elif field == "passage_id":
            if value not in {p.get("passage_id") for p in passages}:
                return None, _error_result(
                    file_id, question, coverage, client, "unverified",
                    f"passage_id {value} was not sent",
                    evidence=evidence, request_mode=request_mode, model_output=parsed,
                )
            assembled["passage_id"] = value
            cited_passage_id = value
        elif field == "quote":
            assembled["quote"] = value
        elif field == "answer":
            assembled["answer"] = value
    return assembled, None


def probe_one_field(client: Any) -> Dict[str, Any]:
    """Run the one-field path over a clearly marked example diagnostic."""
    if _is_live(client) and client.verify_model().get("id_matches") is not True:
        raise ModelVerificationError("pinned model identity mismatch before one-field diagnostic")
    question = "Where does the pilot harness run?"
    passages = [
        {
            "file_id": "EXAMPLE-P01",
            "passage_id": "EXAMPLE-P01",
            "text": "The pilot harness runs only on the local Mac.",
        }
    ]
    coverage = "example diagnostic: sent 1 of 1 passages"
    evidence = _client_evidence(client)
    request_mode = _request_mode(client)
    trace: List[Dict[str, Any]] = []
    response, error_result = _run_one_field_calls(
        client,
        question,
        passages,
        file_id="EXAMPLE-P01",
        coverage=coverage,
        evidence=evidence,
        request_mode=request_mode,
        trace=trace,
    )
    if error_result is not None:
        return {
            "provenance": (
                "example one-field diagnostic; "
                "not a baseline or reliability estimate"
            ),
            "question": question,
            "passage_id": "EXAMPLE-P01",
            "coverage": coverage,
            "schema_ok": False,
            "verified": False,
            "call_diagnostics": trace,
            "observed_thinking": any(c["observed_thinking"] for c in trace),
            "status": error_result["status"],
            "reason": error_result["details"]["reason"],
            "evidence": evidence,
            "request_mode": request_mode,
        }
    checked = check_response(response, passages)
    return {
        "provenance": (
            "example one-field diagnostic; "
            "not a baseline or reliability estimate"
        ),
        "question": question,
        "passage_id": "EXAMPLE-P01",
        "coverage": coverage,
        "schema_ok": validate_ollama_output(response)[0],
        "call_diagnostics": trace,
        "observed_thinking": any(c["observed_thinking"] for c in trace),
        "status": checked["status"],
        "reason": checked["details"]["reason"],
        "verified": checked["verified"],
        "found": checked["found"],
        "evidence": evidence,
        "request_mode": request_mode,
    }


def _is_live(client: Any) -> bool:
    """Return True when the client is a live Ollama installation."""
    return isinstance(client, OllamaClient)


def _request_mode(client: Any) -> str:
    """Return the chosen request mode for the current client."""
    if getattr(client, "compatibility_mode", False):
        return "compatibility"
    if getattr(client, "send_think_false", True):
        return "send_think_false"
    return "compatibility"


def _client_evidence(client: Any) -> str:
    """Return the provenance label for a result."""
    return "live" if _is_live(client) else "fake"


def summarize(
    client: Any,
    file_id: str,
    question: Optional[str] = None,
    one_field: bool = False,
) -> Dict[str, Any]:
    """Run the bounded summarize task for one file.

    Returns a result dictionary with keys:

    - file_id
    - question
    - coverage (exactly what was sent)
    - model_tag
    - status (verified / unverified / not_found / refused / interrupted)
    - answer / quote / passage_id / found / verified
    - sources (what was checked)
    - details (reason and any error)
    - evidence (live or fake)
    """
    if question is None:
        question = "What is the main point of this file?"

    evidence = _client_evidence(client)
    request_mode = _request_mode(client)

    try:
        passages, coverage = read_passages(file_id)
    except (FileNotFoundError, ValueError) as exc:
        return {
            "file_id": file_id,
            "question": question,
            "coverage": "none",
            "model_tag": getattr(client, "tag", "unknown"),
            "status": "refused",
            "answer": "",
            "quote": "",
            "passage_id": "",
            "found": False,
            "verified": False,
            "sources": [],
            "evidence": evidence,
            "request_mode": request_mode,
            "details": {"reason": f"retrieval refused: {exc}"},
        }

    if _is_live(client):
        try:
            identity = client.verify_model()
        except (ModelUnavailableError, ModelVerificationError) as exc:
            return _error_result(
                file_id, question, coverage, client, "interrupted", str(exc),
                evidence=evidence, request_mode=request_mode,
            )
        except APIFailureError as exc:
            return _error_result(
                file_id, question, coverage, client, "unverified", str(exc),
                evidence=evidence, request_mode=request_mode,
            )
        if not identity.get("id_matches"):
            return _error_result(
                file_id,
                question,
                coverage,
                client,
                "refused",
                (
                    "pinned model identity mismatch: "
                    f"expected prefix {identity.get('id_prefix_expected')!r}, "
                    f"got digest {identity.get('digest', '')[:16]!r}"
                ),
                evidence=evidence,
                request_mode=request_mode,
                identity=identity,
            )

    trace: List[Dict[str, Any]] = []
    if one_field:
        response, one_field_error = _run_one_field_calls(
            client,
            question,
            passages,
            file_id=file_id,
            coverage=coverage,
            evidence=evidence,
            request_mode=request_mode,
            trace=trace,
        )
        if one_field_error is not None:
            one_field_error["call_diagnostics"] = trace
            return one_field_error
    else:
        prompt = _summarize_prompt(question, passages)

        raw_output = None
        try:
            message = client.chat(
                messages=[{"role": "user", "content": prompt}],
                format_schema=LOCAL_OLLAMA_SCHEMA(),
            )
            raw_output = message.get("raw_content", message.get("content", ""))
            content = message.get("content", "")
            if message.get("done_reason") == "length":
                return _error_result(
                    file_id, question, coverage, client, "unverified",
                    "summarize call truncated before completion",
                    evidence=evidence, request_mode=request_mode,
                    model_output=raw_output,
                )
            response = client.parse_json_content(content)
        except ModelUnavailableError as exc:
            return _error_result(
                file_id, question, coverage, client, "interrupted", str(exc),
                evidence=evidence,
                request_mode=request_mode,
            )
        except (APIFailureError, ValueError) as exc:
            return _error_result(
                file_id, question, coverage, client, "unverified", str(exc),
                evidence=evidence,
                request_mode=request_mode,
                model_output=raw_output,
            )

    checked = check_response(response, passages)
    sources = []
    if checked["passage_id"]:
        cited_passage = next(
            (p for p in passages if p.get("passage_id") == checked["passage_id"]),
            {},
        )
        sources.append(
            {
                "file_id": file_id,
                "passage_id": checked["passage_id"],
                "file_sha256": cited_passage.get("file_sha256", ""),
                "quote": checked["quote"],
                "verified": checked["verified"],
            }
        )

    result: Dict[str, Any] = {
        "file_id": file_id,
        "question": question,
        "coverage": coverage,
        "model_tag": getattr(client, "tag", "unknown"),
        "request_mode": request_mode,
        "status": checked["status"],
        "answer": checked["answer"],
        "quote": checked["quote"],
        "passage_id": checked["passage_id"],
        "found": checked["found"],
        "verified": checked["verified"],
        "sources": sources,
        "evidence": evidence,
        "details": {"reason": checked["details"]["reason"]},
        "model_output": checked.get("model_output"),
    }
    if one_field:
        result["call_diagnostics"] = trace
    return result


def _error_result(
    file_id: str,
    question: str,
    coverage: str,
    client: Any,
    status: str,
    reason: str,
    evidence: str = "unknown",
    request_mode: str = "unknown",
    model_output: Any = None,
    identity: Any = None,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "file_id": file_id,
        "question": question,
        "coverage": coverage,
        "model_tag": getattr(client, "tag", "unknown"),
        "request_mode": request_mode,
        "status": status,
        "answer": "",
        "quote": "",
        "passage_id": "",
        "found": False,
        "verified": False,
        "sources": [],
        "evidence": evidence,
        "details": {"reason": reason},
    }
    if model_output is not None:
        result["model_output"] = model_output
    if identity is not None:
        result["identity"] = identity
    return result


def _candidate_summary(candidate: Dict[str, Any]) -> Dict[str, Any]:
    """Return a safe candidate summary without exposing file text."""
    return {
        "file_id": candidate["file_id"],
        "passage_id": candidate["passage_id"],
        "file_sha256": candidate.get("file_sha256", ""),
        "score": candidate.get("score", 0),
    }


def find(
    client: Any,
    question: str,
    allowed_files: List[str],
    manifest: Dict[str, Any] = None,
    settings: Dict[str, Any] = None,
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
) -> Dict[str, Any]:
    """Run M4 candidate nomination and per-candidate meaning checks.

    Keywords only nominate. A model ``yes`` judgment can authorize a
    verified result; ``unclear`` survives only to force asking the person.
    """
    evidence = _client_evidence(client)
    request_mode = _request_mode(client)
    start_time = time.monotonic()
    relevance_start: Optional[float] = None
    passages = []
    candidates = []
    meaning_checks = []
    attempted = []
    source_read_complete = False

    def _finish(result, relevance_elapsed=None):
        selected = [p["passage_id"] for p in candidates]
        completed = [c["passage_id"] for c in meaning_checks]
        ids = {
            "read": [p["passage_id"] for p in passages],
            "selected": selected,
            "attempted": list(attempted),
            "completed": completed,
            "failed_before_check": [i for i in attempted if i not in completed],
            "selected_but_not_sent": [i for i in selected if i not in attempted],
            "read_but_not_selected": [p["passage_id"] for p in passages
                                      if p["passage_id"] not in selected],
        }
        result["coverage_ids"] = ids
        result["coverage_counts"] = {name: len(items) for name, items in ids.items()}
        result["source_read_complete"] = source_read_complete
        if source_read_complete:
            result["coverage"] = "; ".join(
                f"{name.replace('_', ' ')} {len(items)}" for name, items in ids.items()
            ) + "; completed is not proof of correct meaning"
        checked = next((c for c in meaning_checks
                        if c["passage_id"] == result.get("passage_id")), None)
        if checked is None:
            checked = next((c for c in meaning_checks if not c["valid"]), None)
        if checked is not None:
            passage = next(p for p in candidates
                           if p["passage_id"] == checked["passage_id"])
            result["source_preview"] = source_preview(
                checked["sentence"], passage, checked["valid"]
            )
        if result.get("ask") == "person":
            result["source_choices"] = []
            for survivor in result.get("survivors", []):
                passage = next(p for p in candidates
                               if p["passage_id"] == survivor["passage_id"])
                preview = source_preview(survivor["sentence"], passage, True)
                preview["judgment"] = survivor["judgment"]
                result["source_choices"].append(preview)
        result["elapsed_total_seconds"] = round(time.monotonic() - start_time, 6)
        if relevance_elapsed is not None:
            result["elapsed_relevance_seconds"] = round(relevance_elapsed, 6)
        return result

    def _attach_trace(result):
        result["candidates"] = [_candidate_summary(c) for c in candidates]
        result["meaning_checks"] = meaning_checks
        return result

    if isinstance(allowed_files, (list, tuple)):
        file_id_for_errors = ",".join(str(item) for item in allowed_files)
    else:
        file_id_for_errors = str(allowed_files)

    if not isinstance(question, str) or not question.strip():
        return _finish(_error_result(
            file_id_for_errors,
            question or "",
            "none",
            client,
            "refused",
            "find requires a non-empty question",
            evidence=evidence,
            request_mode=request_mode,
        ))

    if (
        isinstance(max_candidates, bool)
        or not isinstance(max_candidates, int)
        or max_candidates <= 0
    ):
        return _finish(_error_result(
            file_id_for_errors,
            question,
            "none",
            client,
            "refused",
            "max_candidates must be a positive integer",
            evidence=evidence,
            request_mode=request_mode,
        ))

    if _explicit_file_write_request(question):
        return _finish(_error_result(
            file_id_for_errors,
            question,
            "none",
            client,
            "refused",
            "find is read-only; explicit file-edit request blocked before file access",
            evidence=evidence,
            request_mode=request_mode,
        ))

    try:
        if manifest is None:
            manifest = load_manifest()
        if settings is None:
            settings = load_settings()
        passages = read_candidate_passages(
            allowed_files, manifest=manifest, settings=settings
        )
        source_read_complete = True
        candidates = nominate_candidates(
            question, passages, max_candidates=max_candidates
        )
    except (OSError, ValueError) as exc:
        return _finish(_error_result(
            file_id_for_errors,
            question,
            "none",
            client,
            "refused",
            f"find retrieval refused: {exc}",
            evidence=evidence,
            request_mode=request_mode,
        ))

    coverage = (
        f"read {len(passages)} passages from "
        f"{len(set(p['file_id'] for p in passages))} allowed files; "
        f"checking {len(candidates)} candidates"
    )

    if _is_live(client):
        try:
            identity = client.verify_model()
        except (ModelUnavailableError, ModelVerificationError) as exc:
            return _finish(_error_result(
                file_id_for_errors,
                question,
                coverage,
                client,
                "interrupted",
                str(exc),
                evidence=evidence,
                request_mode=request_mode,
            ))
        except APIFailureError as exc:
            return _finish(_error_result(
                file_id_for_errors,
                question,
                coverage,
                client,
                "unverified",
                str(exc),
                evidence=evidence,
                request_mode=request_mode,
            ))
        if not identity.get("id_matches"):
            return _finish(_error_result(
                file_id_for_errors,
                question,
                coverage,
                client,
                "refused",
                (
                    "pinned model identity mismatch: "
                    f"expected prefix {identity.get('id_prefix_expected')!r}, "
                    f"got digest {identity.get('digest', '')[:16]!r}"
                ),
                evidence=evidence,
                request_mode=request_mode,
                identity=identity,
            ))

    relevance_start = time.monotonic()

    if not candidates:
        result = _error_result(
            file_id_for_errors,
            question,
            coverage,
            client,
            "not_found",
            "no candidate passages were available",
            evidence=evidence,
            request_mode=request_mode,
        )
        result["candidates"] = []
        result["meaning_checks"] = []
        return _finish(result, 0.0)

    survivors: List[Dict[str, Any]] = []
    invalid_checks: List[Dict[str, Any]] = []
    invalid_competitors: List[Dict[str, Any]] = []

    for candidate in candidates:
        sentence_options = _candidate_sentences(candidate)
        prompt = _meaning_prompt(question, candidate)
        raw_output = None
        try:
            attempted.append(candidate["passage_id"])
            message = client.chat(
                messages=[{"role": "user", "content": prompt}],
                format_schema=MEANING_SCHEMA(sentence_options),
            )
            raw_output = message.get("raw_content", message.get("content", ""))
            content = message.get("content", "")
            if message.get("done_reason") == "length":
                return _finish(_attach_trace(_error_result(
                    file_id_for_errors,
                    question,
                    coverage,
                    client,
                    "unverified",
                    (
                        f"meaning check call for {candidate['passage_id']} "
                        "truncated before completion"
                    ),
                    evidence=evidence,
                    request_mode=request_mode,
                    model_output=raw_output,
                )), time.monotonic() - relevance_start)
            parsed = client.parse_json_content(content)
        except ModelUnavailableError as exc:
            result = _error_result(
                file_id_for_errors,
                question,
                coverage,
                client,
                "interrupted",
                str(exc),
                evidence=evidence,
                request_mode=request_mode,
            )
            return _finish(_attach_trace(result), time.monotonic() - relevance_start)
        except (APIFailureError, ValueError) as exc:
            result = _error_result(
                file_id_for_errors,
                question,
                coverage,
                client,
                "unverified",
                str(exc),
                evidence=evidence,
                request_mode=request_mode,
                model_output=raw_output,
            )
            return _finish(_attach_trace(result), time.monotonic() - relevance_start)

        checked = check_meaning_selection(parsed, candidate, sentence_options)
        meaning_check = {
                "file_id": candidate["file_id"],
                "passage_id": candidate["passage_id"],
                "file_sha256": candidate.get("file_sha256", ""),
                "score": candidate.get("score", 0),
                "judgment": checked["judgment"],
                "sentence": checked["sentence"],
                "sentence_index": checked["sentence_index"],
                "sentence_actor": checked["sentence_actor"],
                "model_output": parsed,
                "valid": checked["valid"],
                "reason": checked["reason"],
            }
        meaning_checks.append(meaning_check)

        if not checked["valid"]:
            invalid_checks.append(meaning_check)
            if checked["judgment"] != "no":
                invalid_competitors.append(meaning_check)
            continue

        if checked["judgment"] in ("yes", "unclear"):
            survivors.append(
                {
                    "file_id": candidate["file_id"],
                    "passage_id": candidate["passage_id"],
                    "file_sha256": candidate.get("file_sha256", ""),
                    "score": candidate.get("score", 0),
                    "judgment": checked["judgment"],
                    "sentence": checked["sentence"],
                }
            )

    if invalid_competitors:
        failed = invalid_competitors[0]
        result = _error_result(
            file_id_for_errors, question, coverage, client, "unverified",
            (f"meaning check failed for {failed['passage_id']}: "
             f"{failed['reason']}; possible competing answer; ask the person"),
            evidence=evidence, request_mode=request_mode,
        )
        result["candidates"] = [_candidate_summary(c) for c in candidates]
        result["meaning_checks"] = meaning_checks
        result["survivors"] = survivors
        result["ask"] = "person"
        return _finish(result, time.monotonic() - relevance_start)

    if not survivors:
        failed_reason = (
            f"meaning check failed for {invalid_checks[0]['passage_id']}: "
            f"{invalid_checks[0]['reason']}" if invalid_checks else
            "no candidate passage answered the question"
        )
        result = _error_result(
            file_id_for_errors,
            question,
            coverage,
            client,
            "unverified" if invalid_checks else "not_found",
            failed_reason,
            evidence=evidence,
            request_mode=request_mode,
        )
        result["candidates"] = [_candidate_summary(c) for c in candidates]
        result["meaning_checks"] = meaning_checks
        return _finish(result, time.monotonic() - relevance_start)

    survivors.sort(key=lambda item: (-item["score"], item["passage_id"]))
    if len(survivors) >= 2 and (survivors[0]["score"] - survivors[1]["score"]) <= 1:
        result = _error_result(
            file_id_for_errors,
            question,
            coverage,
            client,
            "ambiguous",
            "top surviving candidates are too close; ask the person to choose",
            evidence=evidence,
            request_mode=request_mode,
        )
        result["candidates"] = [_candidate_summary(c) for c in candidates]
        result["meaning_checks"] = meaning_checks
        result["survivors"] = survivors
        result["ask"] = "person"
        return _finish(result, time.monotonic() - relevance_start)

    if survivors[0]["judgment"] != "yes":
        result = _error_result(
            file_id_for_errors,
            question,
            coverage,
            client,
            "unverified",
            "no clear yes candidate; ask the person to choose",
            evidence=evidence,
            request_mode=request_mode,
        )
        result["candidates"] = [_candidate_summary(c) for c in candidates]
        result["meaning_checks"] = meaning_checks
        result["survivors"] = survivors
        result["ask"] = "person"
        return _finish(result, time.monotonic() - relevance_start)

    survivor = survivors[0]
    quote_ok, quote_reason = _check_quote(
        survivor["sentence"], survivor["passage_id"], candidates
    )
    result = _error_result(
        survivor["file_id"],
        question,
        coverage,
        client,
        "verified" if quote_ok and not invalid_checks else "unverified",
        (quote_reason if not quote_ok else
         "another candidate failed its meaning check; answer shown but not verified"
         if invalid_checks else
         "quote verified; selection is a model judgment, not proof of correctness"),
        evidence=evidence,
        request_mode=request_mode,
    )
    result["found"] = True
    result["verified"] = quote_ok and not invalid_checks
    result["answer"] = survivor["sentence"]
    result["passage_id"] = survivor["passage_id"]
    result["quote"] = survivor["sentence"]
    result["sources"] = [
        {
            "file_id": survivor["file_id"],
            "passage_id": survivor["passage_id"],
            "file_sha256": survivor.get("file_sha256", ""),
            "quote": survivor["sentence"],
            "verified": quote_ok,
        }
    ]
    result["candidates"] = [_candidate_summary(c) for c in candidates]
    result["meaning_checks"] = meaning_checks
    result["survivors"] = survivors
    return _finish(result, time.monotonic() - relevance_start)
