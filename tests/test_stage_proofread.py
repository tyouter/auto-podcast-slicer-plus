"""Stage 3 (proofread) tests — apply/detect separation + LLM degradation invariants."""

from __future__ import annotations

from garden_core.infra.llm_client import LLMClient, LLMOutcome, LLMResponse, NoLLMClient
from garden_core.stage_proofread import ErrataConfig, ProofOptions, proofread
from garden_core.stage_proofread.dual_channel import dual_channel_proofread
from garden_core.stage_proofread.errata import apply_errata_to_segments
from garden_core.stage_proofread.llm_corrector import llm_correct_segments
from garden_core.stage_proofread.normalizer import (
    convert_zhu_to_zhe, normalize_segments, normalize_text,
)
from garden_core.stage_proofread.phonetic import fix_phonetic_in_segments
from garden_core.types import Segment, Transcript

import re


def _t(*texts_times) -> Transcript:
    segs = tuple(
        Segment(text=t, start_s=s, end_s=e) for t, s, e in texts_times
    )
    return Transcript(segments=segs, source_file="x", engine="test")


# ---------------------------- normalizer ----------------------------------- #
def test_zhu_to_zhe_protects_compounds():
    assert convert_zhu_to_zhe("显著") == "显著"      # compound kept
    assert convert_zhu_to_zhe("看着") == "看着"       # already correct
    # 著 outside compounds → 着
    assert convert_zhu_to_zhe("他著急") == "他着急"


def test_normalize_segments_changes_traditional():
    # 繁 體 → 简体 (OpenCC may or may not be installed; test is tolerant)
    t = _t(("測試文字", 0.0, 1.0))
    out, n = normalize_segments(t)
    assert out.segments[0].text == "测试文字"
    assert n >= 1
    # original untouched (immutable)
    assert t.segments[0].text == "測試文字"


def test_normalize_is_idempotent():
    t = _t(("测试", 0.0, 1.0))
    once, _ = normalize_segments(t)
    twice, _ = normalize_segments(once)
    assert once == twice


# ---------------------------- errata (apply only) -------------------------- #
def test_errata_applies_longest_first():
    # Non-overlapping keys of different lengths: longer matched first so a
    # shorter key doesn't fragment it. (Cascading substitution — where one
    # correction's output contains another key's trigger — is a known
    # limitation shared with the legacy engine, out of scope here.)
    cfg = ErrataConfig(flat={"分岔": "分岔A", "小径分岔的花园": "花园全名"})
    t = _t(("我们在小径分岔的花园里", 0.0, 1.0))
    out, n = apply_errata_to_segments(t, cfg)
    assert "花园全名" in out.segments[0].text
    assert n == 1


def test_errata_regex_patterns():
    cfg = ErrataConfig(flat={}, patterns=((re.compile(r"然(?:后|候)"), "然后"),))
    t = _t(("他然候走了", 0.0, 1.0))
    out, n = apply_errata_to_segments(t, cfg)
    assert out.segments[0].text == "他然后走了"
    assert n == 1


def test_errata_no_change_returns_same_count_zero():
    cfg = ErrataConfig(flat={"不存在": "x"})
    t = _t(("无关文本", 0.0, 1.0))
    out, n = apply_errata_to_segments(t, cfg)
    assert n == 0
    assert out.segments[0].text == "无关文本"


# ---------------------------- phonetic (detect side) ----------------------- #
def test_phonetic_returns_zero_when_nothing_to_fix():
    t = _t(("这是一段正常文本", 0.0, 1.0))
    out, n = fix_phonetic_in_segments(t)
    assert n == 0


# ---------------------------- LLM corrector -------------------------------- #
def test_llm_corrector_unavailable_is_noop():
    """LLM unavailable → no-op with WARNING, never crash or fabricate."""
    t = _t(("测试一", 0.0, 1.0), ("测试二", 1.0, 2.0))
    out, n = llm_correct_segments(t, NoLLMClient(), temperature=0.1)
    assert n == 0
    assert out == t  # unchanged


def test_llm_corrector_applies_response(monkeypatch):
    t = _t(("我们我们", 0.0, 1.0), ("确实施好", 1.0, 2.0))
    client = LLMClient(api_key="fake")

    def fake_chat(messages, **kwargs):
        return LLMResponse(outcome=LLMOutcome.OK,
                           content="[0] 我们\n[1] 确实是好", attempts=1)
    monkeypatch.setattr(client, "chat", fake_chat)

    out, n = llm_correct_segments(t, client)
    assert n == 2
    assert out.segments[0].text == "我们"
    assert out.segments[1].text == "确实是好"


# ---------------------------- dual channel --------------------------------- #
def test_dual_channel_no_audio_is_noop():
    t = _t(("测试一", 0.0, 1.0), ("测试二", 1.0, 2.0))
    out, n = dual_channel_proofread(t, "", NoLLMClient())
    assert n == 0
    assert out == t


def test_dual_channel_unavailable_stops_cleanly():
    t = _t(("这是一段足够长的文本", 0.0, 1.0))
    out, n = dual_channel_proofread(t, "audio.wav", NoLLMClient())
    assert n == 0
    assert out == t


# ---------------------------- full proofread orchestration ----------------- #
def test_proofread_runs_deterministic_layers_without_llm():
    """No LLM → deterministic layers run, LLM layers are no-ops, no crash."""
    t = _t(("他著急了", 0.0, 1.0))
    cfg = ErrataConfig(flat={"著急": "着急"})
    out = proofread(t, cfg, None, ProofOptions(enable_llm=False, enable_dual_channel=False))
    # normalize converts 著→着 (or already), then errata may also apply
    assert "着急" in out.segments[0].text
    assert out.corrections_applied  # some layer recorded activity


def test_proofread_records_applied_layers():
    t = _t(("測試", 0.0, 1.0))
    out = proofread(
        t, ErrataConfig.empty(), None,
        ProofOptions(enable_llm=False, enable_dual_channel=False),
    )
    # normalize ran → recorded
    assert any("normalize" in c for c in out.corrections_applied)
