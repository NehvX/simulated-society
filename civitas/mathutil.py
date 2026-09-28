"""Small numerical helpers shared by every subsystem.

Almost every decision in Civitas is a *discrete choice*: an agent compares the
utility of doing something against not doing it, and acts with probability

    P(act) = sigma(U) = 1 / (1 + exp(-U))

which is the logit model of random-utility theory (McFadden, 1974). When there
are several options we use the multinomial version (softmax).
"""
from __future__ import annotations

import math
import random
from typing import Sequence, TypeVar

T = TypeVar("T")

SQRT2 = math.sqrt(2.0)


def sigmoid(x: float) -> float:
    """Logistic function, numerically stable for large |x|."""
    if x >= 0.0:
        return 1.0 / (1.0 + math.exp(-x))
    z = math.exp(x)
    return z / (1.0 + z)


def normal_cdf(z: float) -> float:
    """Phi(z): converts a trait z-score into a population percentile in [0, 1]."""
    return 0.5 * (1.0 + math.erf(z / SQRT2))


def clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def rate_to_prob(annual_rate: float, months: float = 1.0) -> float:
    """Probability of >= 1 event in `months` for a Poisson hazard given per year."""
    return 1.0 - math.exp(-annual_rate * months / 12.0)


def poisson(rng: random.Random, lam: float) -> int:
    """Knuth's Poisson sampler (fine for the small rates used here)."""
    if lam <= 0.0:
        return 0
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def weighted_choice(rng: random.Random, items: Sequence[T], weights: Sequence[float]) -> T:
    return rng.choices(items, weights=weights, k=1)[0]


def softmax_choice(rng: random.Random, items: Sequence[T], utilities: Sequence[float]) -> T:
    """Multinomial logit choice: P(i) = exp(U_i) / sum_j exp(U_j)."""
    top = max(utilities)
    weights = [math.exp(u - top) for u in utilities]
    return rng.choices(items, weights=weights, k=1)[0]


def mean(values: Sequence[float], default: float = 0.0) -> float:
    return sum(values) / len(values) if values else default
