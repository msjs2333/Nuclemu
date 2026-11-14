"""Reuse the alpha apparatus with a half-micrometre aluminium sheet option.

Start the workbench with ``python -m nuclemu gui --path examples/courses``.
This course shares the CSDA response, detector port and spectrum panel; only
the teaching menu of physically supported sheet thicknesses changes.
"""

from dataclasses import replace

from nuclemu.experiments.alpha import EXPERIMENT as ALPHA


EXPERIMENT = replace(
    ALPHA, id="alpha-fine-foil", title="α 能量损失：薄箔规格比较",
    parameters=tuple(replace(p, minimum=0.5,
                            options=((0.5, "Al 0.5 µm/片"), (1.0, "Al 1 µm/片"), (2.0, "Al 2 µm/片")))
                     if p.key == "foil_spec_um" else p for p in ALPHA.parameters),
)
