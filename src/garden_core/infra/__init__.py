"""Infrastructure layer: cross-cutting concerns shared by all stages.

Nothing here mutates pipeline data. Stages receive infra objects
(LLMClient, Aligner, …) via dependency injection — no module-level globals.
"""
