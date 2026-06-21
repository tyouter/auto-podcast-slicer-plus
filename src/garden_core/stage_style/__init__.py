"""Stage 6: style resolution.

Single resolution path (fixes legacy bug #3: SubtitleStyle + StyleDefinition
two parallel systems). A ``StyleResolver`` maps ``style_name`` → ``StyleDef``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from garden_core.types import StyleDef

__all__ = ["StyleResolver", "resolve_style", "DEFAULT_STYLE"]


# A sensible built-in default so the pipeline always has something to render
# even before any config is loaded.
DEFAULT_STYLE = StyleDef(
    name="default",
    font_family="Noto Serif SC",
    font_size_ratio=0.052,
    primary_color="&H00FFFFFF",
    outline_color="&H00000000",
    outline_width=0.036,   # ratio of font_size → ~1px outline at 1080p
    shadow_color="&H96000000",
    shadow_depth=0.014,    # ratio of font_size → ~0.4px shadow at 1080p
    background=None,
    position="bottom",
    bold=False,
)


class StyleResolver(ABC):
    """Maps style_name → StyleDef. Stateless on the caller side; load once."""

    @abstractmethod
    def resolve(self, style_name: str, video_height: int) -> StyleDef: ...


class StaticResolver(StyleResolver):
    """Trivial resolver backed by a dict. Useful for tests / simple configs."""

    def __init__(self, styles: dict[str, StyleDef]) -> None:
        self._styles = styles

    def resolve(self, style_name: str, video_height: int) -> StyleDef:
        return self._styles.get(style_name) or self._styles.get("default") or DEFAULT_STYLE


def resolve_style(
    style_name: str,
    video_height: int,
    resolver: StyleResolver,
) -> StyleDef:
    """Run stage 6: name → resolved StyleDef (font sizes scaled to video)."""
    style = resolver.resolve(style_name, video_height)
    # font_size_px is derived on demand; nothing to mutate on the frozen object.
    return style
