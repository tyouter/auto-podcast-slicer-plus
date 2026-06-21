"""Text width measurement. Fixes legacy bug #14: ``bold`` was accepted but
ignored — ``_load_font`` never loaded a bold variant, so all measurements used
regular glyphs and background boxes came out too narrow for bold subtitles.

Now: when ``bold=True`` we prefer a bold font file (``*Bold*.ttf`` / ``msyhbd`` /
``simheib`` / the "Bold" family member) before falling back to regular.
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

__all__ = ["measure_text_width", "measure_text_bbox", "resolve_font_file"]

# Candidate bold filename fragments, tried in order when bold=True.
_BOLD_HINTS = ("bold", "bd", "heavy", "black", "sembd")
_REGULAR_FALLBACKS = ("wqy-zenhei.ttc", "msyh.ttc", "simhei.ttf", "NotoSansSC-Regular.otf")


@lru_cache(maxsize=1)
def _font_dirs() -> tuple[Path, ...]:
    import os
    candidates = []
    for env in ("SYSTEMROOT",):
        root = os.environ.get(env, r"C:\Windows")
        candidates.append(Path(root) / "Fonts")
    # common user font dirs
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(Path(local) / "Microsoft" / "Windows" / "Fonts")
    candidates.extend([
        Path.home() / ".fonts",
        Path("/usr/share/fonts"),
        Path("/usr/local/share/fonts"),
    ])
    return tuple(c for c in candidates if c.exists())


def _try_name_variants(font_name: str) -> tuple[str, ...]:
    """Generate candidate filenames for a font family name."""
    compact = font_name.replace(" ", "")
    return (f"{font_name}.ttf", f"{compact}.ttf", f"{compact}.otf", f"{font_name}.otf")


def resolve_font_file(font_name: str, bold: bool = False) -> Optional[Path]:
    """Locate a font file on disk. Prefers a bold variant when bold=True."""
    # 1. by family name in each font dir
    for d in _font_dirs():
        for fname in _try_name_variants(font_name):
            p = d / fname
            if p.exists():
                # if bold requested, look for a sibling bold file first
                if bold:
                    bold_match = _find_bold_sibling(d, p.stem)
                    if bold_match:
                        return bold_match
                return p
    # 2. blind scan for the name (case-insensitive substring)
    target = font_name.replace(" ", "").lower()
    for d in _font_dirs():
        for p in d.glob("*.[ot]tf"):
            stem = p.stem.replace(" ", "").lower()
            if target in stem or stem in target:
                if bold:
                    bold_match = _find_bold_sibling(d, p.stem)
                    if bold_match:
                        return bold_match
                return p
    # 3. last-resort fallbacks
    for d in _font_dirs():
        if bold:
            for p in d.iterdir():
                low = p.stem.lower()
                if any(h in low for h in _BOLD_HINTS) and p.suffix in (".ttf", ".otf", ".ttc"):
                    return p
        for fb in _REGULAR_FALLBACKS:
            p = d / fb
            if p.exists():
                return p
    return None


def _find_bold_sibling(directory: Path, stem: str) -> Optional[Path]:
    """Find a bold variant of ``stem`` in the same directory."""
    low = stem.lower()
    # strip existing weight tokens
    base = re.sub(r"(regular|normal|light|medium|bd|bold|black|heavy)", "", low).strip("-_ ")
    for p in directory.iterdir():
        if p.suffix not in (".ttf", ".otf", ".ttc"):
            continue
        pl = p.stem.lower()
        if base and base in pl and any(h in pl for h in _BOLD_HINTS):
            return p
    return None


@lru_cache(maxsize=256)
def _load_font(font_name: str, font_size: int, bold: bool):
    """Load a PIL font, honouring bold. Cached by (name, size, bold)."""
    try:
        from PIL import ImageFont
    except ImportError:
        return None
    font_file = resolve_font_file(font_name, bold=bold)
    if font_file is None:
        log.warning("font not found: %s (bold=%s) — falling back to ratios", font_name, bold)
        return None
    try:
        return ImageFont.truetype(str(font_file), int(font_size))
    except Exception as e:
        log.warning("failed to load font %s: %s", font_file, e)
        return None


def _ratio_width(text: str, font_size: int) -> int:
    """Fallback width estimate when no font file is available (CJK-aware)."""
    w = 0
    for ch in text:
        if "一" <= ch <= "鿿" or "　" <= ch <= "〿":
            w += int(font_size * 0.673)
        elif ch.isascii() and ch.isalnum():
            w += int(font_size * 0.37)
        elif ch == " ":
            w += int(font_size * 0.2)
        else:
            w += int(font_size * 0.4)
    return w


def measure_text_width(
    text: str,
    font_size: int,
    font_family: str = "Noto Sans SC",
    bold: bool = False,
) -> int:
    """Width of ``text`` in pixels at ``font_size``. Honours bold (fix #14)."""
    font = _load_font(font_family, int(font_size), bold)
    if font is not None:
        try:
            return int(font.getlength(text))
        except Exception:
            pass
    return _ratio_width(text, int(font_size))


def measure_text_bbox(
    text: str,
    font_size: int,
    font_family: str = "Noto Sans SC",
    bold: bool = False,
) -> tuple[int, int]:
    """Return (width, height) of the text bounding box."""
    font = _load_font(font_family, int(font_size), bold)
    if font is not None:
        try:
            from PIL import ImageDraw, Image
            img = Image.new("RGB", (10, 10))
            d = ImageDraw.Draw(img)
            bbox = d.textbbox((0, 0), text, font=font)
            return (bbox[2] - bbox[0], bbox[3] - bbox[1])
        except Exception:
            pass
    w = _ratio_width(text, int(font_size))
    return (w, int(font_size))
