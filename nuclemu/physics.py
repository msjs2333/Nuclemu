"""Shared physical objects and counting statistics used by the lab models."""

from dataclasses import dataclass
from math import exp, floor, isfinite, lgamma, log, sqrt
from random import Random


@dataclass(frozen=True)
class AluminumFoil:
    """Homogeneous aluminium at nominal density 2.70 g/cm³; thickness in mm."""

    thickness_mm: float

    def __post_init__(self) -> None:
        if not isfinite(self.thickness_mm) or self.thickness_mm < 0:
            raise ValueError("Foil thickness must be finite and nonnegative")

    @property
    def areal_density_g_cm2(self) -> float:
        return self.thickness_mm / 10 * 2.70


def poisson(mean: float, rng: Random) -> int:
    """Draw a Poisson count using the session's random stream."""
    if not isfinite(mean) or mean < 0:
        raise ValueError("Poisson mean must be finite and nonnegative")
    if mean == 0:
        return 0
    if mean < 30:
        threshold = exp(-mean)
        product = rng.random()
        count = 0
        while product > threshold:
            product *= rng.random()
            count += 1
        return count

    # Transformed rejection (Hörmann, Insurance: Mathematics and Economics,
    # 1993, doi:10.1016/0167-6687(93)90997-4). Cost stays low at high rates.
    root = sqrt(mean)
    b = 0.931 + 2.53 * root
    a = -0.059 + 0.02483 * b
    inverse_alpha = 1.1239 + 1.1328 / (b - 3.4)
    fast_acceptance = 0.9277 - 3.6224 / (b - 2)
    while True:
        u = rng.random() - 0.5
        v = rng.random()
        gap = 0.5 - abs(u)
        if gap == 0:
            continue
        candidate = floor((2 * a / gap + b) * u + mean + 0.43)
        if gap >= 0.07 and v <= fast_acceptance:
            return candidate
        if candidate < 0 or (gap < 0.013 and v > gap):
            continue
        if v == 0 or log(v * inverse_alpha / (a / (gap * gap) + b)) <= (
            -mean + candidate * log(mean) - lgamma(candidate + 1)
        ):
            return candidate
