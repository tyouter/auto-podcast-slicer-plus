"""Proportional style templates ("molds") + a YAML-driven resolver.

This is the SINGLE style resolution path (fixes legacy bug #3: two parallel
systems, SubtitleStyle + StyleDefinition, that drifted apart). Here one
``StyleResolver`` (``YamlStyleResolver`` or ``StaticResolver``) maps a
``style_name`` to one ``StyleDef``. Molds are ratio templates expanded against
a video height; YAML files can override any field.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace as _replace
from pathlib import Path
from typing import Optional

import yaml

from garden_core.config import load_yaml
from garden_core.stage_style import DEFAULT_STYLE, StyleResolver, StaticResolver
from garden_core.types import BgStyle, StyleDef

log = logging.getLogger(__name__)

__all__ = ["StyleMold", "MOLDS", "mold_to_style", "YamlStyleResolver"]


@dataclass(frozen=True)
class StyleMold:
    """Ratios relative to font_size / video_height. Resolution-independent."""

    name: str
    font_size_ratio: float = 0.052        # font_size / video_height
    outline_ratio: float = 0.036          # outline_width / font_size
    shadow_ratio: float = 0.014           # shadow_depth / font_size
    padding_h_ratio: float = 0.15         # box horizontal pad / font_size
    padding_v_ratio: float = 0.08         # box vertical pad / font_size
    corner_radius_ratio: float = 0.0      # box corner r / font_size
    margin_v_ratio: float = 0.042         # margin_v / video_height
    bold: bool = False
    bg_kind: Optional[str] = None         # None | "frosted_glass" | "rounded"
    bg_alpha: int = 180
    primary_color: str = "&H00FFFFFF"
    outline_color: str = "&H00000000"
    shadow_color: str = "&H96000000"
    position: str = "bottom"
    font_family: str = "Noto Serif SC"


MOLDS: dict[str, StyleMold] = {
    "default": StyleMold(name="default"),
    "classic_outline": StyleMold(
        name="classic_outline", outline_ratio=0.036, shadow_ratio=0.014,
        padding_h_ratio=0.15, padding_v_ratio=0.08, bold=True,
    ),
    "frosted_glass": StyleMold(
        name="frosted_glass", outline_ratio=0.02, shadow_ratio=0.01,
        padding_h_ratio=0.20, padding_v_ratio=0.12, corner_radius_ratio=0.08,
        bg_kind="frosted_glass", bg_alpha=180,
    ),
    "minimal_clean": StyleMold(
        name="minimal_clean", outline_ratio=0.0, shadow_ratio=0.0,
        padding_h_ratio=0.10, padding_v_ratio=0.05, margin_v_ratio=0.040,
    ),
    "bold_impact": StyleMold(
        name="bold_impact", outline_ratio=0.05, shadow_ratio=0.02,
        padding_h_ratio=0.18, padding_v_ratio=0.10, margin_v_ratio=0.035, bold=True,
    ),
    "cinematic": StyleMold(
        name="cinematic", outline_ratio=0.025, shadow_ratio=0.02,
        padding_h_ratio=0.12, padding_v_ratio=0.06, margin_v_ratio=0.045,
    ),
    "broadcast": StyleMold(
        name="broadcast", outline_ratio=0.03, shadow_ratio=0.01,
        padding_h_ratio=0.22, padding_v_ratio=0.10, corner_radius_ratio=0.06,
        bg_kind="rounded", bg_alpha=160,
    ),
}


def mold_to_style(mold: StyleMold) -> StyleDef:
    """Expand a mold into a StyleDef. Font sizes resolve against video_height
    on demand (StyleDef.font_size_px)."""
    bg: Optional[BgStyle] = None
    if mold.bg_kind:
        # padding/corner stored as ratios; rendered units computed in ass_writer
        # from font_size — so we stash ratios as-is here (px values derived at
        # render time). For simplicity store padding as a ratio of font size
        # already scaled: ass_writer adds `pad` as flat px, so we encode the
        # ratio*~54 reference here (font_size at 1080 ≈ 54). A cleaner pass:
        bg = BgStyle(
            kind=mold.bg_kind,
            corner_radius=mold.corner_radius_ratio,  # ratio; scaled in ass_writer
            padding=mold.padding_h_ratio,            # ratio; scaled in ass_writer
            alpha=mold.bg_alpha,
        )
    return StyleDef(
        name=mold.name,
        font_family=mold.font_family,
        font_size_ratio=mold.font_size_ratio,
        primary_color=mold.primary_color,
        outline_color=mold.outline_color,
        # outline_width / shadow_depth are stored as RATIOS of font_size;
        # ass_writer scales them to px via font_size_px(video_height).
        outline_width=mold.outline_ratio,
        shadow_color=mold.shadow_color,
        shadow_depth=mold.shadow_ratio,
        background=bg,
        position=mold.position,
        bold=mold.bold,
    )


def _apply_overrides(base: StyleDef, overrides: dict) -> StyleDef:
    """Return a new StyleDef with valid field overrides from a YAML dict."""
    valid = {f.name for f in __import__("dataclasses").fields(StyleDef)}
    picked = {k: v for k, v in overrides.items() if k in valid}
    if "background" in overrides and isinstance(overrides["background"], dict):
        bgd = overrides["background"]
        valid_bg = {f.name for f in __import__("dataclasses").fields(BgStyle)}
        picked["background"] = BgStyle(**{k: v for k, v in bgd.items() if k in valid_bg})
    return _replace(base, **picked) if picked else base


class YamlStyleResolver(StyleResolver):
    """Resolve styles from a directory of YAML files + built-in molds.

    Lookup order: <name>.yaml override → built-in mold → DEFAULT_STYLE.
    One path, one type (fixes bug #3).
    """

    def __init__(self, config_dir: Optional[str | Path] = None) -> None:
        self.config_dir = Path(config_dir) if config_dir else None

    def resolve(self, style_name: str, video_height: int) -> StyleDef:
        # 1. YAML override
        if self.config_dir:
            yaml_path = self.config_dir / f"{style_name}.yaml"
            data = load_yaml(yaml_path)
            if data:
                base_mold = MOLDS.get(data.get("mold", style_name), MOLDS["default"])
                base = mold_to_style(base_mold)
                if data.get("mold"):
                    base = _replace(base, name=style_name)
                return _apply_overrides(base, data)
        # 2. built-in mold
        if style_name in MOLDS:
            return mold_to_style(MOLDS[style_name])
        # 3. default
        return DEFAULT_STYLE
