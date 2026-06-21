"""I/O boundary layer: the ONLY place that touches the filesystem directly.

Stages themselves are pure. Source reads foreign JSON/transcript formats and
emits typed Transcript objects; Sink writes typed artifacts to disk.
"""
