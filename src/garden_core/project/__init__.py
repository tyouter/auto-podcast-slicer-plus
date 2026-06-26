"""garden_core.project — project.yaml schema, config model, and runtime orchestration.

Import path::

    from garden_core.project import (
        ProjectConfig,
        ProjectMeta,
        SourceSpec,
        CutPointSpec,
        RenderOptsSpec,
        ProofOptsSpec,
        TranscriptSpec,
        validate,
        create_project,
        load_project,
        edit_project,
        ProjectRun,
    )
"""

from garden_core.project.config import ProjectConfig, validate
from garden_core.project.create import create_project
from garden_core.project.edit import edit_project
from garden_core.project.load import load_project
from garden_core.project.run import ProjectRun
from garden_core.project.schema import (
    CutPointSpec,
    ProjectMeta,
    ProofOptsSpec,
    RenderOptsSpec,
    SourceSpec,
    TranscriptSpec,
)

__all__ = [
    "ProjectConfig",
    "ProjectMeta",
    "SourceSpec",
    "CutPointSpec",
    "RenderOptsSpec",
    "ProofOptsSpec",
    "TranscriptSpec",
    "validate",
    "create_project",
    "load_project",
    "edit_project",
    "ProjectRun",
]
