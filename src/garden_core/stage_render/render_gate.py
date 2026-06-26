r"""Render gate: an INDEPENDENT, mechanical post-render quality check.

This module does NOT render and does NOT touch render logic. It only *reads*
the artifacts a render already produced (the per-orientation ``.ass`` files
referenced by a :class:`~garden_core.types.RenderResult`) and verifies hard,
machine-computable specs. Zero LLM, zero tokens — pure formula + regex.

Why it exists
-------------
A real bug shipped once: vertical subtitles were sized against the full 1920px
canvas instead of the centred 16:9 content band (~607px), making vertical font
~3.2× too large. That defect is purely mechanical (a ratio mismatch) yet the
pipeline let it through silently — a human caught it by eyeballing frames. This
gate is the automatic net that catches *that class* of defect (and regressions
of it) without a human in the loop.

It is deliberately a SEPARATE layer from the content-level quality audit
(which is LLM-based). This file never calls an LLM.

Checks (all mechanical)
-----------------------
1. font_ratio  — horizontal ``font_size / content_height`` vs vertical
   ``font_size / content_height``; relative difference over tolerance → BLOCK.
   (content_height = the centred 16:9 band of the canvas — exactly the
   dimension the old bug got wrong.)
2. safe_area   — ``margin_v`` + text-block height must land inside the frame
   (inside the content band for vertical); no clipping, no floating.

On failure the gate BLOCKs loudly with a precise report (which clip / which
dimension / actual vs expected). It never auto-fixes a clip — that is a human
decision.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass, field
from typing import Optional

from garden_core.infra.media_probe import probe_media

log = logging.getLogger(__name__)

__all__ = [
    "AuditReport",
    "GateViolation",
    "RenderGateError",
    "ParsedAss",
    "audit_dir",
    "parse_ass",
    "check_ass_pair",
    "check_render_result",
    "gate_results",
]

# Default tolerance for the font-size ratio check (relative difference).
# The old bug was a ~3.2× (≈217%) mismatch, so a generous 15% band catches it
# with huge margin while never tripping on legitimate rounding noise.
DEFAULT_FONT_RATIO_TOL = 0.15

# Single-line text-block height as a multiple of font_size. Mirrors the box
# height factor in ass_writer._bg_dialogue (font_size * 1.4) so the safe-area
# estimate matches how the renderer sizes a line.
_LINE_HEIGHT_FACTOR = 1.4


# --------------------------------------------------------------------------- #
# Result / error types
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class GateViolation:
    """One failed check, in human-and-machine-readable form."""

    clip_id: str
    dimension: str    # "font_ratio" | "safe_area"
    orientation: str  # "horizontal" | "vertical" | "pair"
    detail: str
    expected: str
    actual: str

    def render(self) -> str:
        return (
            f"[BLOCK] clip={self.clip_id} dim={self.dimension} "
            f"({self.orientation}): {self.detail} | "
            f"expected={self.expected} actual={self.actual}"
        )


class RenderGateError(Exception):
    """Raised when one or more clips fail the mechanical render gate.

    Carries the full list of violations so the caller (a human) can see every
    bad clip / dimension at once and decide what to do. The gate never fixes.
    """

    def __init__(self, violations: list[GateViolation]) -> None:
        self.violations = list(violations)
        body = "\n".join("  " + v.render() for v in self.violations)
        super().__init__(
            f"render gate BLOCKED {len(self.violations)} spec violation(s):\n{body}"
        )


# --------------------------------------------------------------------------- #
# ASS parsing (pure, regex/string only)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ParsedAss:
    play_w: int
    play_h: int
    fontsize: int
    margin_v: int
    texts: tuple[str, ...]  # layer-1 (text) Dialogue contents, in order


_RE_PLAYX = re.compile(r"^PlayResX:\s*(\d+)", re.MULTILINE)
_RE_PLAYY = re.compile(r"^PlayResY:\s*(\d+)", re.MULTILINE)


def parse_ass(text: str) -> ParsedAss:
    """Parse the fields the gate needs out of an ASS document.

    Reads PlayResX/Y from [Script Info], Fontsize + MarginV from the
    'Style: Default,...' line (by Format position, like tests do), and the text
    of layer-1 Dialogue lines (layer 0 is the background-box vector drawing).
    """
    mx, my = _RE_PLAYX.search(text), _RE_PLAYY.search(text)
    if not mx or not my:
        raise ValueError("ASS missing PlayResX/PlayResY")
    play_w, play_h = int(mx.group(1)), int(my.group(1))

    style_line = next(
        (l for l in text.splitlines() if l.startswith("Style: Default,")), None
    )
    if style_line is None:
        raise ValueError("ASS missing 'Style: Default,' line")
    # Format: Name,Fontname,Fontsize,...,Alignment,MarginL,MarginR,MarginV,Encoding
    f = style_line[len("Style: "):].split(",")
    fontsize = int(round(float(f[2])))
    margin_v = int(f[-2])

    texts: list[str] = []
    for line in text.splitlines():
        if not line.startswith("Dialogue:"):
            continue
        # Dialogue Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
        parts = line[len("Dialogue:"):].split(",", 9)
        if len(parts) < 10:
            continue
        layer = parts[0].strip()
        body = parts[9]
        if layer != "1":  # skip the layer-0 background drawing
            continue
        texts.append(body)
    return ParsedAss(play_w=play_w, play_h=play_h, fontsize=fontsize,
                     margin_v=margin_v, texts=tuple(texts))


def _content_height(play_w: int, play_h: int) -> int:
    """The centred 16:9 content-band height for a canvas (px).

    Mirrors ass_writer.build_ass: band = round(w*9/16) rounded up to even; the
    content region is that band when it is shorter than the canvas (vertical),
    else the full canvas height (horizontal). This is the basis the renderer
    sizes font + vertical margin against, so the gate measures the same thing.
    """
    band = round(play_w * 9 / 16)
    band += band % 2  # match ffmpeg scale=w:-2 even-height rounding
    return band if band < play_h else play_h


# --------------------------------------------------------------------------- #
# Check 1: font-size ratio consistency
# --------------------------------------------------------------------------- #
def _check_font_ratio(
    clip_id: str, h: ParsedAss, v: ParsedAss, tol: float
) -> list[GateViolation]:
    h_ratio = h.fontsize / _content_height(h.play_w, h.play_h)
    v_ratio = v.fontsize / _content_height(v.play_w, v.play_h)
    if h_ratio <= 0:
        return []
    rel = abs(v_ratio - h_ratio) / h_ratio
    if rel <= tol:
        return []
    return [GateViolation(
        clip_id=clip_id,
        dimension="font_ratio",
        orientation="pair",
        detail=(
            "vertical font_size/content_height differs from horizontal by "
            f"{rel * 100:.0f}% (>{tol * 100:.0f}% tol); vertical font likely "
            "sized against the full canvas instead of the 16:9 content band"
        ),
        expected=f"v_ratio≈{h_ratio:.4f} (within {tol * 100:.0f}%)",
        actual=(
            f"h_ratio={h_ratio:.4f} (fs={h.fontsize}/{_content_height(h.play_w, h.play_h)}), "
            f"v_ratio={v_ratio:.4f} (fs={v.fontsize}/{_content_height(v.play_w, v.play_h)})"
        ),
    )]


# --------------------------------------------------------------------------- #
# Check 2: subtitle safe area
# --------------------------------------------------------------------------- #
def _check_safe_area(
    clip_id: str, ass: ParsedAss, orientation: str
) -> list[GateViolation]:
    out: list[GateViolation] = []
    content_h = _content_height(ass.play_w, ass.play_h)
    # Bottom edge of the (alignment=2, bottom-centred) text block in canvas px.
    y_bottom = ass.play_h - ass.margin_v
    # Tallest text block among the cues (lines counted by explicit \N breaks).
    max_lines = max((t.count(r"\N") + 1 for t in ass.texts), default=1)
    block_h = ass.fontsize * _LINE_HEIGHT_FACTOR * max_lines
    y_top = y_bottom - block_h

    if ass.margin_v < 0:
        out.append(GateViolation(
            clip_id=clip_id, dimension="safe_area", orientation=orientation,
            detail="margin_v is negative — subtitle baseline is below the frame",
            expected="margin_v>=0", actual=f"margin_v={ass.margin_v}",
        ))

    if content_h < ass.play_h:
        # Vertical canvas: subtitle must sit inside the centred content band,
        # never in the letterbox above/below it.
        content_bottom = (ass.play_h + content_h) // 2
        content_top = (ass.play_h - content_h) // 2
        if y_bottom > content_bottom:
            out.append(GateViolation(
                clip_id=clip_id, dimension="safe_area", orientation=orientation,
                detail="text block bottom falls below the content band into the lower letterbox",
                expected=f"y_bottom<=content_bottom={content_bottom}",
                actual=f"y_bottom={y_bottom:.0f} (margin_v={ass.margin_v})",
            ))
        if y_top < content_top:
            out.append(GateViolation(
                clip_id=clip_id, dimension="safe_area", orientation=orientation,
                detail="text block top rises above the content band into the upper letterbox",
                expected=f"y_top>=content_top={content_top}",
                actual=f"y_top={y_top:.0f} (fontsize={ass.fontsize}, lines={max_lines})",
            ))
    else:
        # Horizontal / full-frame: just stay inside [0, play_h].
        if y_bottom > ass.play_h:
            out.append(GateViolation(
                clip_id=clip_id, dimension="safe_area", orientation=orientation,
                detail="text block bottom falls below the frame",
                expected=f"y_bottom<=play_h={ass.play_h}",
                actual=f"y_bottom={y_bottom:.0f} (margin_v={ass.margin_v})",
            ))
        if y_top < 0:
            out.append(GateViolation(
                clip_id=clip_id, dimension="safe_area", orientation=orientation,
                detail="text block top rises above the top of the frame (floating/clipped)",
                expected="y_top>=0",
                actual=f"y_top={y_top:.0f} (fontsize={ass.fontsize}, lines={max_lines})",
            ))
    return out


# --------------------------------------------------------------------------- #
# Public entry points
# --------------------------------------------------------------------------- #
def check_ass_pair(
    clip_id: str,
    horizontal_ass: str | None,
    vertical_ass: str | None,
    *,
    font_ratio_tol: float = DEFAULT_FONT_RATIO_TOL,
) -> list[GateViolation]:
    """Run every check over a horizontal/vertical ASS text pair (no file I/O).

    Either side may be ``None`` (that orientation was not rendered). font_ratio
    needs both; safe_area runs per available orientation.
    """
    h = parse_ass(horizontal_ass) if horizontal_ass is not None else None
    v = parse_ass(vertical_ass) if vertical_ass is not None else None

    violations: list[GateViolation] = []
    if h is not None and v is not None:
        violations += _check_font_ratio(clip_id, h, v, font_ratio_tol)
    if h is not None:
        violations += _check_safe_area(clip_id, h, "horizontal")
    if v is not None:
        violations += _check_safe_area(clip_id, v, "vertical")
    return violations


def _vertical_ass_path(ass_path: str) -> str:
    """Derive the vertical ASS path from the canonical (horizontal) one.

    Mirrors stage_render.render: vertical ASS is '{clip_id}_vertical.ass'
    alongside the canonical '{clip_id}.ass'.
    """
    root, ext = os.path.splitext(ass_path)
    return f"{root}_vertical{ext}"


def check_render_result(result, *, font_ratio_tol: float = DEFAULT_FONT_RATIO_TOL):
    """Read a RenderResult's ASS artifacts off disk and run the gate over them.

    Read-only: opens the .ass files referenced/derived from the result; never
    writes or re-renders. Returns the list of violations (possibly empty).
    """
    h_text = None
    v_text = None
    if result.ass_path and os.path.exists(result.ass_path):
        with open(result.ass_path, "r", encoding="utf-8") as fh:
            h_text = fh.read()
        v_path = _vertical_ass_path(result.ass_path)
        if os.path.exists(v_path):
            with open(v_path, "r", encoding="utf-8") as fh:
                v_text = fh.read()
    else:
        log.warning("render gate: no ASS file for clip %s — skipping", result.clip_id)
        return []
    return check_ass_pair(result.clip_id, h_text, v_text, font_ratio_tol=font_ratio_tol)


def gate_results(results, *, font_ratio_tol: float = DEFAULT_FONT_RATIO_TOL) -> None:
    """Gate a whole batch of RenderResults; raise RenderGateError if any fail.

    Checks every clip first, then raises once with the complete report so a
    human sees all bad clips/dimensions at once. Passing clips are silent.
    """
    all_violations: list[GateViolation] = []
    for r in results:
        all_violations += check_render_result(r, font_ratio_tol=font_ratio_tol)
    if all_violations:
        raise RenderGateError(all_violations)
    log.info("render gate: clips passed all mechanical specs")


# --------------------------------------------------------------------------- #
# Directory-level audit (T3): combines file-existence, ffprobe specs,
# ASS cue count, and ASS content gate into a single AuditReport.
# --------------------------------------------------------------------------- #

@dataclass
class AuditReport:
    """Structured result of ``audit_dir()``.

    Carries all blocking violations and any skipped (non-blocking) mechanical
    items (e.g. ffprobe unavailable).  Provides serialisation for downstream
    agents (``to_dict()`` / ``save()``).
    """

    output_dir: str
    violations: list[GateViolation] = field(default_factory=list)
    skipped: list[GateViolation] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return len(self.violations) == 0

    def to_dict(self) -> dict:
        def _v(v: GateViolation) -> dict:
            return {
                "clip_id": v.clip_id,
                "dimension": v.dimension,
                "orientation": v.orientation,
                "detail": v.detail,
                "expected": v.expected,
                "actual": v.actual,
            }
        return {
            "output_dir": self.output_dir,
            "passed": self.passed,
            "violations": [_v(v) for v in self.violations],
            "skipped": [_v(v) for v in self.skipped],
        }

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, ensure_ascii=False, indent=2)


# --------------------------------------------------------------------------- #
# Internal helpers for audit_dir
# --------------------------------------------------------------------------- #

def _discover_clip_ids(output_dir: str) -> set[str]:
    """Extract unique clip_ids from filenames in *output_dir*.

    Discovers from ``{cid}_horizontal.mp4``, ``{cid}_vertical.mp4``,
    and ``{cid}.ass`` files.  ``{cid}_vertical.ass`` is intentionally
    excluded so it does not create a spurious clip_id entry — it is
    always paired with its horizontal ``.ass`` via ``_vertical_ass_path``.
    """
    cids: set[str] = set()
    try:
        names = os.listdir(output_dir)
    except FileNotFoundError:
        return cids
    for fname in names:
        if fname.endswith("_horizontal.mp4"):
            cids.add(fname[: -len("_horizontal.mp4")])
        elif fname.endswith("_vertical.mp4"):
            cids.add(fname[: -len("_vertical.mp4")])
        elif fname.endswith(".ass") and not fname.endswith("_vertical.ass"):
            cids.add(fname[: -len(".ass")])
    return cids


def _probe_codec(mp4_path: str, ffprobe_bin: str = "ffprobe") -> Optional[str]:
    """Return the codec_name of the first video stream, or *None* on failure."""
    cmd = [
        ffprobe_bin, "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=codec_name",
        "-of", "csv=p=0",
        mp4_path,
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace",
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return (proc.stdout.strip() or None)


def _count_ass_cues(ass_path: str) -> int:
    """Count ``Dialogue:`` lines in an ASS file (all layers)."""
    try:
        with open(ass_path, "r", encoding="utf-8") as fh:
            return sum(1 for line in fh if line.startswith("Dialogue:"))
    except (FileNotFoundError, PermissionError):
        return 0


# --------------------------------------------------------------------------- #
# Public: audit_dir
# --------------------------------------------------------------------------- #

def audit_dir(
    output_dir: str,
    *,
    pattern: str = "{clip_id}",
    expected_horizontal: tuple[int, int] = (3840, 2160),
    expected_vertical: tuple[int, int] = (1080, 1920),
    expected_codec: str = "h264",
    render_horizontal: bool = True,
    render_vertical: bool = True,
    raise_on_fail: bool = True,
    font_ratio_tol: float = DEFAULT_FONT_RATIO_TOL,
    ffprobe_bin: str = "ffprobe",
) -> AuditReport:
    """Audit a rendered output directory against mechanical quality specs.

    Four checks on every discovered clip:

    1. **File existence** — ``{cid}_horizontal.mp4`` / ``{cid}_vertical.mp4`` /
       ``{cid}.ass`` / ``{cid}_vertical.ass`` must all be present (subject to
       *render_horizontal* / *render_vertical*).  Missing → ``missing_file``.
    2. **ffprobe resolution & codec** — for each existing mp4, verify width×height
       against *expected_horizontal* / *expected_vertical* and codec against
       *expected_codec*.  Mismatch → ``resolution`` / ``codec``.
    3. **ASS cue count** — every ``.ass`` must have ≥1 ``Dialogue:`` line.
       Zero → ``zero_cues``.
    4. **ASS content gate** — delegates to :func:`check_ass_pair` (font-ratio +
       safe-area).  Violations retain their original ``dimension``
       (``font_ratio`` / ``safe_area``).

    If *raise_on_fail* is ``True`` (default) and any blocking violation exists,
    :class:`RenderGateError` is raised with the full violation list.  Skipped
    items (ffprobe unavailable) are **never** blocking.

    Parameters
    ----------
    output_dir:
        Path to the directory containing rendered clip artifacts.
    pattern:
        Naming pattern (unused — kept for API future-proofing; the render
        stage always uses ``{clip_id}_horizontal.mp4`` etc.).
    expected_horizontal:
        Expected (width, height) for horizontal mp4 files.
    expected_vertical:
        Expected (width, height) for vertical mp4 files.
    expected_codec:
        Expected video codec (e.g. ``"h264"``).
    render_horizontal / render_vertical:
        Whether horizontal / vertical orientation was rendered.  Missing files
        are only flagged when the corresponding orientation is enabled.
    raise_on_fail:
        If ``True``, raise :class:`RenderGateError` on any blocking violation.
    font_ratio_tol:
        Passed through to :func:`check_ass_pair`.
    ffprobe_bin:
        Path or name of the ffprobe binary.
    """
    clip_ids = _discover_clip_ids(output_dir)
    violations: list[GateViolation] = []
    skipped: list[GateViolation] = []

    for cid in sorted(clip_ids):
        # ---- file existence -------------------------------------------------
        h_mp4 = os.path.join(output_dir, f"{cid}_horizontal.mp4")
        v_mp4 = os.path.join(output_dir, f"{cid}_vertical.mp4")
        h_ass = os.path.join(output_dir, f"{cid}.ass")
        v_ass = _vertical_ass_path(h_ass)

        if render_horizontal:
            for path, label in [(h_mp4, "H_MP4"), (h_ass, "H_ASS")]:
                if not os.path.exists(path):
                    violations.append(GateViolation(
                        clip_id=cid, dimension="missing_file",
                        orientation="horizontal",
                        detail=f"missing {label}: {path}",
                        expected="file exists", actual="not found",
                    ))
        if render_vertical:
            for path, label in [(v_mp4, "V_MP4"), (v_ass, "V_ASS")]:
                if not os.path.exists(path):
                    violations.append(GateViolation(
                        clip_id=cid, dimension="missing_file",
                        orientation="vertical",
                        detail=f"missing {label}: {path}",
                        expected="file exists", actual="not found",
                    ))

        # ---- ffprobe mechanical specs ---------------------------------------
        for orientation, mp4_path, expected_wh in [
            ("horizontal", h_mp4, expected_horizontal),
            ("vertical", v_mp4, expected_vertical),
        ]:
            enabled = render_horizontal if orientation == "horizontal" else render_vertical
            if not enabled:
                continue
            if not os.path.exists(mp4_path):
                continue  # already reported as missing_file above

            ffprobe_ok = True

            # Resolution check via probe_media
            info = probe_media(mp4_path, ffprobe_bin=ffprobe_bin)
            if info is None:
                ffprobe_ok = False
            else:
                if (info.width, info.height) != expected_wh:
                    violations.append(GateViolation(
                        clip_id=cid, dimension="resolution",
                        orientation=orientation,
                        detail=f"expected {expected_wh[0]}x{expected_wh[1]}",
                        expected=f"{expected_wh[0]}x{expected_wh[1]}",
                        actual=f"{info.width}x{info.height}",
                    ))

            # Codec check (separate ffprobe call — probe_media doesn't return codec)
            codec = _probe_codec(mp4_path, ffprobe_bin=ffprobe_bin)
            if codec is None:
                ffprobe_ok = False
            elif codec != expected_codec:
                violations.append(GateViolation(
                    clip_id=cid, dimension="codec",
                    orientation=orientation,
                    detail=f"expected codec={expected_codec}, got {codec}",
                    expected=expected_codec,
                    actual=codec,
                ))

            if not ffprobe_ok:
                skipped.append(GateViolation(
                    clip_id=cid, dimension="skipped",
                    orientation=orientation,
                    detail=f"ffprobe unavailable for mechanical check on {mp4_path}",
                    expected="ffprobe available",
                    actual="ffprobe returned None or failed",
                ))

        # ---- ASS cue count --------------------------------------------------
        for orientation, ass_path in [("horizontal", h_ass), ("vertical", v_ass)]:
            enabled = render_horizontal if orientation == "horizontal" else render_vertical
            if not enabled:
                continue
            if not os.path.exists(ass_path):
                continue  # already reported as missing_file above
            if _count_ass_cues(ass_path) == 0:
                violations.append(GateViolation(
                    clip_id=cid, dimension="zero_cues",
                    orientation=orientation,
                    detail=f"ASS file has zero Dialogue: lines: {ass_path}",
                    expected=">=1 Dialogue: line",
                    actual="0",
                ))

        # ---- ASS content gate -----------------------------------------------
        h_text: Optional[str] = None
        v_text: Optional[str] = None
        if render_horizontal and os.path.exists(h_ass):
            with open(h_ass, "r", encoding="utf-8") as fh:
                h_text = fh.read()
        if render_vertical and os.path.exists(v_ass):
            with open(v_ass, "r", encoding="utf-8") as fh:
                v_text = fh.read()
        if h_text is not None or v_text is not None:
            try:
                violations += check_ass_pair(cid, h_text, v_text,
                                             font_ratio_tol=font_ratio_tol)
            except ValueError as e:
                violations.append(GateViolation(
                    clip_id=cid, dimension="ass_gate",
                    orientation="pair",
                    detail=f"ASS parse failed: {e}",
                    expected="valid ASS document",
                    actual="parse error",
                ))

    report = AuditReport(
        output_dir=output_dir,
        violations=violations,
        skipped=skipped,
    )

    if raise_on_fail and violations:
        raise RenderGateError(violations)

    if violations:
        log.warning("audit_dir: %d violation(s) in %s", len(violations), output_dir)
    else:
        log.info("audit_dir: all %d clip(s) passed mechanical audit", len(clip_ids))
    return report
