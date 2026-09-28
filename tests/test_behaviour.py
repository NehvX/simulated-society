"""Each behavioural equation responds in the direction the theory predicts."""
import math

import pytest

from civitas import SimConfig, Simulation
from civitas.economy import OCC
from civitas.person import FRIEND, WORK, Person, Tie
from civitas.traits import TRAIT_NAMES
from civitas.wellbeing import reference_health


@pytest.fixture(scope="module")
def sim():
    return Simulation(SimConfig(seed=5, initial_population=80, burn_in_months=0, verbose=False))


def person(sim, **traits) -> Person:
    values = [traits.get(t, 0.0) for t in TRAIT_NAMES]
    p = Person(10_000, "F", -12 * 30, "Test", "Person", [0.0] * 7, values, 2)
    p.stage, p.education, p.inst_trust = WORK, 12, 0.5
    return p


def test_trust_is_bayesian(sim):
    p = person(sim)
    tie = Tie(0.3, 0.5, FRIEND)
    before = tie.trust
    sim.social._learn(p, tie, other_cooperated=True)
    assert tie.trust > before
    after_good = tie.trust
    sim.social._learn(p, tie, other_cooperated=False)
    assert tie.trust < after_good


def test_betrayal_hurts_more_than_kindness_helps(sim):
    """Negativity bias: one defection costs more closeness than one kind act adds."""
    p = person(sim)
    up, down = Tie(0.5, 0.5), Tie(0.5, 0.5)
    sim.social._learn(p, up, True)
    sim.social._learn(p, down, False)
    assert (0.5 - down.strength) > (up.strength - 0.5)


def test_cooperation_rises_with_honesty_trust_and_closeness(sim):
    tie = Tie(0.3, 0.6)
    base = sim.social.p_cooperate(person(sim), tie, 0)
    assert sim.social.p_cooperate(person(sim, honesty=2.0), tie, 0) > base
    assert sim.social.p_cooperate(person(sim), Tie(0.3, 0.95), 0) > base
    assert sim.social.p_cooperate(person(sim), Tie(0.9, 0.6), 0) > base
    assert sim.social.p_cooperate(person(sim), tie, 10) > base            # embeddedness
    stressed = person(sim)
    stressed.stress = 3.0
    assert sim.social.p_cooperate(stressed, tie, 0) < base


def test_bounded_confidence_assimilates_close_views_and_repels_distant_ones(sim):
    a = person(sim)
    a.ideology = 0.0
    assert 0.0 < sim.social._shift(a, d=0.2, trust=0.9) < 0.2                  # moves towards
    assert sim.social._shift(a, d=0.9, trust=0.2) < 0.0                         # backfire: moves away
    assert sim.social._shift(a, d=0.9, trust=0.9) == 0.0                         # trusted but too far: ignored


def test_conspiracy_susceptibility(sim):
    trusting, cynical = person(sim), person(sim)
    trusting.inst_trust, cynical.inst_trust = 0.8, 0.2
    assert sim.social.susceptibility(cynical) > sim.social.susceptibility(trusting)
    assert sim.social.susceptibility(person(sim, intelligence=2)) < sim.social.susceptibility(person(sim))


def test_becker_crime_model(sim):
    j = sim.justice
    base = j.crime_utility(person(sim), 35.0, peers=0.0)
    poor = person(sim)
    poor.strain = 1.0
    assert j.crime_utility(poor, 35.0, peers=0.0) > base                        # need
    assert j.crime_utility(person(sim, honesty=2), 35.0, peers=0.0) < base      # moral cost
    assert j.crime_utility(person(sim), 20.0, peers=0.0) > base                 # age-crime curve
    assert j.crime_utility(person(sim), 35.0, peers=0.5) > base                 # delinquent peers
    old = j.p_arrest
    j.p_arrest = old + 0.3
    assert j.crime_utility(person(sim), 35.0, peers=0.0) < base                 # deterrence
    j.p_arrest = old
    legit = person(sim)
    legit.inst_trust = 0.9
    assert j.crime_utility(legit, 35.0, peers=0.0) < base                       # legitimacy


def test_gompertz_mortality_doubles_every_seven_to_eight_years(sim):
    d = sim.demography
    p = person(sim)
    ratio = []
    for age in (50, 60, 70):
        p.health = reference_health(age)
        h1 = d.hazard(p, age)
        p.health = reference_health(age + 7.5)
        h2 = d.hazard(p, age + 7.5)
        ratio.append(h2 / h1)
    assert all(1.7 < r < 2.2 for r in ratio)


def test_poor_health_raises_mortality(sim):
    p = person(sim)
    p.health = reference_health(60)
    healthy = sim.demography.hazard(p, 60)
    p.health -= 0.2
    assert sim.demography.hazard(p, 60) > 1.5 * healthy


def test_mincer_wage_equation(sim):
    econ, occ = sim.economy, OCC["Office Worker"]
    p = person(sim)
    p.wage_luck = 0.0
    w12 = econ.wage_level(p, occ)
    p.education = 16
    assert econ.wage_level(p, occ) / w12 == pytest.approx(math.exp(4 * econ.P.return_to_schooling))
    peak = econ.P.exp_linear / (2 * econ.P.exp_quadratic)                      # returns to experience peak
    wages = []
    for x in (0, peak / 2, peak, peak * 1.5):
        p.experience = x
        wages.append(econ.wage_level(p, occ))
    assert wages[0] < wages[1] < wages[2] > wages[3]


def test_progressive_income_tax(sim):
    tax = sim.economy.income_tax
    assert tax(500) == 0.0
    assert tax(4000) / 4000 < tax(20000) / 20000                                 # average rate rises with income
