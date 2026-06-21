"""garden-core: clean rewrite of the podcast clipping + subtitle pipeline.

See ARCHITECTURE.md / README.md for the 7-stage design. Import path::

    from garden_core.types import Transcript, Cue
    from garden_core.pipeline import run_full_pipeline
"""

from garden_core import types

__version__ = "0.1.0"
__all__ = ["types", "__version__"]
