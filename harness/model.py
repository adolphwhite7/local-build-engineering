"""Ollama client with strict local-only guarantees.

* Host is the literal ``127.0.0.1:11434``; no proxies, redirects, or
  remote-host overrides are honoured.
* No download or daemon change is attempted.
* One pinned model per call; no tool calling, shell execution, or
  generated code execution.
* ``send_think_false`` adds ``think: false`` to the request body; a compatibility
  mode omits that field and strips a leading ``<thinking...>`` block instead.
"""

import json
import re
import socket
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional


class ModelUnavailableError(Exception):
    """Raised when the local Ollama server cannot be reached or times out."""


class ModelVerificationError(Exception):
    """Raised when the pinned model is not present or wrong version."""


class APIFailureError(Exception):
    """Raised when the API returns an unexpected or malformed response.

    ``status_code`` is set when the failure originated from an HTTP error.
    """

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Handler that refuses HTTP redirects rather than following them."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(
            req.get_full_url(),
            code,
            f"HTTP redirect to {newurl} is blocked",
            headers,
            fp,
        )


# Reasoning-block markers stripped in compatibility mode.  Both the short
# ``think`` and the longer ``thinking`` tag names are accepted; each must be
# enclosed in angle brackets with its own matching closing tag.
_THINKING_MARKER_NAMES = ("thinking", "think")


def _open_marker(name: str) -> str:
    return f"\u003c{name}\u003e"


def _close_marker(name: str) -> str:
    return f"\u003c/{name}\u003e"


def _has_thinking_marker(raw_content: Any) -> bool:
    """Return True when the raw assistant content starts with a known
    complete-leading reasoning marker (``<think>`` or ``<thinking>``).
    """
    if not isinstance(raw_content, str):
        return False
    trimmed = raw_content.lstrip()
    return any(
        trimmed.startswith(_open_marker(name)) for name in _THINKING_MARKER_NAMES
    )


def _observed_thinking(raw_content: Any, content: Any, thinking: Any) -> bool:
    """Return True when raw output shows reasoning before stripping."""
    if isinstance(thinking, str) and thinking:
        return True
    if _has_thinking_marker(raw_content):
        return True
    if isinstance(raw_content, str) and isinstance(content, str):
        return content.lstrip() != raw_content.lstrip()
    return False


def _strip_think(content: str) -> str:
    """Remove a single leading reasoning block if present.

    Compatibility mode uses deterministic stripping.  Only *complete*
    leading blocks are removed; malformed or unclosed markers are left in
    place so that parsing can report them as malformed output.
    """
    if not isinstance(content, str):
        raise APIFailureError(
            f"message content is not a string (got {type(content).__name__})"
        )

    content = content.lstrip()

    # HTML-style <thinking>...</thinking> and <think>...</think> blocks.
    for name in _THINKING_MARKER_NAMES:
        open_marker = _open_marker(name)
        close_marker = _close_marker(name)
        if content.startswith(open_marker):
            end = content.find(close_marker)
            if end != -1:
                content = content[end + len(close_marker):]
                return content.lstrip()

    # Markdown fenced code block with an optional "thinking" info string.
    fence = re.match(
        r"^(````*|~~~+)(?:[ \t]*thinking[^\n]*)?[ \t]*\r?\n(.*?)(?:\r?\n)\1[ \t]*(?:\r?\n|$)",
        content,
        re.IGNORECASE | re.DOTALL,
    )
    if fence:
        content = content[fence.end():].lstrip()
        return content

    # Single-line inline backtick block whose first word is "thinking".
    inline = re.match(
        r"^(`+)[ \t]*thinking[ \t]+[^`\n]*\1",
        content,
        re.IGNORECASE,
    )
    if inline:
        content = content[inline.end():].lstrip()

    return content.lstrip()


def LOCAL_OLLAMA_SCHEMA() -> Dict[str, Any]:
    """JSON-schema for the expected structured output."""
    return {
        "type": "object",
        "properties": {
            "answer": {"type": "string"},
            "quote": {"type": "string"},
            "passage_id": {"type": "string"},
            "found": {"type": "boolean"},
        },
        "required": ["answer", "quote", "passage_id", "found"],
        "additionalProperties": False,
    }


