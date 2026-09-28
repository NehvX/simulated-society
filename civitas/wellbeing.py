"""Body and mind: physical health, stress, trauma, mental-health crises and
life satisfaction.

Stress, as allostatic load (McEwen 1998), is a leaky bucket:
    S(t+1) = S + inflow - recovery * S
    inflow   = 0.30 strain + 0.25 unemployed + 0.06 conflicts + 0.35 prison + 0.15 crisis
    recovery = r0 * (1 + 0.3 support + 0.25 C) * exp(-0.25 N) * (2 if in treatment)
so the long-run stress level is S* = inflow / recovery.

Mental-health crises follow a stress-diathesis model (vulnerability x stress):
    P(crisis) = sigma(c0 + 1.0 S + 0.6 N + 1.5 trauma - 0.35 support)
Whether someone gets treatment depends on the public mental-health budget.

Life satisfaction L (0-10 ladder) is an Ornstein-Uhlenbeck process pulled
towards a set point L*. Event shocks (job loss, bereavement, a birth) move L
directly and then fade, which is hedonic adaptation (Brickman 1978; Lucas 2007):
    L(t+1) = L + theta * (L* - L) + noise
    L* = L0 + 0.45 ln(income / neighbours' income)    relative income (Luttmer 2005)
            + 0.6 (support - 1.5) + 0.35 partnered - 0.7 unemployed
            - 0.35 N + 0.15 X + 1.5 (health - normal health for age)
            - 1.2 strain - 1.2 prison - 0.8 trauma - 1.0 crisis + ...
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

from .mathutil import clamp, sigmoid
from .network import social_support
from .person import WORK

if TYPE_CHECKING:
    from .simulation import Simulation


def reference_health(age: float) -> float:
    """Typical health for someone of this age (1 = perfect)."""
    return clamp(1.0 - 0.009 * max(0.0, age - 30.0), 0.25, 1.0)


class Wellbeing:
    def __init__(self, sim: "Simulation"):
        self.sim = sim
        self.P = sim.cfg.wellbeing

    def treatment_access(self) -> float:
        """Probability a person in crisis gets care: diminishing returns in the budget."""
        gov = self.sim.gov
        return (1.0 - math.exp(-gov.policy.mental_health_pc / self.P.treatment_scale)) * gov.efficiency

    def step(self) -> None:
        sim, W, rng, month = self.sim, self.P, self.sim.rng, self.sim.month
        access = self.treatment_access()
        normal_decay = 0.5 ** (1.0 / W.trauma_half_life)
        treated_decay = 0.5 ** (1.0 / 12.0)
        district_income = sim.pools.district_income

        for p in sim.alive:
            age = p.age(month)
            h_ref = reference_health(age)
            p.health = clamp(p.health + 0.05 * (h_ref - p.health) - 0.006 * p.stress
                             - 0.004 * p.strain + rng.gauss(0.0, 0.01), 0.02, 1.0)
            if age < 12.0:
                p.stress = 0.9 * p.stress + 0.1 * p.strain      # growing up in a strained home
                p.social_month = 0.0
                p.conflicts_month = 0
                continue

            support = social_support(p)
            unemployed = p.stage == WORK and not p.employed and p.free
            in_crisis = p.crisis_months > 0

            # --- stress (allostatic load)
            inflow = (0.30 * p.strain + 0.25 * unemployed + 0.06 * min(p.conflicts_month, 5)
                      + 0.35 * p.incarcerated + 0.15 * in_crisis)
            recovery = W.stress_recovery * (1.0 + 0.3 * support + 0.25 * p.conscientiousness) \
                * math.exp(-0.25 * p.neuroticism) * (2.0 if p.treated else 1.0)
            p.stress = max(0.0, p.stress + inflow - min(0.9, recovery) * p.stress)

            # --- trauma fades, faster with treatment
            p.trauma *= treated_decay if p.treated else normal_decay

            # --- mental-health crises
            if in_crisis:
                p.crisis_months += 1
                if rng.random() < W.crisis_recovery * (1.0 + 1.5 * p.treated) * (1.0 + 0.15 * support):
                    p.crisis_months = 0
                    p.treated = False
                    p.stress *= 0.6
                    p.log(month, "Recovered from a mental-health crisis")
            else:
                u = W.crisis_intercept + 1.0 * p.stress + 0.6 * p.neuroticism + 1.5 * p.trauma - 0.35 * support
                if rng.random() < sigmoid(u):
                    p.crisis_months = 1
                    p.treated = rng.random() < access
                    p.life_sat -= 1.5
                    sim.counters["crises"] += 1
                    sim.counters["crises_treated"] += p.treated
                    p.log(month, "Mental-health crisis (" + ("received treatment)" if p.treated
                                                              else "no treatment available)"))

            # --- life satisfaction
            income = p.income if age >= 18 else self._family_income(p)
            reference = max(300.0, district_income[p.district])
            target = (W.life_sat_base
                      + 0.45 * math.log(max(income, 300.0) / reference)
                      + 0.60 * (support - 1.5)
                      + 0.35 * (p.partner_id is not None)
                      - 0.70 * unemployed
                      - 0.35 * p.neuroticism + 0.15 * p.extraversion
                      + 1.50 * (p.health - h_ref) - 0.5 * (1.0 - h_ref)
                      - 1.20 * p.strain - 1.20 * p.incarcerated
                      - 0.80 * p.trauma - 1.00 * (p.crisis_months > 0)
                      + 0.30 * math.tanh(p.social_month / 5.0)
                      + 0.30 * (p.inst_trust - 0.5))
            noise = W.life_sat_noise * (1.0 + 0.3 * max(0.0, p.neuroticism))
            p.life_sat = clamp(p.life_sat + W.adaptation_rate * (target - p.life_sat)
                               + rng.gauss(0.0, noise), 0.0, 10.0)
            p.social_month = 0.0
            p.conflicts_month = 0

    def _family_income(self, p) -> float:
        people = self.sim.people
        incomes = [people[i].income for i in (p.mother_id, p.father_id) if i is not None and people[i].alive]
        return max(incomes) if incomes else 0.0
