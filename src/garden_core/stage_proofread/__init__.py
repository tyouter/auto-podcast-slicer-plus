"""Stage 3: text proofreading.

Fixes the legacy errata/content_validator/text_corrector/word_verifier tangle:
  * ``errata`` owns *apply* (deterministic corrections) only.
  * ``phonetic`` owns *detect* (phonetic-confusion reports) only.
  * ``llm_corrector`` owns LLM semantic correction — via the unified LLMClient.
  * ``dual_channel`` owns BibbGPT-style audio+text proofing (enabled this release).

Responsibilities never overlap and there are no name collisions
(no more two ``apply_errata`` with different signatures).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from garden_core.infra.llm_client import LLMClient, NoLLMClient
from garden_core.types import Transcript

__all__ = ["ProofOptions", "ErrataConfig", "proofread"]


@dataclass(frozen=True)
class ErrataConfig:
    """Deterministic correction tables. Injected, never global (fixes bug #9).

    ``flat`` is a {wrong: correct} str→str map. ``patterns`` are
    (compiled_pattern, replacement) regex pairs.
    """

    flat: dict = field(default_factory=dict)
    patterns: tuple = field(default_factory=tuple)

    @classmethod
    def empty(cls) -> "ErrataConfig":
        return cls()


@dataclass(frozen=True)
class ProofOptions:
    enable_normalize: bool = True      # 繁→简, 著→着
    enable_errata: bool = True         # deterministic apply
    enable_phonetic: bool = True       # detect + (where unambiguous) fix
    enable_llm: bool = False           # DeepSeek semantic correction
    enable_dual_channel: bool = True   # BibbGPT audio+text proofing
    llm_temperature: float = 0.1


def proofread(
    transcript: Transcript,
    errata: ErrataConfig,
    llm: Optional[LLMClient],
    opts: ProofOptions,
    audio_path: str = "",
) -> Transcript:
    """Run stage 3. Deterministic layers first, LLM layers last.

    Each layer returns a new immutable Transcript (with corrections_applied
    extended) — nothing mutates in place.

    Step API: part of ``garden_core.steps``. Persist via
    ``save_transcript_json`` / reload via ``load_transcript_json``.
    """
    from dataclasses import replace as _replace

    applied: list[str] = list(transcript.corrections_applied)
    result = transcript
    llm_client = llm or NoLLMClient()

    if opts.enable_normalize:
        from garden_core.stage_proofread.normalizer import normalize_segments
        result, n = normalize_segments(result)
        if n:
            applied.append(f"normalize:{n}")

    if opts.enable_errata and (errata.flat or errata.patterns):
        from garden_core.stage_proofread.errata import apply_errata_to_segments
        result, n = apply_errata_to_segments(result, errata)
        if n:
            applied.append(f"errata:{n}")

    if opts.enable_phonetic:
        from garden_core.stage_proofread.phonetic import fix_phonetic_in_segments
        result, n = fix_phonetic_in_segments(result)
        if n:
            applied.append(f"phonetic:{n}")

    if opts.enable_llm and llm_client.available:
        from garden_core.stage_proofread.llm_corrector import llm_correct_segments
        result, n = llm_correct_segments(result, llm_client, opts.llm_temperature)
        if n:
            applied.append(f"llm:{n}")

    if opts.enable_dual_channel and llm_client.available and audio_path:
        from garden_core.stage_proofread.dual_channel import dual_channel_proofread
        result, n = dual_channel_proofread(result, audio_path, llm_client)
        if n:
            applied.append(f"dual_channel:{n}")

    return _replace(result, corrections_applied=tuple(applied))
