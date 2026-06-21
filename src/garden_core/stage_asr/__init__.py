"""Stage 1: speech recognition.

Public contract::

    def transcribe(audio: AudioRef, engine: Transcriber,
                   hotwords: list[str] = ()) -> Transcript

Engines are stateful objects (model loaded once, reused) injected by the
caller — never constructed per-call.

**Default**: no backend shipped in the base package.  The caller injects any
``Transcriber`` implementation.  Two production backends are available:

* ``FunASRLocal`` (in ``tests/smoke_full_pipeline_local.py``) — loads
  Paraformer+VAD+Punc+SPK models directly on GPU via ``funasr.AutoModel``.
  Zero network overhead, RTF ~0.03 on CUDA.  Ideal for single-machine
  batch processing.

* ``FunASRMCPBackend`` (``funasr_mcp_backend.py``) — connects to a
  separately-hosted FunASR MCP server (start ``mcp-server-funasr/main.py``
  first).  Useful for multi-client / containerised deployments where the
  GPU lives on a dedicated host.

The legacy ``FunASRBackend`` (``funasr_backend.py``) with a hand-rolled
``_MCP`` client is kept for reference; prefer ``FunASRMCPBackend`` for new
MCP integrations (it uses the official ``fastmcp.Client``).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from garden_core.types import Transcript

__all__ = ["AudioRef", "Transcriber", "transcribe"]


@dataclass(frozen=True)
class AudioRef:
    """A reference to source audio (path or pre-extracted wav)."""

    path: str
    duration_s: Optional[float] = None  # known duration, or None to probe


class Transcriber(ABC):
    """Abstract ASR backend. Stateful — load model once, reuse across calls."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def transcribe(self, audio: AudioRef, hotwords: tuple[str, ...] = ()) -> Transcript:
        ...


def transcribe(
    audio: AudioRef,
    engine: Transcriber,
    hotwords: tuple[str, ...] | list[str] = (),
) -> Transcript:
    """Run stage 1: audio → Transcript (seconds-based, no words yet)."""
    return engine.transcribe(audio, tuple(hotwords))
