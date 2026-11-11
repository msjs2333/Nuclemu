"""Discover built-in experiments and user-selected, trusted Python modules."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict
from importlib import import_module
from pathlib import Path
from pkgutil import iter_modules
from runpy import run_path

from . import experiments
from .core import Component, Experiment


def describe(experiment: Experiment) -> dict:
    """Return the public catalogue entry without constructing a session."""
    parts = experiment.components
    if not parts:
        parts = tuple(Component(f"device-{d.id}", "instrument", d.label, device=d.id)
                      for d in experiment.devices)
        if experiment.parameters:
            controls = Component("controls", "controls", "实验参数",
                                 parameters=tuple(p.key for p in experiment.parameters))
            parts = (controls, *parts)
    return {
        "id": experiment.id,
        "title": experiment.title,
        "course": experiment.course,
        "description": experiment.description,
        "question": experiment.question or experiment.description,
        "guide": list(experiment.guide) or [experiment.description],
        "parameters": [dict(asdict(p), options=[{"value": value, "label": label}
                                               for value, label in p.options])
                       for p in experiment.parameters],
        "devices": [dict(asdict(d), background_conditions=dict(d.background_conditions))
                    for d in experiment.devices],
        "components": [asdict(part) for part in parts],
        "connections": [asdict(link) for link in experiment.connections],
    }


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