class OllamaClient:
    """Minimal client for ``/api/chat`` on the pinned local model."""

    def __init__(
        self,
        settings: Dict[str, Any],
        *,
        compatibility_mode: bool = False,
    ):
        self.cfg = settings.get("model", {})
        # Enforce literal local host/port in code regardless of settings.
        self.host = "127.0.0.1"
        self.port = 11434
        self.tag = self.cfg.get("tag", "deepseek-r1:1.5b")
        self.id_prefix = self.cfg.get("id_prefix", "")
        self.timeout = float(self.cfg.get("timeout", 120))
        self.temperature = self.cfg.get("temperature", 0)
        self.seed = self.cfg.get("seed", 42)
        self.num_ctx = self.cfg.get("num_ctx", 2048)
        self.num_predict = self.cfg.get("num_predict", 8192)
        self.send_think_false = (
            not compatibility_mode
            and self.cfg.get("send_think_false", True)
        )
        self.compatibility_mode = compatibility_mode

    def _url(self, path: str) -> str:
        return f"http://{self.host}:{self.port}{path}"

    @staticmethod
    def _build_opener() -> urllib.request.OpenerDirector:
        """Build an opener with default HTTP processing, no redirects, no proxy."""
        return urllib.request.build_opener(
            urllib.request.ProxyHandler({}),  # ignore *_proxy env vars
            _NoRedirectHandler(),
        )

    def _request(self, path: str, payload: Optional[bytes] = None) -> str:
        """Make a request and return the decoded body.

        HTTP errors are reported as ``APIFailureError`` with the actual status
        code before URLError-style unreachability is considered.
        """
        req = urllib.request.Request(
            self._url(path),
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Content-Length": str(len(payload) if payload is not None else 0),
            },
            method="POST" if payload is not None else "GET",
        )
        opener = self._build_opener()
        try:
            with opener.open(req, timeout=self.timeout) as response:
                return response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read(1024).decode("utf-8", errors="replace")
            except Exception:
                pass
            message = f"Ollama returned HTTP {exc.code}: {exc.reason}"
            if body:
                message = f"{message}: {body[:256]}"
            raise APIFailureError(message, status_code=exc.code) from exc
        except (socket.timeout, TimeoutError) as exc:
            raise ModelUnavailableError(
                f"Ollama request timed out at {self.host}:{self.port}: {exc}"
            ) from exc
        except urllib.error.URLError as exc:
            raise ModelUnavailableError(
                f"Cannot reach Ollama at {self.host}:{self.port}: {exc}"
            ) from exc

    def chat(
        self,
        messages: List[Dict[str, str]],
        format_schema: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Send one chat request to ``/api/chat`` and return the message."""
        body: Dict[str, Any] = {
            "model": self.tag,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "seed": self.seed,
                "num_ctx": self.num_ctx,
                "num_predict": self.num_predict,
            },
        }
        if format_schema is not None:
            body["format"] = format_schema
        if self.send_think_false:
            body["think"] = False

        raw = self._request("/api/chat", json.dumps(body).encode("utf-8"))
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise APIFailureError(f"Ollama returned non-JSON: {exc}") from exc

        if not isinstance(data, dict):
            raise APIFailureError("Ollama /api/chat response is not a JSON object")

        message = data.get("message")
        if not isinstance(message, dict):
            raise APIFailureError("Ollama /api/chat response missing message object")

        raw_content = message.get("content", "")
        if not isinstance(raw_content, str):
            raise APIFailureError(
                f"Ollama /api/chat message.content is not a string "
                f"(got {type(raw_content).__name__}): {raw!r}"
            )
        thinking = message.get("thinking")
        if self.compatibility_mode:
            content = _strip_think(raw_content)
        else:
            content = raw_content
        message["content"] = content
        message["raw_content"] = raw_content
        # Diagnostic metadata is not evidence that the answer is valid.
        message["eval_count"] = data.get("eval_count")
        message["done_reason"] = data.get("done_reason")
        return message

    def parse_json_content(self, content: Any) -> Dict[str, Any]:
        """Parse model output as JSON."""
        if not isinstance(content, str):
            raise APIFailureError(
                f"Model output is not a string (got {type(content).__name__})"
            )
        try:
            return json.loads(content.strip())
        except json.JSONDecodeError as exc:
            raise APIFailureError(f"Model output is not valid JSON: {exc}") from exc

    def runtime_version(self) -> str:
        """Return the Ollama runtime version string, or '?'."""
        try:
            raw = self._request("/api/version")
            data = json.loads(raw)
            if isinstance(data, dict):
                return data.get("version", "?")
        except (APIFailureError, ModelUnavailableError):
            pass
        return "?"

    def verify_model(self) -> Dict[str, Any]:
        """Probe ``/api/tags`` to confirm the pinned model is present."""
        raw = self._request("/api/tags")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise APIFailureError(f"/api/tags returned non-JSON: {exc}") from exc

        if not isinstance(data, dict):
            raise APIFailureError("/api/tags response is not a JSON object")

        models = data.get("models", [])
        if not isinstance(models, list):
            raise APIFailureError("/api/tags 'models' field is not a list")

        found = None
        for m in models:
            if not isinstance(m, dict):
                continue
            name = m.get("name") or m.get("model")
            if name == self.tag:
                found = m
                break

        if found is None:
            raise ModelVerificationError(
                f"Pinned model {self.tag} is not loaded"
            )

        digest = found.get("digest", "")
        if not isinstance(digest, str):
            raise APIFailureError("Pinned model digest is not a string")

        # A recorded full SHA-256 pin requires equality. Retain shorter-prefix
        # compatibility for existing diagnostic fixtures, not the pilot pin.
        id_matches = (
            digest == self.id_prefix if len(self.id_prefix) == 64
            else bool(self.id_prefix) and digest.startswith(self.id_prefix)
        )
        return {
            "tag": self.tag,
            "digest": digest,
            "id_prefix_expected": self.id_prefix,
            "id_matches": id_matches,
        }

    def probe_chat_test(self) -> Dict[str, Any]:
        """Make one small chat call to exercise the submitted schema.

        Returns parsed content, schema validity, and observed thinking.
        """
        from .check import validate_ollama_output

        messages = [
            {
                "role": "user",
                "content": (
                    "Return a JSON object with answer '', quote '', "
                    "passage_id '', and found false."
                ),
            }
        ]
        message = self.chat(messages, format_schema=LOCAL_OLLAMA_SCHEMA())
        raw_content = message.get("raw_content", message.get("content", ""))
        observed_thinking = _observed_thinking(
            raw_content,
            message.get("content", ""),
            message.get("thinking"),
        )
        parsed = None
        parse_error = None
        try:
            parsed = self.parse_json_content(message.get("content", ""))
        except APIFailureError as exc:
            parse_error = str(exc)

        schema_ok, _, _ = validate_ollama_output(parsed)
        thinking = message.get("thinking")
        return {
            "content": message.get("content", ""),
            "raw_content": raw_content,
            "parsed": parsed,
            "parse_error": parse_error,
            "schema_ok": schema_ok,
            "observed_thinking": observed_thinking,
            "thinking_length": len(thinking) if isinstance(thinking, str) else None,
            "raw_content_length": len(raw_content) if isinstance(raw_content, str) else None,
            "eval_count": message.get("eval_count"),
            "done_reason": message.get("done_reason"),
            "num_predict": self.num_predict,
        }


class FakeOllamaClient:
    """Deterministic stand-in for the Ollama client.

    The harness owns the result; the model output is supplied by the test
    or operator. This class never reaches the network.  It shares JSON and
    API error semantics with the live client.
    """

    def __init__(
        self,
        payload: Any,
        *,
        compatibility_mode: bool = False,
        tag: str = "fake",
    ):
        self.payload = payload
        self.last_call: Optional[Dict[str, Any]] = None
        self.cfg = {"host": "127.0.0.1", "port": 11434}
        self.tag = tag
        self.id_prefix = ""
        self.compatibility_mode = compatibility_mode
        self.send_think_false = not compatibility_mode

    def chat(
        self,
        messages: List[Dict[str, str]],
        format_schema: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Return fake content."""
        self.last_call = {"messages": messages, "format": format_schema}
        if callable(self.payload):
            content = self.payload(messages, format_schema)
        elif isinstance(self.payload, dict):
            content = json.dumps(self.payload)
        elif isinstance(self.payload, str):
            if self.payload == "timeout":
                raise ModelUnavailableError("fake timeout")
            if self.payload == "unreachable":
                raise ModelUnavailableError("fake unreachable")
            if self.payload == "unsupported_thinking":
                raise APIFailureError(
                    "Ollama returned HTTP 400: think field not supported",
                    status_code=400,
                )
            content = self.payload
        else:
            content = json.dumps(self.payload)
        if not isinstance(content, str):
            raise APIFailureError(
                f"fake client produced non-string content ({type(content).__name__})"
            )
        raw_content = content
        if self.compatibility_mode:
            content = _strip_think(content)
        message = {
            "role": "assistant",
            "content": content,
            "raw_content": raw_content,
        }
        return message

    def parse_json_content(self, content: Any) -> Dict[str, Any]:
        if not isinstance(content, str):
            raise APIFailureError(
                f"Model output is not a string (got {type(content).__name__})"
            )
        try:
            return json.loads(content.strip())
        except json.JSONDecodeError as exc:
            raise APIFailureError(f"Model output is not valid JSON: {exc}") from exc

    def verify_model(self) -> Dict[str, Any]:
        if self.payload == "unreachable":
            raise ModelUnavailableError("fake unreachable")
        return {
            "tag": self.tag,
            "digest": "fake",
            "id_prefix_expected": "",
            "id_matches": False,
        }

    def probe_chat_test(self) -> Dict[str, Any]:
        """Fake probe: one chat call to exercise schema/thinking handling."""
        from .check import validate_ollama_output

        messages = [
            {
                "role": "user",
                "content": (
                    "Return a JSON object with answer '', quote '', "
                    "passage_id '', and found false."
                ),
            }
        ]
        message = self.chat(messages, format_schema=LOCAL_OLLAMA_SCHEMA())
        raw_content = message.get("raw_content", message.get("content", ""))
        observed_thinking = _observed_thinking(
            raw_content,
            message.get("content", ""),
            message.get("thinking"),
        )
        parsed = None
        parse_error = None
        try:
            parsed = self.parse_json_content(message.get("content", ""))
        except APIFailureError as exc:
            parse_error = str(exc)

        schema_ok, _, _ = validate_ollama_output(parsed)
        return {
            "content": message.get("content", ""),
            "raw_content": raw_content,
            "parsed": parsed,
            "parse_error": parse_error,
            "schema_ok": schema_ok,
            "observed_thinking": observed_thinking,
        }

    def runtime_version(self) -> str:
        return "fake"
