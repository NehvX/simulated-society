"""Quantitative-genetics checks for trait inheritance."""
import random
import statistics

from civitas.config import TraitParams
from civitas.traits import TRAIT_NAMES, describe, founder_traits, inherited_traits

H2 = TraitParams().heritability


def slope(xs, ys):
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return cov / sum((x - mx) ** 2 for x in xs)


def test_founders_are_standardised():
    rng = random.Random(0)
    pop = [founder_traits(rng, H2)[1] for _ in range(5000)]
    for k in range(len(TRAIT_NAMES)):
        values = [t[k] for t in pop]
        assert abs(statistics.fmean(values)) < 0.05
        assert 0.93 < statistics.pvariance(values) < 1.07


def test_infinitesimal_model_preserves_variance_across_generations():
    """Mid-parent + segregation noise keeps Var(trait) ~ 1 generation after generation."""
    rng = random.Random(1)
    pop = [founder_traits(rng, H2) for _ in range(3000)]
    for _ in range(6):
        pop = [inherited_traits(rng, *(g for g, _ in rng.sample(pop, 2)), H2) for _ in range(3000)]
    for k in range(len(TRAIT_NAMES)):
        assert 0.88 < statistics.pvariance([t[k] for _, t in pop]) < 1.12


def test_naive_averaging_from_the_original_code_collapses_variance():
    """The original `(x + y) / 2 + uniform(-0.05, 0.05)` halves the variance every
    generation: after 6 generations almost everyone is identical."""
    rng = random.Random(2)
    pop = [rng.uniform(0.1, 1.0) for _ in range(3000)]
    start = statistics.pvariance(pop)
    for _ in range(6):
        pop = [(rng.choice(pop) + rng.choice(pop)) / 2 + rng.uniform(-0.05, 0.05) for _ in range(3000)]
    assert statistics.pvariance(pop) < 0.1 * start


def test_midparent_offspring_slope_equals_heritability():
    """Textbook identity: regressing offspring on mid-parent phenotype gives h^2."""
    rng = random.Random(3)
    for trait in ("conscientiousness", "intelligence"):
        k = TRAIT_NAMES.index(trait)
        xs, ys = [], []
        for _ in range(20000):
            gm, tm = founder_traits(rng, H2)
            gf, tf = founder_traits(rng, H2)
            _, tc = inherited_traits(rng, gm, gf, H2)
            xs.append((tm[k] + tf[k]) / 2)
            ys.append(tc[k])
        assert abs(slope(xs, ys) - H2[trait]) < 0.04


def test_describe_picks_extreme_traits():
    words = describe({name: 0.0 for name in TRAIT_NAMES} | {"honesty": 2.0, "openness": -1.5})
    assert words == ["scrupulously honest", "conventional"]
