"""Government, elections, corruption and institutional trust.

Elections use the probabilistic spatial voting model (Downs 1957; Lindbeck &
Weibull 1987). Voter i gives candidate c the utility

    U_ic = -w_I (o_i - o_c)^2                   ideological proximity
           + w_T (trust_ic - 1/2)               personal acquaintance, if any
           + w_R (reputation_c - 1/2)           public reputation
           + w_X X_c                            charisma
           + w_inc (2 trust_i - 1) [incumbent]  retrospective voting
           + Gumbel noise

so P(vote for c) = softmax(U). Turnout is itself a logit in age, education
and trust.

The winner's ideology sets policy: left mayors tax and spend more, right
mayors cut taxes and hire police. A mayor low in honesty may skim public money
each month. Scandals are detected at random, and when one breaks it destroys
institutional trust, which feeds back into crime (legitimacy), conspiracy
beliefs and turnout.
"""
from __future__ import annotations

import copy
import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .config import Policy
from .mathutil import clamp, normal_cdf, poisson, sigmoid, softmax_choice
from .person import Person, WORK

if TYPE_CHECKING:
    from .simulation import Simulation


@dataclass
class ElectionResult:
    month: int
    reason: str
    candidates: list[dict]
    turnout: float
    winner_id: int
    winner_name: str
    winner_ideology: float


@dataclass
class Government:
    policy: Policy
    wealth: float = 0.0              # the treasury (negative = public debt)
    mayor_id: int | None = None
    efficiency: float = 0.9
    next_election: int = 0
    consecutive_terms: dict = field(default_factory=lambda: defaultdict(int))
    embezzled_this_term: float = 0.0
    last_scandal: int = -10_000
    tax_adjustment: float = 0.0      # fiscal-rule changes, inherited by every new mayor
    elections: list[ElectionResult] = field(default_factory=list)


def policy_from_ideology(o: float, base: Policy) -> Policy:
    """Map a mayor's position o in [-1, 1] (left to right) to concrete policy."""
    p = copy.deepcopy(base)
    p.income_tax = clamp(base.income_tax - 0.10 * o, 0.10, 0.50)
    p.top_tax = clamp(base.top_tax - 0.08 * o, 0.0, 0.30)
    p.welfare_floor = base.welfare_floor * (1.0 - 0.35 * o)
    p.child_benefit = base.child_benefit * (1.0 - 0.30 * o)
    p.police_per_1000 = base.police_per_1000 * (1.0 + 0.35 * o)
    p.education_subsidy = clamp(base.education_subsidy - 0.35 * o, 0.0, 1.0)
    p.mental_health_pc = base.mental_health_pc * (1.0 - 0.40 * o)
    p.public_services_pc = base.public_services_pc * (1.0 - 0.30 * o)
    return p


