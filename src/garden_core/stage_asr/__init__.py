"""Stage 1: speech recognition.

Public contract::

    def transcribe(audio: AudioRef, engine: Transcriber,
                   hotwords: list[str] = ()) -> Transcript

Engines are stateful objects (model loaded once, reused) injected by the
caller — never constructed per-call.

**Standard backend**: ``FunASRLocal`` (``funasr_local.py``) — loads
Paraformer+VAD+Punc+SPK models directly on the local GPU via
``funasr.AutoModel``.  Zero network overhead, RTF ~0.03 on CUDA.  This is the
Windows-native single-machine backend; inject it as the ``Transcriber``.

The MCP backends (``FunASRMCPBackend``, legacy ``FunASRBackend``) have been
retired and deleted — the HTTP/MCP transport existed only to bridge a
containerised Python that couldn't reach the GPU, which no longer applies.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from garden_core.types import Transcript

__all__ = ["AudioRef", "Transcriber", "transcribe", "FunASRLocal"]


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


# Imported last: ``funasr_local`` imports ``AudioRef``/``Transcriber`` from this
# package, so it must load only after they are defined above.
from garden_core.stage_asr.funasr_local import FunASRLocal  # noqa: E402
