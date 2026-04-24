from __future__ import annotations

from .coordatt import CoordAtt, ResidualCoordAtt


def register_custom_modules() -> None:
    """Register project-local modules for Ultralytics YAML parsing."""

    import ultralytics.nn.tasks as tasks

    tasks.CoordAtt = CoordAtt
    tasks.ResidualCoordAtt = ResidualCoordAtt