class Politics:
    def __init__(self, sim: "Simulation"):
        self.sim = sim
        self.P = sim.cfg.politics
        self._last_treasury = 0.0

    @property
    def mayor(self) -> Person | None:
        gov = self.sim.gov
        return self.sim.people[gov.mayor_id] if gov.mayor_id is not None else None

    # ================================================================= month
    def step(self) -> None:
        sim, month = self.sim, self.sim.month
        self.update_trust()
        self.mayor_conduct()
        if sim.cfg.elections and month >= sim.gov.next_election:
            self.election("scheduled" if sim.gov.mayor_id is not None else "special")
        if month % 12 == 11:
            self.fiscal_rule()
            self.class_interest_drift()
        self.seed_rumours()

    def update_trust(self) -> None:
        """Trust in institutions relaxes towards a target set by one's distance
        from the mayor's politics, personal hardship, victimisation, the economy
        and conspiracy beliefs."""
        sim, month = self.sim, self.sim.month
        mayor = self.mayor
        o_m = mayor.ideology if mayor is not None else 0.0
        recession = 0.1 if sim.economy.recession else 0.0
        rate = self.P.trust_adjust
        for p in sim.alive:
            if month - p.birth_month < 216:
                continue
            target = (0.66 - 0.30 * abs(p.ideology - o_m)
                      - 0.15 * (p.stage == WORK and not p.employed)
                      - recession - self.P.conspiracy_distrust * p.conspiracy - 0.10 * p.strain
                      - 0.15 * (month - p.last_victimized < 12)
                      + 0.5 * (sim.gov.efficiency - 0.9))
            p.inst_trust = clamp(p.inst_trust + rate * (target - p.inst_trust), 0.0, 1.0)

    def mayor_conduct(self) -> None:
        sim, T, rng = self.sim, self.P, self.sim.rng
        gov, mayor = sim.gov, self.mayor
        if mayor is None:
            gov.efficiency = 0.85
            return
        # competence: conscientious, able mayors run a tighter ship
        gov.efficiency = 0.8 + 0.12 * normal_cdf(mayor.conscientiousness) + 0.08 * normal_cdf(mayor.intelligence)
        # corruption: the temptation to skim rises steeply as honesty falls
        if rng.random() < (1.0 - normal_cdf(mayor.honesty)) ** 4:
            amount = T.max_embezzle * sim.economy.ledger.month.get("taxes", 0.0)
            sim.economy.transfer(gov, mayor, amount, "embezzlement")
            gov.embezzled_this_term += amount
            sim.counters["embezzled"] += amount
            if rng.random() < T.scandal_hazard:
                self.scandal(mayor)

    def scandal(self, mayor: Person) -> None:
        sim, gov, rng = self.sim, self.sim.gov, self.sim.rng
        stolen = gov.embezzled_this_term
        sim.chronicle("politics", f"SCANDAL: Mayor {mayor.name} is caught embezzling ${stolen:,.0f} of public money.")
        sim.economy.transfer(mayor, gov, min(stolen, max(0.0, mayor.wealth)), "recovered_funds")
        mayor.reputation = 0.05
        gov.last_scandal = sim.month
        for p in sim.alive:
            p.inst_trust = max(0.0, p.inst_trust - self.P.scandal_trust_shock)
        sim.justice.convict(mayor, 24 + rng.randrange(25), "embezzlement")   # removes the mayor

    def remove_mayor(self, reason: str) -> None:
        sim, gov = self.sim, self.sim.gov
        mayor = self.mayor
        if mayor is not None:
            sim.chronicle("politics", f"Mayor {mayor.name} leaves office ({reason}).")
        gov.mayor_id = None
        gov.embezzled_this_term = 0.0
        if sim.cfg.elections:
            gov.next_election = sim.month + 1

    # ============================================================== elections
    def ambition(self, p: Person) -> float:
        """Who runs for office: extraverted, conscientious, well-connected, well
        known, and (a dark-triad touch) somewhat lower in honesty-humility."""
        network = math.log1p(sum(t.strength for t in p.ties.values()))
        return (0.5 * p.extraversion + 0.3 * p.conscientiousness - 0.15 * p.honesty
                + 1.5 * (p.reputation - 0.5) + 0.4 * network + self.sim.rng.gauss(0.0, 0.4))

    def election(self, reason: str) -> ElectionResult | None:
        sim, T, rng, month, gov = self.sim, self.P, self.sim.rng, self.sim.month, self.sim.gov
        adults = [p for p in sim.alive if p.free and p.age(month) >= 18.0]
        eligible = [p for p in adults if T.min_candidate_age <= p.age(month) <= 78.0
                    and p.record == 0 and p.crisis_months == 0]
        if not eligible:
            gov.next_election = month + 12
            return None
        incumbent = self.mayor
        if incumbent is not None and gov.consecutive_terms[incumbent.id] >= T.term_limit:
            eligible = [p for p in eligible if p is not incumbent]          # term-limited: may not run
        if incumbent not in eligible:
            incumbent = None
        challengers = sorted((p for p in eligible if p is not incumbent), key=self.ambition, reverse=True)
        candidates = ([incumbent] if incumbent else []) + challengers[: T.candidates - (1 if incumbent else 0)]

        votes = {c.id: 0 for c in candidates}
        voters = 0
        for v in adults:
            turnout = sigmoid(-0.4 + 0.03 * (v.age(month) - 40.0) + 0.15 * (v.education - 12)
                              + 3.0 * (v.inst_trust - 0.5) + 0.3 * v.conscientiousness)
            if rng.random() >= turnout:
                continue
            voters += 1
            utils = []
            for c in candidates:
                tie = v.ties.get(c.id)
                u = (-T.ideology_weight * (v.ideology - c.ideology) ** 2
                     + T.reputation_weight * (c.reputation - 0.5)
                     + T.charisma_weight * c.extraversion)
                if tie is not None:
                    u += T.trust_weight * (tie.trust - 0.5) + tie.strength
                if c is incumbent:
                    u += T.incumbency_weight * (2.0 * v.inst_trust - 1.0)
                utils.append(u)
            votes[softmax_choice(rng, candidates, utils).id] += 1

        winner = max(candidates, key=lambda c: (votes[c.id], c.reputation))
        total = max(1, voters)
        result = ElectionResult(
            month=month, reason=reason, turnout=voters / max(1, len(adults)),
            candidates=[{"id": c.id, "name": c.name, "ideology": round(c.ideology, 3),
                         "share": votes[c.id] / total, "incumbent": c is incumbent} for c in candidates],
            winner_id=winner.id, winner_name=winner.name, winner_ideology=winner.ideology)
        gov.elections.append(result)

        if winner is incumbent:
            gov.consecutive_terms[winner.id] += 1
        else:
            gov.consecutive_terms = defaultdict(int, {winner.id: 1})
            gov.embezzled_this_term = 0.0
        gov.mayor_id = winner.id
        gov.next_election = month + T.term_months
        winner.offices += 1
        share = votes[winner.id] / total
        winner.log(month, f"Elected mayor with {share:.0%} of the vote")
        if not sim.cfg.lock_policy:
            gov.policy = policy_from_ideology(winner.ideology, sim.cfg.policy)
            gov.policy.income_tax = clamp(gov.policy.income_tax + gov.tax_adjustment, 0.05, 0.60)
        lean = "left" if winner.ideology < -0.15 else "right" if winner.ideology > 0.15 else "centrist"
        sim.chronicle("politics", f"{winner.name} ({lean}, {winner.ideology:+.2f}) wins the {reason} election "
                                  f"with {share:.0%}; turnout {result.turnout:.0%}.")
        return result

    # ================================================================ fiscal
    def fiscal_rule(self) -> None:
        """Yearly budget review. Austerity when debt is high *and* still growing;
        a tax cut when the treasury is flush *and* still running a surplus. Using
        both the stock and the flow stops the rule from firing every year."""
        sim, gov = self.sim, self.sim.gov
        balance = gov.wealth - self._last_treasury
        self._last_treasury = gov.wealth
        income = sim.economy.annual_labour_income
        if income <= 0:
            return
        pol = gov.policy
        if sim.cfg.lock_policy:
            # Experiments: politicians cannot touch policy, but the flat income tax
            # follows a fiscal reaction function (Bohn 1998) so that every regime
            # is solvent and the tax it needs becomes an outcome:
            #   tau <- tau - 0.6 * (annual balance / income) - 0.05 * (treasury / income)
            pol.income_tax = clamp(pol.income_tax - 0.6 * balance / income - 0.05 * gov.wealth / income,
                                   0.05, 0.60)
            return
        if -gov.wealth / income > self.P.fiscal_debt_limit and balance < 0:
            gov.tax_adjustment += 0.02
            pol.income_tax = min(0.5, pol.income_tax + 0.02)
            pol.welfare_floor *= 0.95
            pol.mental_health_pc *= 0.9
            pol.education_subsidy = max(0.0, pol.education_subsidy - 0.05)
            sim.chronicle("economy", f"Debt crisis: austerity budget (tax rate now {pol.income_tax:.0%}).")
        elif gov.wealth > 0.25 * income and balance > 0.02 * income and pol.income_tax > 0.10:
            gov.tax_adjustment -= 0.02
            pol.income_tax = max(0.10, pol.income_tax - 0.02)
            sim.chronicle("economy", f"Budget surplus: income tax cut to {pol.income_tax:.0%}.")

    def class_interest_drift(self) -> None:
        """Slow pull of one's political anchor towards material self-interest
        (richer -> right), yearly."""
        sim = self.sim
        for p in sim.alive:
            pct = sim.income_pct.get(p.id)
            if pct is not None:
                p.anchor = clamp(p.anchor + 0.01 * (0.6 * (2.0 * pct - 1.0) - p.anchor), -1.0, 1.0)

    # ============================================================ misinformation
    def seed_rumours(self) -> None:
        """New conspiracy theories appear more often in hard times (recessions,
        scandals); van Prooijen & Douglas (2017)."""
        sim, rng, month = self.sim, self.sim.rng, self.sim.month
        crisis = 1.0 + 1.5 * sim.economy.recession + 2.0 * (month - sim.gov.last_scandal < 12)
        n = poisson(rng, sim.cfg.social.rumour_seeds_per_year / 12.0 * crisis)
        adults = [p for p in sim.alive if month - p.birth_month >= 216 and p.free]
        for _ in range(n):
            if not adults:
                return
            pool = [rng.choice(adults) for _ in range(10)]
            seed = max(pool, key=sim.social.susceptibility)
            seed.conspiracy = max(seed.conspiracy, 0.85)
