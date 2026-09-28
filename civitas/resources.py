"""The commons: a shared renewable resource and the rules for using it.

Think of the town's farmland, fishery, forest or aquifer. It regrows
logistically (Verhulst; Schaefer 1954) and is harvested by working-age
residents:

    R(t+1) = R + r R (1 - R/K) - H

What each person *tries* to take depends on who they are and their situation:

    effort_i = e0 * exp(-0.35 H_i - 0.25 A_i + 0.5 strain_i) * (1.4 if unemployed else 0.7)
               * (1 + 0.8 * scarcity * max(0, -H_i))        (scarcity panic in the less honest)

and what that effort yields falls as the stock thins (catch per unit effort is
proportional to the stock). This is Hardin's (1968) tragedy of the commons:
each person gains from taking more, while the cost of depletion is shared by
everyone.

Allocation rules (Policy.commons_rule), after Ostrom (1990):

    open_access        no limits; you keep what you take
    regulated          a sustainable quota per harvester; you keep what you take
    equal_shares       quota; the whole harvest is pooled and split equally among adults
    need_based         quota; the pool goes first to those below the cost of essentials
    private_ownership  owners (in proportion to wealth) take 60% of the value, harvesters
                       are paid 40% by effort; owners monitor closely, so compliance is high

A quota is only as good as compliance. A harvester whose effort exceeds the
quota obeys with probability

    sigma(c0 + 1.5 H + 2 (trust - 1/2) + 3 p_arrest - 0.8 strain  [+ 2 if privately owned])

so honest, trusting populations with credible enforcement manage the commons
well, and selfish ones overshoot it. A depleted commons makes essentials more
expensive (up to +60%) and drags down productivity growth: this is the main
route by which a society in the model can collapse.
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

from .mathutil import clamp, sigmoid
from .person import WORK, Person

if TYPE_CHECKING:
    from .simulation import Simulation

RULES = ("open_access", "regulated", "equal_shares", "need_based", "private_ownership")
RULE_LABELS = {
    "open_access": "Open access (keep what you take)",
    "regulated": "Regulated (quota, keep what you take)",
    "equal_shares": "Equal shares (quota, pooled, split equally)",
    "need_based": "Need-based (quota, pooled, poorest first)",
    "private_ownership": "Private ownership (owners take 60%)",
}


class Commons:
    def __init__(self, sim: "Simulation"):
        self.sim = sim
        self.P = sim.cfg.commons
        self.capacity = self.P.capacity_per_capita * sim.cfg.initial_population
        self.stock = self.P.initial_stock * self.capacity
        self.last_harvest = 0.0
        self.reset_year()

    def reset_year(self) -> None:
        self.year_units = 0.0
        self.year_value = 0.0
        self.year_scarcity = 0.0
        self.year_months = 0
        self.year_harvester_months = 0
        self.year_cheats = 0
        self.year_min_level = 1.0

    # ------------------------------------------------------------ indicators
    @property
    def level(self) -> float:
        """Stock as a share of carrying capacity (1 = pristine, 0 = exhausted)."""
        return self.stock / self.capacity if self.capacity > 0 else 0.0

    @property
    def scarcity(self) -> float:
        """0 while the stock is at least half of capacity, rising to 1 at exhaustion."""
        return clamp((0.5 - self.level) / 0.5, 0.0, 1.0)

    @property
    def cost_multiplier(self) -> float:
        """Price of essentials relative to normal: food and energy get dear as the commons runs out."""
        return 1.0 + self.P.scarcity_cost * clamp((0.6 - self.level) / 0.6, 0.0, 1.0)

    def regrowth(self) -> float:
        return self.P.regen_rate * self.stock * (1.0 - self.stock / self.capacity)

    # ------------------------------------------------------------------ month
    def step(self) -> None:
        sim, P, rng, month = self.sim, self.P, self.sim.rng, self.sim.month
        rule = sim.gov.policy.commons_rule
        for p in sim.alive:
            p.commons_income = 0.0
        harvesters = [p for p in sim.alive if p.stage == WORK and p.free and 18.0 <= p.age(month) <= 70.0]
        growth = self.regrowth()
        catchability = clamp(self.level / P.initial_stock, 0.0, 1.0)     # catch per unit effort ~ stock
        scarcity = self.scarcity

        quota = None
        if rule != "open_access" and harvesters:
            # Sustainable target: this month's regrowth, nudged to steer the stock to its target level.
            target = max(0.0, growth + 0.05 * (self.stock - P.target_stock * self.capacity))
            quota = target / len(harvesters) / max(catchability, 0.05)     # in effort units

        p_arrest = sim.justice.p_arrest
        efforts: list[float] = []
        for p in harvesters:
            effort = P.base_effort * math.exp(-0.35 * p.honesty - 0.25 * p.agreeableness + 0.5 * p.strain)
            effort *= 0.7 if p.employed else 1.4
            effort *= 1.0 + 0.8 * scarcity * max(0.0, -p.honesty)
            if quota is not None and effort > quota:
                u = (P.compliance_intercept + 1.5 * p.honesty + 2.0 * (p.inst_trust - 0.5)
                     + 3.0 * p_arrest - 0.8 * p.strain + (2.0 if rule == "private_ownership" else 0.0))
                if rng.random() < sigmoid(u):
                    effort = quota
                else:
                    self.year_cheats += 1
                    if rng.random() < 0.5 * p_arrest:                      # caught poaching: a fine
                        sim.economy.transfer(p, sim.gov, min(300.0, max(0.0, p.wealth)), "fines")
            efforts.append(effort)

        units = [e * catchability for e in efforts]
        total = sum(units)
        cap = 0.5 * self.stock                                           # can't strip it in a month
        if total > cap > 0.0:
            units = [u * cap / total for u in units]
            total = cap
        self.stock = clamp(self.stock + growth - total, 0.0, self.capacity)
        self.last_harvest = total
        value = total * P.unit_value
        if value > 0.0:
            self._distribute(rule, harvesters, units, value)

        self.year_units += total
        self.year_value += value
        self.year_scarcity += scarcity
        self.year_months += 1
        self.year_harvester_months += len(harvesters)
        self.year_min_level = min(self.year_min_level, self.level)

    # ----------------------------------------------------------- allocation
    def _pay(self, p: Person, amount: float) -> None:
        if amount > 0.0:
            self.sim.economy.external(p, amount, "commons_harvest")
            p.commons_income += amount

    def _adults(self) -> list[Person]:
        month = self.sim.month
        return [p for p in self.sim.alive if p.free and month - p.birth_month >= 216]

    def _distribute(self, rule: str, harvesters: list[Person], units: list[float], value: float) -> None:
        per_unit = value / sum(units) if sum(units) > 0 else 0.0
        if rule in ("open_access", "regulated"):
            for p, u in zip(harvesters, units):
                self._pay(p, u * per_unit)
            return
        adults = self._adults()
        if not adults:
            return
        if rule == "equal_shares":
            for p in adults:
                self._pay(p, value / len(adults))
        elif rule == "need_based":
            econ = self.sim.economy
            needs = [max(0.0, econ.living_cost(p) - p.income) for p in adults]
            total_need = sum(needs)
            to_needs = min(value, total_need)
            rest = (value - to_needs) / len(adults)
            for p, need in zip(adults, needs):
                self._pay(p, (to_needs * need / total_need if total_need > 0 else 0.0) + rest)
        elif rule == "private_ownership":
            for p, u in zip(harvesters, units):                            # wages for the work
                self._pay(p, 0.4 * u * per_unit)
            owners = [p for p in adults if p.wealth > 0.0]
            total_wealth = sum(p.wealth for p in owners)
            for p in owners if total_wealth > 0 else adults:              # profits to the owners
                share = p.wealth / total_wealth if total_wealth > 0 else 1.0 / len(adults)
                self._pay(p, 0.6 * value * share)
        else:
            raise ValueError(f"unknown commons rule '{rule}' (choose from {', '.join(RULES)})")
