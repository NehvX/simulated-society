"""Standard social-science measures computed on the simulated population."""
from __future__ import annotations

import math
import random
from typing import Iterable, Sequence

import numpy as np

AGE_BAND_WIDTHS = [1, 4] + [5] * 16 + [math.inf]          # matches demography.age_band


def gini(values: Iterable[float]) -> float:
    """Gini coefficient (0 = perfect equality, 1 = one person has everything).
    Negative net worth is floored at zero, as is conventional."""
    x = np.sort(np.clip(np.asarray(list(values), dtype=float), 0.0, None))
    n, total = len(x), x.sum()
    if n == 0 or total <= 0:
        return 0.0
    ranks = np.arange(1, n + 1)
    return float(2.0 * np.sum(ranks * x) / (n * total) - (n + 1.0) / n)


def lorenz_curve(values: Iterable[float], points: int = 21) -> list[tuple[float, float]]:
    x = np.sort(np.clip(np.asarray(list(values), dtype=float), 0.0, None))
    if len(x) == 0 or x.sum() <= 0:
        return [(i / (points - 1), i / (points - 1)) for i in range(points)]
    cum = np.concatenate([[0.0], np.cumsum(x)]) / x.sum()
    grid = np.linspace(0.0, 1.0, points)
    return [(float(g), float(np.interp(g * len(x), np.arange(len(x) + 1), cum))) for g in grid]


def top_share(values: Iterable[float], q: float = 0.10) -> float:
    x = np.sort(np.clip(np.asarray(list(values), dtype=float), 0.0, None))[::-1]
    if len(x) == 0 or x.sum() <= 0:
        return 0.0
    k = max(1, int(round(q * len(x))))
    return float(x[:k].sum() / x.sum())


def poverty_rate(incomes: Sequence[float], line: float = 0.5) -> float:
    """OECD relative poverty: share with income below 50% of the median."""
    if not incomes:
        return 0.0
    threshold = line * float(np.median(incomes))
    return sum(1 for y in incomes if y < threshold) / len(incomes)


def bimodality_coefficient(values: Sequence[float]) -> float:
    """Sarle's b = (skew^2 + 1) / (excess kurtosis + 3(n-1)^2/((n-2)(n-3))).
    b > 0.555 (the uniform distribution's value) suggests two camps."""
    x = np.asarray(values, dtype=float)
    n = len(x)
    if n < 4 or x.std() == 0:
        return 0.0
    z = (x - x.mean()) / x.std()
    skew = float(np.mean(z ** 3))
    kurt = float(np.mean(z ** 4)) - 3.0
    return (skew ** 2 + 1.0) / (kurt + 3.0 * (n - 1) ** 2 / ((n - 2) * (n - 3)))


def weighted_assortativity(pairs: Sequence[tuple[float, float, float]]) -> float:
    """Weighted Pearson correlation of an attribute across network ties.
    Near +1 means echo chambers (friends think alike)."""
    if len(pairs) < 3:
        return 0.0
    a = np.array(pairs, dtype=float)
    x, y, w = a[:, 0], a[:, 1], a[:, 2]
    mx, my = np.average(x, weights=w), np.average(y, weights=w)
    cov = np.average((x - mx) * (y - my), weights=w)
    sx = math.sqrt(np.average((x - mx) ** 2, weights=w))
    sy = math.sqrt(np.average((y - my) ** 2, weights=w))
    return float(cov / (sx * sy)) if sx > 0 and sy > 0 else 0.0


def dissimilarity_index(group_a: Sequence[int], group_b: Sequence[int], n_units: int) -> float:
    """Duncan & Duncan (1955): D = 1/2 sum_u |a_u/A - b_u/B|. The share of one
    group that would have to move for both to be spread evenly across units."""
    if not group_a or not group_b:
        return 0.0
    ca, cb = np.bincount(group_a, minlength=n_units), np.bincount(group_b, minlength=n_units)
    return float(0.5 * np.abs(ca / ca.sum() - cb / cb.sum()).sum())


def clustering_coefficient(people, rng: random.Random, sample: int = 150, min_strength: float = 0.15) -> float:
    """Average local clustering of the (thresholded) friendship graph, on a sample."""
    alive = [p for p in people if p.alive]
    if not alive:
        return 0.0
    coeffs = []
    by_id = {p.id: p for p in alive}
    for p in rng.sample(alive, min(sample, len(alive))):
        nbrs = [i for i, t in p.ties.items() if t.strength >= min_strength and i in by_id]
        k = len(nbrs)
        if k < 2:
            continue
        nbr_set = set(nbrs)
        links = sum(1 for i in nbrs for j, t in by_id[i].ties.items()
                    if j in nbr_set and t.strength >= min_strength)
        coeffs.append(links / (k * (k - 1)))
    return float(np.mean(coeffs)) if coeffs else 0.0


def ols(y: Sequence[float], X: Sequence[Sequence[float]]) -> tuple[np.ndarray, float]:
    """Ordinary least squares with intercept. Returns (coefficients, R^2)."""
    Y = np.asarray(y, dtype=float)
    M = np.column_stack([np.ones(len(Y)), np.asarray(X, dtype=float)])
    beta, *_ = np.linalg.lstsq(M, Y, rcond=None)
    resid = Y - M @ beta
    ss_tot = float(((Y - Y.mean()) ** 2).sum())
    r2 = 1.0 - float((resid ** 2).sum()) / ss_tot if ss_tot > 0 else 0.0
    return beta, r2


def rank_rank_slope(parent_pct: Sequence[float], child_values: Sequence[float]) -> float | None:
    """Chetty et al. (2014) intergenerational mobility: regress the child's
    income rank on the parents' rank. US ~0.34, Denmark ~0.18."""
    if len(parent_pct) < 10:
        return None
    child_rank = percentile_ranks(child_values)
    parent_rank = percentile_ranks(parent_pct)        # both generations ranked within the sample
    beta, _ = ols(child_rank, [[x] for x in parent_rank])
    return float(beta[1])


def percentile_ranks(values: Sequence[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    for r, i in enumerate(order):
        ranks[i] = (r + 0.5) / len(values)
    return ranks


def life_expectancy(deaths: Sequence[float], exposure: Sequence[float]) -> float | None:
    """Period life expectancy at birth from an abridged life table (Chiang 1984).
        m_x = D_x / E_x,  q_x = n m_x / (1 + (n - a_x) m_x),  e_0 = sum(L_x) / l_0
    """
    if sum(deaths) < 5:
        return None
    l, total = 1.0, 0.0
    for x, n in enumerate(AGE_BAND_WIDTHS):
        m = deaths[x] / exposure[x] if exposure[x] > 0 else 0.0
        if math.isinf(n):
            total += l / m if m > 0 else l * 10.0
            break
        a = 0.1 if x == 0 else n / 2.0
        q = min(1.0, n * m / (1.0 + (n - a) * m))
        survivors = l * (1.0 - q)
        total += n * survivors + a * (l - survivors)
        l = survivors
    return total


def total_fertility_rate(births: Sequence[float], female_exposure: Sequence[float]) -> float | None:
    """TFR = 5 * sum of age-specific fertility rates over the 15-49 bands."""
    if sum(female_exposure) <= 0:
        return None
    return 5.0 * sum(b / e for b, e in zip(births, female_exposure) if e > 0)
