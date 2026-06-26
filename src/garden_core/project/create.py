"""create_project — project scaffolding: directory tree + project.yaml + defaults.

Implements T8 of the project management system (DEVELOPMENT_PLAN.md D1).
Creates a project directory from the template described in
``project-directory-template.md``, writes a validated ``project.yaml`` via
T7's ``ProjectConfig.to_yaml``, and returns the ``ProjectConfig`` so the
caller can immediately proceed (or later call ``load_project`` to read it back).
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import yaml

from garden_core.config import ConfigError
from garden_core.project.config import ProjectConfig, validate
from garden_core.project.schema import (
    ProofOptsSpec,
    ProjectMeta,
    RenderOptsSpec,
    SourceSpec,
    TranscriptSpec,
)

__all__ = ["create_project"]

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

# Wiki sub-directories for garden-style projects (A–M, full set from the
# project-directory-template).
_WIKI_DIRS: tuple[str, ...] = (
    "A_花园地图",
    "B_创作宣言",
    "C_〈原著参考〉",
    "D_花园对话",
    "E_人类创作",
    "F_AI 创作",
    "G_发布管线",
    "H_发布渠道",
    "I_发布日志",
    "J_长期反馈",
    "K_行者社群",
    "L_开源说明",
    "M_概念花园",
)

# 4K production default for render_opts (aligns with tesla_stage04).
_DEFAULT_4K_RENDER_OPTS = RenderOptsSpec(
    output_dir="output/clips",
    horizontal_width=3840,
    horizontal_height=2160,
    vertical_width=1080,
    vertical_height=1920,
    crf=18,
)

# Minimal AGENTS.md template (T13 will elaborate).
_AGENTS_MD_TEMPLATE = """\
# AGENTS.md

> 本文件供 AI 编码执行器（Reasonix / Claude Code 等）在处理本项目时自动加载。

## 花园精神

- 花园不是广播：对话是原点，发布是漂流瓶。
- AI 是共创者不是工具。
- 制作过程透明：从原始对话到成品的全链路可追溯。
- 分岔是方法：不追求“唯一主线”，各路径同时存在。

## 权限边界

- 可读/写本项目目录下的所有文件。
- 不访问项目目录以外的任意路径（除非项目配置文件显式指向）。
- 不执行网络请求（除非项目配置显式允许）。

## 项目信息

本项目由 `garden_core.project.create_project` 生成。
项目配置见 `project.yaml`，运行入口见对应 SKILL.md。
"""

# Minimal README.md template (T13 will elaborate).
_README_MD_TEMPLATE = """\
# {name}

项目入口: `load_project(\"{root_dir}\")` — 使用 `garden_core.project` 加载 `project.yaml`。

> 生成工具: `garden_core.project.create_project`
"""


# --------------------------------------------------------------------------- #
# create_project
# --------------------------------------------------------------------------- #
def create_project(
    name: str,
    root_dir: str | Path,
    *,
    sources: Sequence[SourceSpec],
    audio_path: str | None = None,
    style: str = "fresh",
    render_opts: RenderOptsSpec | None = None,
    corrections: dict | None = None,
    wiki: bool = False,
    overwrite: bool = False,
) -> ProjectConfig:
    """Scaffold a new project directory and return a validated ProjectConfig.

    Parameters
    ----------
    name:
        Project name — written to ``meta.name`` and used in README / path
        placeholders.
    root_dir:
        Project root directory.  Created if it does not exist.
    sources:
        One or more ``SourceSpec`` entries (at least one — validated).
    audio_path:
        Path to the source audio for ASR transcription.  ``None`` (default)
        uses the placeholder ``source/<name>.wav``.
    style:
        Style name (must exist in ``stage_style/styles/``).  Default ``"fresh"``.
    render_opts:
        Render options.  ``None`` (default) uses a 4K production preset
        (3840×2160 horizontal / 1080×1920 vertical / crf 18).
    corrections:
        Initial corrections dict for ``corrections.yaml``.  ``None`` writes
        an empty mapping ``{}``.
    wiki:
        When ``True``, create the full Wiki sub-tree (``Wiki/<name>/A..M``).
        Default ``False`` (minimal skeleton only).
    overwrite:
        When ``False`` (default), refuse to create inside a non-empty
        directory.  When ``True``, allow overwriting — but **never** deletes
        ``source/`` content.

    Returns
    -------
    ProjectConfig
        The validated, fully-constructed config (also written to
        ``root_dir/project.yaml``).

    Raises
    ------
    ConfigError
        If ``overwrite=False`` and ``root_dir`` already exists and is
        non-empty, or if validation fails (e.g. unknown style name,
        duplicate source ids, …).
    """
    root = Path(root_dir).resolve()

    # --- overwrite guard ----------------------------------------------------
    if root.exists():
        if not root.is_dir():
            raise ConfigError(
                f"Cannot create project: '{root}' exists but is not a directory"
            )
        contents = list(root.iterdir())
        if contents and not overwrite:
            raise ConfigError(
                f"Project root '{root}' already exists and is not empty; "
                f"use overwrite=True to allow, or choose a different root_dir. "
                f"Existing entries: {sorted(p.name for p in contents)}"
            )

    # --- build config (in memory, before touching disk) --------------------
    resolved_audio_path = audio_path if audio_path is not None else f"source/{name}.wav"
    resolved_render_opts = render_opts if render_opts is not None else _DEFAULT_4K_RENDER_OPTS

    cfg = ProjectConfig(
        meta=ProjectMeta(name=name, root=str(root)),
        sources=tuple(sources),
        transcript=TranscriptSpec(
            audio_path=resolved_audio_path,
            path="output/transcript.json",
        ),
        errata_path="corrections.yaml",
        proof_opts=ProofOptsSpec(),
        cut_points=(),
        style_name=style,
        render_opts=resolved_render_opts,
        output_dir="output",
    )

    # --- validate before touching disk (create = validate) ------------------
    validate(cfg)

    # --- create directory tree ----------------------------------------------
    # Output sub-directories
    for sub in ("clips", "fullcut", "release"):
        (root / "output" / sub).mkdir(parents=True, exist_ok=True)

    # Source directory
    (root / "source").mkdir(parents=True, exist_ok=True)

    # Wiki (garden-style)
    if wiki:
        wiki_root = root / "Wiki" / name
        for d in _WIKI_DIRS:
            (wiki_root / d).mkdir(parents=True, exist_ok=True)

    # --- write files --------------------------------------------------------
    # project.yaml
    cfg.to_yaml(root / "project.yaml")

    # corrections.yaml
    _write_corrections(root / "corrections.yaml", corrections)

    # AGENTS.md
    (root / "AGENTS.md").write_text(_AGENTS_MD_TEMPLATE, encoding="utf-8")

    # README.md
    readme = _README_MD_TEMPLATE.format(name=name, root_dir=str(root))
    (root / "README.md").write_text(readme, encoding="utf-8")

    return cfg


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _write_corrections(path: Path, corrections: dict | None) -> None:
    """Write corrections.yaml — empty ``{}`` when *corrections* is None."""
    payload = {} if corrections is None else corrections
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(payload, fh, allow_unicode=True, sort_keys=False)
