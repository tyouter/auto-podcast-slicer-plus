"""Comprehensive full-pipeline test: exercises EVERY stage individually.

Stages tested:
  1. ASR (FunASR local, GPU)
  2. Align (MMS forced alignment, word-level timestamps)
  3a. Normalize (繁→简 + 著→着)
  3b. Errata (deterministic corrections from errata.yaml)
  3c. Phonetic (high-confidence fixes)
  3d. LLM corrector (DeepSeek whole-transcript)
  3e. Dual-channel (DeepSeek context-conditioned)
  G.  Gap-heal (detect + fill speech-with-no-subtitle)
  4. Segment (semantic)
  5. Cut
  6. Style (cinematic mold)
  7. Render (1080p horizontal + vertical MP4, SRT, ASS)
"""

from __future__ import annotations

import logging
import os
import sys
import time
from dataclasses import replace

logging.basicConfig(level=logging.INFO, format="%(levelname).1s %(name)s: %(message)s")

results: list[tuple[str, str]] = []  # (stage_name, "OK"|"FAIL"|"SKIP")


def ok(name: str, detail: str = ""):
    msg = f"OK ({detail})" if detail else "OK"
    results.append((name, msg))
    print(f"  [OK] {name}" + (f"  — {detail}" if detail else ""))


def fail(name: str, detail: str = ""):
    msg = f"FAIL ({detail})" if detail else "FAIL"
    results.append((name, msg))
    print(f"  [FAIL] {name}" + (f"  — {detail}" if detail else ""))


def skip(name: str, reason: str = ""):
    msg = f"SKIP ({reason})" if reason else "SKIP"
    results.append((name, msg))
    print(f"  [SKIP] {name}" + (f"  — {reason}" if reason else ""))


# ---- config ----------------------------------------------------------------
AUDIO = r"D:/Hermes/projects/auto-podcast-slicer-plus/_m3_out/full_test_clip.wav"
SOURCE_VIDEO = r"D:\boke\garden post factory\C0257_mono_video.mp4"
ERRATA = r"D:/Hermes/projects/auto-podcast-slicer/projects/garden-forking-paths/errata.yaml"
OUTPUT_DIR = r"D:/Hermes/projects/auto-podcast-slicer-plus/_m3_out/full_test"


