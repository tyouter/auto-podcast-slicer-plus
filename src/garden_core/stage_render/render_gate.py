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

import logging
import os
import re
from dataclasses import dataclass

log = logging.getLogger(__name__)

__all__ = [
    "GateViolation",
    "RenderGateError",
    "ParsedAss",
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
