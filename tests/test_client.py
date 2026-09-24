import copy
import json
import urllib.error
import pytest
from jev_fle import MODEL
from jev_fle.client import JevClient, ModelProtocolError, BudgetExceeded, NoRedirect, validate_response

Q = {"pick": {"type": "choice", "instructions": "Pick", "criteria": {"a": "A", "b": "B"}}}


def response():
    return {"model": MODEL, "answers": {"pick": {"type": "choice", "choice": "a",
            "probabilities": {"a": 0.8, "b": 0.2}, "confidence": 0.7}},
            "usage": {"input_tokens": 100, "output_tokens": 10}}


def test_valid_response():
    assert validate_response(response(), Q, MODEL)["pick"]["choice"] == "a"


@pytest.mark.parametrize("mutation", [
    lambda r: r.update(model="jev-latest"),
    lambda r: r.update(answers={}),
    lambda r: r["answers"].update(extra={}),
    lambda r: r["answers"]["pick"].update(type="noul"),
    lambda r: r["answers"]["pick"].update(choice="evil"),
    lambda r: r["answers"]["pick"].update(choice="b"),
    lambda r: r["answers"]["pick"].update(probabilities={"a": 1}),
    lambda r: r["answers"]["pick"].update(probabilities={"a": float("nan"), "b": 0.2}),
    lambda r: r["answers"]["pick"].update(probabilities={"a": 0.1, "b": 0.2}),
    lambda r: r["answers"]["pick"].update(probabilities={"a": True, "b": 0}),
    lambda r: r["answers"]["pick"].update(confidence=1.1),
    lambda r: r["answers"]["pick"].update(confidence=None),
    lambda r: r.pop("usage"),
    lambda r: r["usage"].update(input_tokens=-1),
    lambda r: r["usage"].update(input_tokens=True),
])
def test_malformed_response_rejected(mutation):
    value = response()
    mutation(value)
    with pytest.raises(ModelProtocolError):
        validate_response(value, Q, MODEL)


def test_no_mock_fallback_without_key():
    with pytest.raises(ValueError, match="required"):
        JevClient("", max_calls=2)


def test_exact_model_pin():
    with pytest.raises(ValueError, match="requires"):
        JevClient("fixture-key", max_calls=2, model="jev-latest")


def test_payload_and_budget_receipts_without_secret():
    events = []
    def transport(payload):
        assert json.loads(payload)["model"] == MODEL
        assert b"fixture-key" not in payload
        return response()
    client = JevClient("fixture-key", max_calls=1, transport=transport,
                       emit=lambda event, **data: events.append({"event": event, **data}))
    assert client.choose({"x": 1}, Q) == {"pick": "a"}
    with pytest.raises(BudgetExceeded):
        client.choose({"x": 1}, Q)
    assert [e["event"] for e in events] == ["api_attempt", "api_response"]
    assert client.calls == 1 and client.input_tokens == 100
    assert "fixture-key" not in json.dumps(events)


def test_retry_budget_counts_each_attempt():
    attempts, sleeps = [], []
    def transport(payload):
        attempts.append(payload)
        raise urllib.error.HTTPError("https://api.typesafe.ai", 429, "fixture secret must not be logged", {}, None)
    c = JevClient("fixture-key", max_calls=2, retries=4, transport=transport, sleeper=sleeps.append)
    with pytest.raises(BudgetExceeded):
        c.choose({}, Q)
    assert c.calls == 2 and len(attempts) == 2


def test_retry_recovers_with_bounded_backoff():
    attempts, sleeps = [], []
    def transport(payload):
        attempts.append(payload)
        if len(attempts) == 1:
            raise urllib.error.HTTPError("https://api.typesafe.ai", 529, "busy", {"Retry-After": "1000"}, None)
        return response()
    c = JevClient("fixture-key", max_calls=2, transport=transport, sleeper=sleeps.append)
    assert c.choose({}, Q) == {"pick": "a"}
    assert sleeps == [30] and c.calls == 2


def test_invalid_provider_distribution_gets_one_fresh_attempt():
    attempts, events = [], []
    def transport(payload):
        attempts.append(payload)
        bad = response()
        if len(attempts) == 1:
            bad["answers"]["pick"]["probabilities"]["a"] = 0.1
        return bad
    c = JevClient("fixture-key", max_calls=2, retries=1, transport=transport,
                  sleeper=lambda seconds: None,
                  emit=lambda event, **data: events.append((event, data)))
    assert c.choose({}, Q) == {"pick": "a"}
    assert c.calls == 2
    assert [event for event, _ in events] == ["api_attempt", "api_error", "api_attempt", "api_response"]
    assert events[1][1]["status"] == "protocol_error"


def test_auth_errors_do_not_retry_or_reflect_body():
    def transport(payload):
        raise urllib.error.HTTPError("https://api.typesafe.ai", 401, "fixture-key", {}, None)
    c = JevClient("fixture-key", max_calls=3, transport=transport)
    with pytest.raises(RuntimeError, match="HTTP 401") as err:
        c.choose({}, Q)
    assert "fixture-key" not in str(err.value) and c.calls == 1


def test_size_guard_precedes_transport():
    c = JevClient("fixture-key", max_calls=1, transport=lambda payload: pytest.fail("Unexpected HTTP attempt"))
    with pytest.raises(ValueError, match="byte guard"):
        c.choose({"text": "z" * 30000}, Q)
    assert c.calls == 0


def test_redirect_refused():
    with pytest.raises(ModelProtocolError, match="redirect"):
        NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://untrusted.test")


def test_empty_question_batch_is_free():
    c = JevClient("fixture-key", max_calls=1)
    assert c.choose({}, {}) == {} and c.calls == 0