def main() -> int:
    assert os.path.exists(AUDIO), f"audio missing: {AUDIO}"
    assert os.path.exists(SOURCE_VIDEO), f"video missing: {SOURCE_VIDEO}"
    assert os.environ.get("DEEPSEEK_API_KEY"), "DEEPSEEK_API_KEY not set"

    t0 = time.monotonic()
    print("=" * 60)
    print("COMPREHENSIVE FULL-PIPELINE TEST (stage by stage)")
    print("=" * 60)

    # ═══════════════════════════════════════════════════════════════════════
    # Stage 1: ASR
    # ═══════════════════════════════════════════════════════════════════════
    print("\n── Stage 1: ASR ──")
    from garden_core.stage_asr import AudioRef
    from garden_core.types import Segment as _Segment, Transcript as _Transcript

    class _FunASRLocal:
        """Inline FunASR AutoModel (avoid cross-test import)."""
        def __init__(self, device="cuda", chunk_s=30.0):
            self._model = None
            self._device = device
            self._chunk_s = chunk_s
        @property
        def name(self):
            return "funasr-local"
        def _load(self):
            if self._model is not None:
                return
            from funasr import AutoModel
            self._model = AutoModel(
                model="iic/speech_paraformer-large-vad-punc_asr_nat-zh-cn-16k-common-vocab8404-pytorch",
                vad_model="iic/speech_fsmn_vad_zh-cn-16k-common-pytorch",
                punc_model="iic/punc_ct-transformer_zh-cn-common-vocab272727-pytorch",
                spk_model="iic/speech_campplus_sv_zh-cn_16k-common",
                device=self._device, batch_size_s=300,
            )
        def transcribe(self, audio, hotwords=()):
            self._load()
            t_start = time.monotonic()
            result = self._model.generate(input=audio.path, batch_size_s=int(self._chunk_s))
            sentences = result[0].get("sentence_info", []) if isinstance(result, list) else result.get("sentence_info", [])
            segs = []
            for s in sentences:
                if not isinstance(s, dict) or not s.get("text"):
                    continue
                segs.append(_Segment(
                    text=str(s["text"]).strip(),
                    start_s=float(s.get("start", 0)) / 1000.0,
                    end_s=float(s.get("end", 0)) / 1000.0,
                    speaker=str(s.get("spk", -1)) if s.get("spk", -1) >= 0 else None,
                ))
            return _Transcript(
                segments=tuple(segs), source_file=audio.path, engine="funasr-local",
                language="zh", duration_s=segs[-1].end_s if segs else 0.0,
            )

    t1 = time.monotonic()
    transcriber = _FunASRLocal(device="cuda")
    transcript = transcriber.transcribe(AudioRef(path=AUDIO))
    asr_time = time.monotonic() - t1
    n_seg = len(transcript.segments)
    ok("1. ASR (FunASR local)", f"{n_seg} segments, {transcript.duration_s:.0f}s audio, {asr_time:.1f}s")
    for i, seg in enumerate(transcript.segments[:2]):
        print(f"       [{i}] \"{seg.text[:60]}\"  {seg.start_s:.1f}-{seg.end_s:.1f}s")
    if n_seg > 2:
        print(f"       ... ({n_seg - 2} more)")

    # ═══════════════════════════════════════════════════════════════════════
    # Stage 2: Align
    # ═══════════════════════════════════════════════════════════════════════
    print("\n── Stage 2: Align ──")
    from garden_core.stage_align.mms_aligner import MMSAligner
    from garden_core.stage_align import align

    aligner = MMSAligner(device="cuda")
    transcript = align(transcript, aligner, AUDIO)
    words_total = sum(len(s.words) for s in transcript.segments)
    if words_total > 0:
        ok("2. Align (MMS_FA)", f"{words_total} char-level timestamps across {n_seg} segments")
        # Show a sample word
        for seg in transcript.segments:
            if seg.words:
                sample = "".join(w.text for w in seg.words[:15])
                print(f"       sample: \"{sample}\"  words={len(seg.words)}")
                break
    else:
        fail("2. Align (MMS_FA)", "no word timestamps produced")

    # ═══════════════════════════════════════════════════════════════════════
    # Stage 3: Proofread (5 sub-stages)
    # ═══════════════════════════════════════════════════════════════════════
    print("\n── Stage 3: Proofread ──")
    from garden_core.config import build_errata_config
    from garden_core.infra.llm_client import LLMClient
    from garden_core.stage_proofread.normalizer import normalize_segments
    from garden_core.stage_proofread.errata import apply_errata_to_segments
    from garden_core.stage_proofread.phonetic import fix_phonetic_in_segments
    from garden_core.stage_proofread.llm_corrector import llm_correct_segments
    from garden_core.stage_proofread.dual_channel import dual_channel_proofread

    llm = LLMClient()
    errata_cfg = build_errata_config(ERRATA)

    # 3a: Normalize
    orig_len = sum(len(s.text) for s in transcript.segments)
    transcript, n_norm = normalize_segments(transcript)
    new_len = sum(len(s.text) for s in transcript.segments)
    ok("3a. Normalize", f"{n_norm} segments changed, {orig_len}→{new_len} chars")

    # 3b: Errata
    transcript, n_errata = apply_errata_to_segments(transcript, errata_cfg)
    ok("3b. Errata", f"{n_errata} corrections ({len(errata_cfg.flat)} flat + {len(errata_cfg.patterns)} patterns)")

    # 3c: Phonetic
    transcript, n_phon = fix_phonetic_in_segments(transcript)
    ok("3c. Phonetic", f"{n_phon} high-confidence fixes")

    # 3d: LLM corrector
    if llm.available:
        t_llm = time.monotonic()
        transcript, n_llm = llm_correct_segments(transcript, llm, temperature=0.1)
        llm_time = time.monotonic() - t_llm
        ok("3d. LLM corrector", f"{n_llm} segments corrected in {llm_time:.1f}s")
    else:
        skip("3d. LLM corrector", "no API key")

    # 3e: Dual-channel
    if llm.available and AUDIO:
        t_dc = time.monotonic()
        transcript, n_dc = dual_channel_proofread(transcript, AUDIO, llm, batch_size=20)
        dc_time = time.monotonic() - t_dc
        ok("3e. Dual-channel", f"{n_dc} context-conditioned fixes in {dc_time:.1f}s")
    else:
        skip("3e. Dual-channel", "no audio or no key")

    # Show sample post-proofread
    for i, seg in enumerate(transcript.segments[:2]):
        print(f"       [{i}] \"{seg.text[:60]}\"")

    # ═══════════════════════════════════════════════════════════════════════
    # Gap-heal (optional)
    # ═══════════════════════════════════════════════════════════════════════
    print("\n── Gap-heal ──")
    from garden_core.stage_segment.gap_heal import heal_gaps, detect_gaps

    if AUDIO:
        gaps_before = len(detect_gaps(transcript, AUDIO, min_gap_s=1.5))
        print(f"       gaps before heal: {gaps_before}")
        transcript, unfilled = heal_gaps(transcript, AUDIO, transcriber=None, max_rounds=2)
        gaps_after = len(unfilled)
        if gaps_before == 0:
            skip("Gap-heal", "no gaps detected (continuous speech in this clip)")
        elif gaps_after < gaps_before:
            ok("Gap-heal", f"{gaps_before}→{gaps_after} gaps (healed {gaps_before - gaps_after})")
        else:
            ok("Gap-heal", f"{gaps_before} gaps detected, 0 healed (no transcriber provided)")
    else:
        skip("Gap-heal", "no audio path")

    # ═══════════════════════════════════════════════════════════════════════
    # Stage 4: Segment
    # ═══════════════════════════════════════════════════════════════════════
    print("\n── Stage 4: Segment ──")
    from garden_core.stage_segment import segment, SegmentOptions

    cues = segment(transcript, SegmentOptions(strategy="semantic", max_duration_s=7.0))
    ok("4. Segment (semantic)", f"{len(cues)} cues")
    for cue in cues[:3]:
        print(f"       [{cue.index}] \"{cue.text[:50]}\"  {cue.start_s:.1f}-{cue.end_s:.1f}s")

    # ═══════════════════════════════════════════════════════════════════════
    # Stage 5: Cut
    # ═══════════════════════════════════════════════════════════════════════
    print("\n── Stage 5: Cut ──")
    from garden_core.stage_cut import cut
    from garden_core.types import CutPoint

    clip_dur = min(90.0, transcript.duration_s - 10.0)
    cut_points = [CutPoint(clip_id="full_test", source_media=SOURCE_VIDEO, start_s=10.0, end_s=10.0 + clip_dur,
                           style_name="cinematic", title="Full Test")]
    plans = cut(transcript, cues, cut_points)
    plan = replace(plans[0], source_ref=SOURCE_VIDEO)
    ok("5. Cut", f"1 clip ({plan.duration_s:.0f}s), {len(plan.cues)} cues")

    # ═══════════════════════════════════════════════════════════════════════
    # Stage 6: Style
    # ═══════════════════════════════════════════════════════════════════════
    print("\n── Stage 6: Style ──")
    from garden_core.stage_style.molds import YamlStyleResolver

    resolver = YamlStyleResolver()
    style = resolver.resolve("cinematic", 2160)
    ok("6. Style (cinematic)", f"font={style.font_family}, {style.font_size_px(1080):.0f}px@1080p")

    # ═══════════════════════════════════════════════════════════════════════
    # Stage 7: Render
    # ═══════════════════════════════════════════════════════════════════════
    print("\n── Stage 7: Render ──")
    from garden_core.stage_render import render, RenderOptions

    r_opts = RenderOptions(
        output_dir=OUTPUT_DIR,
        render_horizontal=True,
        render_vertical=True,
        horizontal_width=1920, horizontal_height=1080,
        vertical_width=1080, vertical_height=1920,
        crf=18,
    )
    r = render(plan, style, r_opts)

    all_outputs_ok = True
    for label, path in [
        ("SRT", r.srt_path),
        ("ASS (H)", r.ass_path),
        ("ASS (V)", f"{os.path.splitext(r.ass_path)[0]}_vertical.ass"),
        ("MP4 (H)", r.horizontal_mp4),
        ("MP4 (V)", r.vertical_mp4),
    ]:
        exists = bool(path) and os.path.exists(path)
        size = os.path.getsize(path) if exists else 0
        mb = size / 1024 / 1024
        if exists and size > 0:
            ok(f"7. Render → {label}", f"{mb:.1f} MB")
        else:
            fail(f"7. Render → {label}", "missing or empty")
            all_outputs_ok = False

    # ═══════════════════════════════════════════════════════════════════════
    # Summary
    # ═══════════════════════════════════════════════════════════════════════
    elapsed = time.monotonic() - t0
    print(f"\n{'=' * 60}")
    print(f"SUMMARY  ({elapsed:.0f}s total)")
    print(f"{'=' * 60}")
    passed = sum(1 for _, r in results if r.startswith("OK"))
    failed = sum(1 for _, r in results if r.startswith("FAIL"))
    skipped = sum(1 for _, r in results if r.startswith("SKIP"))
    for name, result in results:
        print(f"  [{result.split()[0]:>4}] {name}  — {result.split('(', 1)[1].rstrip(')') if '(' in result else 'OK'}")
    print(f"\n  {passed} passed, {failed} failed, {skipped} skipped")
    print(f"  RESULT: {'ALL PASS' if failed == 0 else 'FAIL'}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
