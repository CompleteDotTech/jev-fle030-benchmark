"""Strict, bounded TypeSafe HTTP adapter. No chat-completions shim and no fallback model."""
from __future__ import annotations
import json
import math
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any
from . import MODEL
from .util import canonical, digest

ENDPOINT = "https://api.typesafe.ai/v1/systemone"


class BudgetExceeded(RuntimeError):
    pass


class ModelProtocolError(RuntimeError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward the bearer key to a redirected host.
        raise ModelProtocolError("TypeSafe redirect refused")


def _probability(value: Any) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and 0 <= value <= 1)


def validate_response(response: Any, questions: dict, model: str) -> dict:
    if not isinstance(response, dict) or response.get("model") != model:
        raise ModelProtocolError("Missing or unexpected resolved Jev model")
    answers = response.get("answers")
    if not isinstance(answers, dict) or set(answers) != set(questions):
        raise ModelProtocolError("Response question IDs do not match the request")
    for qid, question in questions.items():
        answer = answers[qid]
        if not isinstance(answer, dict) or answer.get("type") != "choice":
            raise ModelProtocolError("Expected a typed Choice answer")
        probabilities = answer.get("probabilities")
        allowed = set(question["criteria"])
        if (not isinstance(probabilities, dict) or set(probabilities) != allowed
                or any(not _probability(v) for v in probabilities.values())
                # The provider rounds displayed probabilities to hundredths;
                # a valid large Choice response can therefore total 0.99.
                or abs(sum(probabilities.values()) - 1) > 0.015):
            raise ModelProtocolError("Invalid or incomplete probability distribution")
        choice = answer.get("choice")
        if choice not in allowed or not _probability(answer.get("confidence")):
            raise ModelProtocolError("Invalid selected option or confidence")
        if probabilities[choice] + 1e-6 < max(probabilities.values()):
            raise ModelProtocolError("Choice is not a highest-probability option")
    usage = response.get("usage")
    if not isinstance(usage, dict):
        raise ModelProtocolError("Missing token usage")
    for name in ("input_tokens", "output_tokens"):
        if not isinstance(usage.get(name), int) or isinstance(usage[name], bool) or usage[name] < 0:
            raise ModelProtocolError("Invalid token usage")
    return answers


class JevClient:
    def __init__(self, api_key: str, *, max_calls: int, model: str = MODEL,
                 emit: Callable[..., None] = lambda *a, **kw: None,
                 retries: int = 2, timeout: float = 60,
                 transport: Callable | None = None, sleeper: Callable = time.sleep):
        if not api_key.strip():
            raise ValueError("TYPESAFE_API_KEY is required; no mock fallback is permitted")
        if max_calls < 1 or not 0 <= retries <= 4 or timeout <= 0:
            raise ValueError("Invalid API budget, retry count, or timeout")
        if model != MODEL:
            raise ValueError(f"This reproducible profile requires {MODEL}")
        self._key = api_key.strip()
        self.max_calls, self.model, self.emit = max_calls, model, emit
        self.retries, self.timeout = retries, timeout
        self.calls = self.input_tokens = self.output_tokens = 0
        self._transport = transport or self._http
        self._sleep = sleeper

    def _http(self, payload: bytes) -> dict:
        request = urllib.request.Request(ENDPOINT, data=payload, method="POST", headers={
            "Authorization": f"Bearer {self._key}", "Content-Type": "application/json",
            "User-Agent": "CompleteTech-Jev-FLE030/0.1.0",
        })
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=self.timeout) as reply:
            data = reply.read(2_000_001)
            if len(data) > 2_000_000:
                raise ModelProtocolError("Oversized TypeSafe response")
            try:
                return json.loads(data)
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise ModelProtocolError("TypeSafe returned invalid JSON") from exc

    def choose(self, state: dict, questions: dict[str, dict]) -> dict[str, str]:
        if not questions:
            return {}
        for question in questions.values():
            if (question.get("type") != "choice"
                    or not 1 <= len(question.get("criteria", {})) <= 255):
                raise ValueError("Choice questions require 1–255 options")
        payload = {"model": self.model, "state": state, "questions": questions}
        encoded = canonical(payload).encode("utf-8")
        # Conservative byte guards, not a claim to implement the provider's tokenizer.
        largest = max(len(canonical(q).encode("utf-8")) for q in questions.values())
        if len(encoded) > 60_000 or len(canonical(state).encode("utf-8")) + largest > 28_000:
            raise ValueError("State/question byte guard exceeded; no silent request truncation")
        request_hash = digest(payload)
        for attempt in range(self.retries + 1):
            if self.calls >= self.max_calls:
                raise BudgetExceeded("API-call budget exhausted, including retries")
            self.calls += 1
            self.emit("api_attempt", request_hash=request_hash, attempt=attempt + 1,
                      request=payload, call_number=self.calls)
            start = time.monotonic()
            try:
                response = self._transport(encoded)
                answers = validate_response(response, questions, self.model)
                self.input_tokens += response["usage"]["input_tokens"]
                self.output_tokens += response["usage"]["output_tokens"]
                self.emit("api_response", request_hash=request_hash,
                          latency_seconds=time.monotonic() - start, response=response)
                return {qid: answer["choice"] for qid, answer in answers.items()}
            except urllib.error.HTTPError as exc:
                # Do not log response bodies or HTTP headers: they may reflect secrets.
                self.emit("api_error", request_hash=request_hash, status=exc.code,
                          latency_seconds=time.monotonic() - start)
                if exc.code not in {429, 500, 502, 503, 504, 529} or attempt == self.retries:
                    raise RuntimeError(f"TypeSafe HTTP {exc.code}; benchmark episode interrupted") from None
                try:
                    delay = float(exc.headers.get("Retry-After", "0"))
                    if not math.isfinite(delay):
                        delay = 0
                except (ValueError, AttributeError):
                    delay = 0
                self._sleep(min(30, max(0.5 * 2 ** attempt, delay)))
            except ModelProtocolError:
                # A provider response can be incomplete or inconsistent. Keep
                # the guard strict, but allow a bounded fresh attempt.
                self.emit("api_error", request_hash=request_hash, status="protocol_error")
                if attempt == self.retries:
                    raise
                self._sleep(min(8, 0.5 * 2 ** attempt))
            except (urllib.error.URLError, TimeoutError, OSError):
                self.emit("api_error", request_hash=request_hash, status="transport_error")
                if attempt == self.retries:
                    raise RuntimeError("TypeSafe transport failed; benchmark episode interrupted") from None
                self._sleep(min(8, 0.5 * 2 ** attempt))
        raise AssertionError("Unreachable retry state")


class RandomClient:
    """Explicit diagnostic baseline, NEVER substituted for a live Jev failure."""
    def __init__(self, rng):
        self.rng = rng
        self.calls = self.input_tokens = self.output_tokens = 0

    def choose(self, state, questions):
        return {name: self.rng.choice(list(q["criteria"])) for name, q in questions.items()}
