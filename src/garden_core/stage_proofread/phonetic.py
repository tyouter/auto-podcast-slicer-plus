"""Phonetic: detect + (where unambiguous) fix ASR phonetic-confusion errors.

This is the DETECT side (fixes the legacy split where errata_engine mixed
apply and validate). Inspired by legacy word_verifier: forward-max-match
tokenize unknown words, then flag them against pinyin confusion groups
(zh↔z, ch↔c, sh↔s, n↔l, f↔h, an↔ang …). Unambiguous single-candidate fixes
are applied; ambiguous ones are only reported (returned as issues) so the LLM
corrector or a human can decide.

Kept deliberately lightweight for the first release — no pinyin library
dependency; we use a small rule table. A full jieba/pypinyin pass is a later
enhancement.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Tuple

from garden_core.types import Segment, Transcript

log = logging.getLogger(__name__)

__all__ = ["PhoneticIssue", "fix_phonetic_in_segments", "detect_phonetic_issues"]


@dataclass(frozen=True)
class PhoneticIssue:
    entry_index: int
    wrong: str
    suggestion: str
    confidence: float
    description: str


# Common, high-confidence ASR confusions for Mandarin (unambiguous → fixable).
# These are pairs where one form is almost always wrong in podcast speech.
_HIGH_CONFIDENCE_FIXES: dict[str, str] = {
    "确实施": "确实是",  # placeholder example of the pattern
}

# Confusion groups (for detection; not auto-fixed).
_CONFUSION_GROUPS = (
    ("zh", "z"), ("ch", "c"), ("sh", "s"),
    ("n", "l"), ("f", "h"), ("an", "ang"), ("en", "eng"), ("in", "ing"),
)


def detect_phonetic_issues(text: str) -> list[tuple[str, str]]:
    """Return [(wrong_substring, suggestion), ...] for likely phonetic errors.

    First release: only the high-confidence fix table triggers. Ambiguous
    pinyin-confusion detection (full forward-max-match) is deferred.
    """
    out: list[tuple[str, str]] = []
    for wrong, correct in _HIGH_CONFIDENCE_FIXES.items():
        if wrong in text:
            out.append((wrong, correct))
    return out


def fix_phonetic_in_segments(transcript: Transcript) -> Tuple[Transcript, int]:
    """Apply high-confidence phonetic fixes. Returns (new transcript, n_changes)."""
    from dataclasses import replace as _replace
    total = 0
    new_segs: list[Segment] = []
    for seg in transcript.segments:
        text = seg.text
        for wrong, correct in _HIGH_CONFIDENCE_FIXES.items():
            if wrong in text:
                text = text.replace(wrong, correct)
                total += 1
        new_segs.append(_replace(seg, text=text) if text != seg.text else seg)
    return _replace(transcript, segments=tuple(new_segs)), total
