"""Tests for Engines.from_env() — env/API key injection helper (T2)."""

import os
import tempfile
from unittest.mock import patch

import pytest

from garden_core.infra.llm_client import LLMClient, NoLLMClient
from garden_core.pipeline import Engines


# --------------------------------------------------------------------------- #
# Scenario 1: DEEPSEEK_API_KEY in os.environ → real LLMClient
# --------------------------------------------------------------------------- #
def test_from_env_key_in_environment():
    """When DEEPSEEK_API_KEY is in os.environ, from_env returns LLMClient."""
    with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-test-123"}, clear=True):
        engines = Engines.from_env()

    assert not isinstance(engines.llm, NoLLMClient)
    assert isinstance(engines.llm, LLMClient)
    assert engines.llm.default_model == "deepseek-chat"
    assert engines.llm.timeout == 300.0
    assert engines.transcriber is None
    assert engines.aligner is None
    assert engines.style_resolver is None


# --------------------------------------------------------------------------- #
# Scenario 2: DEEPSEEK_API_KEY in a .env file → merge → real LLMClient
# --------------------------------------------------------------------------- #
def test_from_env_key_in_dotenv_file():
    """When env_path points to a .env with the key, it is merged and used."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".env", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write("# comment line\n")
        tmp.write("DEEPSEEK_API_KEY=sk-dotenv-456\n")
        tmp.write("\n")  # blank line
        tmp.write("OTHER_VAR=ignored\n")
        env_path = tmp.name

    try:
        # Clear the key from the live environment so we know it came from the file
        with patch.dict(os.environ, {}, clear=True):
            engines = Engines.from_env(env_path=env_path)

        assert not isinstance(engines.llm, NoLLMClient)
        assert isinstance(engines.llm, LLMClient)
        assert engines.llm.default_model == "deepseek-chat"
        assert engines.llm.timeout == 300.0
    finally:
        os.unlink(env_path)


# --------------------------------------------------------------------------- #
# Scenario 3: no DEEPSEEK_API_KEY anywhere → NoLLMClient (no exception)
# --------------------------------------------------------------------------- #
def test_from_env_no_key_degrades_gracefully():
    """Without DEEPSEEK_API_KEY, from_env returns NoLLMClient — no exception."""
    with patch.dict(os.environ, {}, clear=True):
        engines = Engines.from_env(env_path=None)

    assert isinstance(engines.llm, NoLLMClient)
    # Must not raise — the call itself succeeds, LLM layer reports UNAVAILABLE later
    assert engines.transcriber is None
    assert engines.aligner is None


# --------------------------------------------------------------------------- #
# Edge: custom llm_default_model and llm_timeout are forwarded
# --------------------------------------------------------------------------- #
def test_from_env_custom_model_and_timeout():
    """llm_default_model and llm_timeout are forwarded to LLMClient."""
    with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-custom"}, clear=True):
        engines = Engines.from_env(
            llm_default_model="gpt-4o",
            llm_timeout=60.0,
        )

    assert isinstance(engines.llm, LLMClient)
    assert engines.llm.default_model == "gpt-4o"
    assert engines.llm.timeout == 60.0


# --------------------------------------------------------------------------- #
# Edge: env_path pointing to a non-existent file is a no-op
# --------------------------------------------------------------------------- #
def test_from_env_missing_env_file_no_error():
    """A missing env_path should not raise — it's silently skipped."""
    with patch.dict(os.environ, {}, clear=True):
        engines = Engines.from_env(env_path="/nonexistent/path/.env")

    assert isinstance(engines.llm, NoLLMClient)


# --------------------------------------------------------------------------- #
# Regression: transcriber / aligner / style_resolver are passed through
# --------------------------------------------------------------------------- #
def test_from_env_passthrough_heavy_engines():
    """transcriber, aligner, style_resolver are forwarded verbatim."""

    class FakeTranscriber:
        pass

    class FakeAligner:
        pass

    class FakeStyleResolver:
        pass

    t = FakeTranscriber()
    a = FakeAligner()
    s = FakeStyleResolver()

    with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk"}, clear=True):
        engines = Engines.from_env(transcriber=t, aligner=a, style_resolver=s)

    assert engines.transcriber is t
    assert engines.aligner is a
    assert engines.style_resolver is s
