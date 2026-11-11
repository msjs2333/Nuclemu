"""Python entry point for the local browser workbench."""

from .workbench import Workbench as Workbench


def launch(paths=()):
    """Open the Web workbench using the supplied experiment discovery paths."""
    from .web import launch as launch_web

    return launch_web(paths=paths)
