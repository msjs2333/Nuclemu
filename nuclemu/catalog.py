"""Discover built-in experiments and user-selected, trusted Python modules."""

from __future__ import annotations

from collections.abc import Iterable
from importlib import import_module
from pathlib import Path
from pkgutil import iter_modules
from runpy import run_path

from . import experiments
from .core import Experiment


def discover(paths: Iterable[str | Path] = ()) -> dict[str, Experiment]:
    """Collect EXPERIMENT definitions; each extra directory holds *.py modules."""
    definitions: dict[str, Experiment] = {}
    origins: dict[str, str] = {}

    def register(definition: object, origin: str) -> None:
        if not isinstance(definition, Experiment):
            raise ValueError(f"{origin}: expected an Experiment named EXPERIMENT")
        if definition.id in definitions:
            raise ValueError(
                f"duplicate experiment {definition.id!r}: {origin} and {origins[definition.id]}"
            )
        definitions[definition.id] = definition
        origins[definition.id] = origin

    for info in iter_modules(experiments.__path__):
        if not info.name.startswith("_"):
            name = f"{experiments.__name__}.{info.name}"
            try:
                definition = getattr(import_module(name), "EXPERIMENT", None)
            except Exception as error:
                raise ValueError(f"{name}: {error}") from error
            register(definition, name)

    for path in paths:
        directory = Path(path)
        if not directory.is_dir():
            raise ValueError(f"Experiment directory does not exist: {directory}")
        for file in sorted(directory.glob("*.py")):
            if file.name.startswith("_"):
                continue
            try:
                definition = run_path(str(file)).get("EXPERIMENT")
            except Exception as error:
                raise ValueError(f"{file}: {error}") from error
            register(definition, str(file))
    return definitions
