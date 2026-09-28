"""Whole-simulation invariants: accounting identities, consistency of the
social graph and life course, and reproducibility."""
import math

import pytest

from civitas import SimConfig, Simulation
from civitas.person import CHILD, SCHOOL, WORK
from civitas.traits import TRAIT_CAP, TRAIT_NAMES


@pytest.fixture(scope="module")
def sim():
    return Simulation(SimConfig(seed=11, years=12, initial_population=220, verbose=False)).run()


def test_money_is_conserved(sim):
    """Stock-flow consistency: all money now = money at the start + net external flows.
    Every internal transfer (tax, theft, inheritance...) must net to zero."""
    ledger = sim.economy.ledger
    total_now = sum(p.wealth for p in sim.people) + sim.gov.wealth
    expected = sim.initial_money + ledger.net_external
    gross = sum(abs(v) for v in ledger.external.values()) + sum(ledger.transfers.values())
    assert abs(total_now - expected) <= 1e-9 * gross + 1e-6


def test_the_dead_hold_nothing(sim):
    for p in sim.people:
        if not p.alive:
            assert abs(p.wealth) < 1e-6
            assert not p.ties
            assert not p.employed and p.prison_release == 0
            assert p not in sim.alive


def test_partnerships_are_mutual(sim):
    for p in sim.alive:
        if p.partner_id is not None:
            q = sim.people[p.partner_id]
            assert q.alive and q.partner_id == p.id and q is not p


def test_social_graph_is_consistent(sim):
    alive_ids = {p.id for p in sim.alive}
    for p in sim.alive:
        assert p.id not in p.ties
        for oid, tie in p.ties.items():
            assert oid in alive_ids
            assert p.id in sim.people[oid].ties                                   # ties exist in both directions
            assert 0.0 <= tie.strength <= 1.0 and 0.0 < tie.trust < 1.0


def test_life_course_is_consistent(sim):
    month = sim.month
    for p in sim.alive:
        age = p.age(month)
        if p.employed:
            assert p.stage == WORK and age >= 15 and not p.incarcerated
        if p.stage in (CHILD, SCHOOL):
            assert age < 18.5
        if p.occupation == "Police Officer" and p.employed:
            assert age >= 21
        for pid in (p.mother_id,):
            if pid is not None and p.birth_month >= 0:
                assert (p.birth_month - sim.people[pid].birth_month) / 12 >= 17.9


def test_prison_bookkeeping(sim):
    inmates = {p.id for p in sim.alive if p.incarcerated}
    assert inmates == {p.id for p in sim.pools.prison}
    assert all(p.prison_release > sim.month - 1 for p in sim.pools.prison)


def test_traits_stay_finite_and_bounded(sim):
    for p in sim.people:
        for name in TRAIT_NAMES:
            z = getattr(p, name)
            assert math.isfinite(z) and abs(z) <= TRAIT_CAP
        assert 0.0 <= p.health <= 1.0 and 0.0 <= p.life_sat <= 10.0
        assert -1.0 <= p.ideology <= 1.0 and 0.0 <= p.inst_trust <= 1.0
        assert math.isfinite(p.wealth) and math.isfinite(p.stress)


def test_outcomes_are_in_a_plausible_range(sim):
    s = sim.summary()
    assert 0.01 < s["unemployment"] < 0.20
    assert 0.3 < s["gini_wealth"] < 0.9
    assert 65 < s["life_expectancy"] < 90
    assert 0.6 < s["cooperation_rate"] < 1.0
    assert s["final_population"] > 0.7 * 220


def test_runs_are_reproducible():
    def fingerprint(seed):
        sim = Simulation(SimConfig(seed=seed, years=3, initial_population=120, verbose=False)).run()
        return [(r["population"], round(r["gini_wealth"], 10), r["property_crimes"] if "property_crimes" in r
                 else round(r["property_crime_rate"], 10)) for r in sim.history]
    assert fingerprint(3) == fingerprint(3)
    assert fingerprint(3) != fingerprint(4)


def test_config_round_trip(tmp_path):
    cfg = SimConfig(seed=9)
    cfg.override("policy.income_tax", 0.33)
    cfg.override("crime.deterrence", 4)
    path = tmp_path / "cfg.json"
    cfg.save(str(path))
    loaded = SimConfig.load(str(path))
    assert loaded.policy.income_tax == 0.33 and loaded.crime.deterrence == 4.0 and loaded.seed == 9
    with pytest.raises(AttributeError):
        cfg.override("policy.no_such_thing", 1)
