"""LLM gateway: the key fix is that 'LLM unavailable' is NEVER a silent pass."""

from __future__ import annotations

from garden_core.infra.llm_client import LLMClient, LLMOutcome, LLMResponse, NoLLMClient


def test_no_api_key_is_unavailable_not_ok():
    """Without a key, the call must be UNAVAILABLE — callers cannot treat as pass."""
    client = LLMClient(api_key="")
    assert not client.available
    resp = client.chat([{"role": "user", "content": "hi"}])
    assert resp.outcome is LLMOutcome.UNAVAILABLE
    assert not resp.ok


def test_nollmclient_is_unavailable():
    client = NoLLMClient()
    assert not client.available
    resp = client.chat([{"role": "user", "content": "hi"}])
    assert resp.outcome is LLMOutcome.UNAVAILABLE


def test_raise_if_unavailable_raises():
    """Quality gates that would otherwise false-PASS must fail loudly."""
    resp = LLMResponse(outcome=LLMOutcome.UNAVAILABLE, error="no key")
    import pytest
    with pytest.raises(RuntimeError):
        resp.raise_if_unavailable()


def test_chat_json_degrades_on_garbage(monkeypatch):
    """A successful HTTP call returning non-JSON → DEGRADED, content preserved."""
    client = LLMClient(api_key="fake-key-for-test")

    # Stub chat() to return OK with garbage content, bypassing the network.
    def fake_chat(messages, **kwargs):
        return LLMResponse(outcome=LLMOutcome.OK, content="not json at all", attempts=1)
    monkeypatch.setattr(client, "chat", fake_chat)

    resp, parsed = client.chat_json([{"role": "user", "content": "x"}])
    assert parsed is None
    assert resp.outcome is LLMOutcome.DEGRADED
    assert resp.content == "not json at all"  # preserved for debugging


def test_chat_json_parses_fenced(monkeypatch):
    """```json fences stripped before parsing."""
    client = LLMClient(api_key="fake-key-for-test")

    def fake_chat(messages, **kwargs):
        return LLMResponse(
            outcome=LLMOutcome.OK,
            content='```json\n{"score": 8}\n```',
            attempts=1,
        )
    monkeypatch.setattr(client, "chat", fake_chat)

    resp, parsed = client.chat_json([{"role": "user", "content": "x"}])
    assert resp.ok
    assert parsed == {"score": 8}
