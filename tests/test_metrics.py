"""The social-science measures behave as their textbook definitions say."""
import math
import random

import pytest

from civitas import metrics


def test_gini_extremes():
    assert metrics.gini([5, 5, 5, 5]) == pytest.approx(0.0)
    assert metrics.gini([0, 0, 0, 10]) == pytest.approx(0.75)        # (n - 1) / n
    assert metrics.gini([-100, 0, 0, 10]) == pytest.approx(0.75)     # debts floored at zero
    assert metrics.gini([]) == 0.0


def test_top_share_and_lorenz():
    values = [1] * 9 + [91]
    assert metrics.top_share(values, 0.10) == pytest.approx(0.91)
    curve = metrics.lorenz_curve(values)
    assert curve[0] == (0.0, 0.0) and curve[-1] == pytest.approx((1.0, 1.0))
    assert all(y <= x + 1e-9 for x, y in curve)                        # never above equality


def test_poverty_rate():
    assert metrics.poverty_rate([100, 1000, 1000, 1000, 1000]) == pytest.approx(0.2)


def test_life_table_constant_hazard():
    """With a constant death rate m, life expectancy is 1/m."""
    m = 0.02
    exposure = [1000.0] * 19
    deaths = [m * e for e in exposure]
    assert metrics.life_expectancy(deaths, exposure) == pytest.approx(1 / m, rel=0.03)


def test_total_fertility_rate():
    births = [10] * 7
    exposure = [100.0] * 7                 # 0.1 births per woman-year in every band
    assert metrics.total_fertility_rate(births, exposure) == pytest.approx(3.5)


def test_rank_rank_slope():
    rng = random.Random(0)
    parents = [rng.random() for _ in range(2000)]
    assert metrics.rank_rank_slope(parents, parents) == pytest.approx(1.0, abs=1e-3)
    independent = [rng.random() for _ in range(2000)]
    assert abs(metrics.rank_rank_slope(parents, independent)) < 0.08


def test_dissimilarity_index():
    assert metrics.dissimilarity_index([0, 0, 1, 1], [0, 0, 1, 1], 3) == pytest.approx(0.0)
    assert metrics.dissimilarity_index([0, 0, 0], [2, 2, 2], 3) == pytest.approx(1.0)


def test_bimodality_coefficient_separates_one_camp_from_two():
    rng = random.Random(1)
    one = [rng.gauss(0, 1) for _ in range(3000)]
    two = [rng.gauss(-2, 0.4) for _ in range(1500)] + [rng.gauss(2, 0.4) for _ in range(1500)]
    assert metrics.bimodality_coefficient(one) < 0.555 < metrics.bimodality_coefficient(two)


def test_weighted_assortativity():
    pairs = [(x, x, 1.0) for x in (-1, -0.5, 0, 0.5, 1)]
    assert metrics.weighted_assortativity(pairs) == pytest.approx(1.0)
    anti = [(x, -x, 1.0) for x in (-1, -0.5, 0, 0.5, 1)]
    assert metrics.weighted_assortativity(anti) == pytest.approx(-1.0)


def test_ols_recovers_coefficients():
    rng = random.Random(2)
    X = [[rng.gauss(0, 1), rng.gauss(0, 1)] for _ in range(500)]
    y = [3 + 2 * a - 0.5 * b for a, b in X]
    beta, r2 = metrics.ols(y, X)
    assert beta == pytest.approx([3, 2, -0.5])
    assert r2 == pytest.approx(1.0)
    assert not math.isnan(r2)
