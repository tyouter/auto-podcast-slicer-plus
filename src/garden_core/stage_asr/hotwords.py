"""Hot-word injection (BibbGPT borrow).

Podcast-specific proper nouns (host/guest names, show title, technical terms)
are often mistranscribed by ASR. BibiGPT showed that injecting a hot-word list
before transcription materially lifts accuracy at ~20% extra ASR cost.

Here hotwords are just a tuple of strings carried alongside the ASR request;
backends that support a hot-word / biasing parameter (FunASR hotword_url, or a
system-prompt hint) consume it. Backends that don't simply ignore it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

__all__ = ["load_hotwords", "hotwords_to_hint"]


def load_hotwords(source) -> tuple[str, ...]:
    """Load hotwords from a file (one per line) or an iterable of strings."""
    if not source:
        return ()
    if isinstance(source, (str, Path)):
        p = Path(source)
        if not p.exists():
            return ()
        words = [w.strip() for w in p.read_text(encoding="utf-8").splitlines()
                 if w.strip() and not w.strip().startswith("#")]
        return tuple(dict.fromkeys(words))  # dedupe, preserve order
    return tuple(dict.fromkeys(str(w).strip() for w in source if str(w).strip()))


def hotwords_to_hint(hotwords: Iterable[str]) -> str:
    """Format hotwords as a guidance hint for backends that take a text prompt."""
    hw = [w for w in hotwords if w]
    if not hw:
        return ""
    return "专有名词/热词(优先按此拼写): " + "、".join(hw)
