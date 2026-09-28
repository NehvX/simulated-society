"""The economy: schooling, jobs, wages, taxes, welfare, spending and investment.

Stock-flow consistency
----------------------
All money lives in `.wealth` (people) or the treasury (`gov.wealth`, negative
means public debt). Every change of money goes through one of two functions:

    transfer(src, dst, amount, kind)  zero-sum between two agents (tax, theft, inheritance, ...)
    external(agent, amount, kind)     flow across the boundary of the society
                                      (private wages, consumption, investment returns, ...)

The ledger therefore satisfies, at every moment,

    sum(wealth of everyone) + treasury = initial money + sum(external flows)

which tests/test_invariants.py checks. The original code violated this: lying,
crime and childbirth all created money from nothing.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .mathutil import clamp, sigmoid, softmax_choice
from .person import CHILD, RETIRED, SCHOOL, UNIVERSITY, WORK, Person

if TYPE_CHECKING:
    from .simulation import Simulation

POLICE = "Police Officer"


@dataclass(frozen=True)
class Occupation:
    name: str
    min_education: int
    wage_mult: float
    share: float                  # share of the labour force employed in it
    fit: dict = field(default_factory=dict)   # trait weights: who is suited to it
    public: bool = False          # wages paid by the treasury


OCCUPATIONS = (
    Occupation("Doctor", 18, 1.90, 0.03, {"intelligence": 1.0, "conscientiousness": 0.6, "agreeableness": 0.3}),
    Occupation("Lawyer", 18, 1.70, 0.02, {"intelligence": 0.8, "extraversion": 0.5, "conscientiousness": 0.3}),
    Occupation("Engineer", 16, 1.50, 0.07, {"intelligence": 1.0, "conscientiousness": 0.4, "openness": 0.2}),
    Occupation("Entrepreneur", 12, 1.40, 0.05, {"openness": 0.6, "extraversion": 0.6, "neuroticism": -0.5}),
    Occupation("Teacher", 16, 0.95, 0.06, {"agreeableness": 0.6, "extraversion": 0.4, "conscientiousness": 0.3}),
    Occupation("Nurse", 16, 1.05, 0.06, {"agreeableness": 0.8, "conscientiousness": 0.5}),
    Occupation("Artist", 12, 0.75, 0.03, {"openness": 1.2, "conscientiousness": -0.3}),
    Occupation(POLICE, 12, 1.15, 0.00, {"conscientiousness": 0.6, "honesty": 0.3, "extraversion": 0.2}, public=True),
    Occupation("Office Worker", 12, 1.00, 0.24, {"conscientiousness": 0.4}),
    Occupation("Tradesperson", 12, 1.05, 0.15, {"conscientiousness": 0.3, "openness": -0.2}),
    Occupation("Retail Worker", 10, 0.78, 0.18, {"extraversion": 0.3}),
    Occupation("Labourer", 0, 0.72, 0.11, {}),
)
OCC = {o.name: o for o in OCCUPATIONS}


class Ledger:
    def __init__(self) -> None:
        self.external: defaultdict[str, float] = defaultdict(float)
        self.transfers: defaultdict[str, float] = defaultdict(float)
        self.month: defaultdict[str, float] = defaultdict(float)   # flows this month

    @property
    def net_external(self) -> float:
        return sum(self.external.values())


class Economy:
    def __init__(self, sim: "Simulation"):
        self.sim = sim
        self.P = sim.cfg.economy
        self.ledger = Ledger()
        self.recession = False
        self.months_in_regime = 0
        self.tfp = 1.0             # trend productivity, grown yearly by development.growth_components
        self.cycle = 1.0           # business-cycle factor
        self.productivity = 1.0    # = tfp * cycle, multiplies every wage
        self.avg_wage = self.P.base_wage
        self.unemployment = 0.0
        self.labour_income_history: list[float] = []   # last 12 months of labour income
        self.n_firms = self.P.n_firms or max(5, sim.cfg.initial_population // 25)

    # ============================================================ money plumbing
    def transfer(self, src, dst, amount: float, kind: str) -> float:
        if amount <= 0.0:
            return 0.0
        src.wealth -= amount
        dst.wealth += amount
        self.ledger.transfers[kind] += amount
        self.ledger.month[kind] += amount
        return amount

    def external(self, agent, amount: float, kind: str) -> None:
        agent.wealth += amount
        self.ledger.external[kind] += amount
        self.ledger.month[kind] += amount

    # ==================================================================== step
    def step(self) -> None:
        self.ledger.month.clear()
        self.business_cycle()
        self.labour_market()
        self.sim.commons.step()
        self.household_budgets()
        self.public_accounts()

    def business_cycle(self) -> None:
        """Two-state regime-switching model (Hamilton 1989): expansions last ~7
        years on average and recessions ~14 months. Each regime has a minimum
        length (6 months for a recession, 18 for an expansion), after which it
        ends with a constant hazard chosen so the mean length is unchanged.
        Productivity moves smoothly towards its regime's target."""
        sim, P, rng = self.sim, self.P, self.sim.rng
        self.months_in_regime += 1
        if self.recession:
            if self.months_in_regime > 6 and rng.random() < 1.0 / (P.mean_recession_months - 6):
                self.recession, self.months_in_regime = False, 0
                sim.chronicle("economy", "The recession ends; the economy begins to recover.")
        elif self.months_in_regime > 18 and rng.random() < 1.0 / (P.mean_expansion_months - 18):
            self.recession, self.months_in_regime = True, 0
            sim.chronicle("economy", "A recession hits: layoffs rise and hiring freezes.")
        target = 1.0 - P.recession_depth if self.recession else 1.0
        self.cycle += 0.2 * (target - self.cycle)
        self.productivity = self.tfp * self.cycle

    # ========================================================= education & wages
    def parent_income_pct(self, p: Person) -> float:
        pcts = [self.sim.income_pct.get(pid) for pid in (p.mother_id, p.father_id) if pid is not None]
        pcts = [x for x in pcts if x is not None]
        return sum(pcts) / len(pcts) if pcts else 0.35

    def continue_education_prob(self, p: Person, age: int) -> float:
        """Sequential logit schooling decisions at ages 16, 18 and 22. Parental
        income (resources, expectations) and neighbourhood school quality
        (Chetty et al. 2014) both enter, which are two channels of low
        intergenerational mobility. The unsubsidised part of tuition is a
        barrier mainly for poorer families, who are credit-constrained
        (Lochner & Monge-Naranjo 2012), so subsidies matter most to them."""
        pct = self.parent_income_pct(p) if p.parent_pct is None else p.parent_pct
        sub = self.sim.gov.policy.education_subsidy
        school = 0.8 * (self.P.district_housing[p.district] - 1.0)    # richer district, better school
        G, C, O = p.intelligence, p.conscientiousness, p.openness
        if age == 16:
            u = 2.3 + 0.9 * G + 0.6 * C + 1.5 * (pct - 0.5) + school - 1.0 * p.strain
        elif age == 18:
            cost_barrier = 2.4 * (1.0 - sub) * (1.0 - pct)                 # 0.6 at baseline
            u = (0.15 + 1.1 * G + 0.6 * C + 0.4 * O + 2.5 * (pct - 0.5) + school
                 - cost_barrier - 0.8 * p.strain)
        else:
            u = -2.2 + 1.0 * G + 0.5 * C + 0.5 * O + 1.0 * (pct - 0.5)
        return sigmoid(u)

    def wage_level(self, p: Person, occ: Occupation) -> float:
        """Mincer (1974) earnings equation, extended with personality:
        ln w = ln(w0 * m_occ) + r_s (S - 12) + b1 X - b2 X^2 + 0.06 C + 0.05 G + 0.03 E + u_i
        """
        P = self.P
        x = p.experience
        log_w = (math.log(P.base_wage * occ.wage_mult)
                 + P.return_to_schooling * (p.education - 12)
                 + P.exp_linear * x - P.exp_quadratic * x * x
                 + 0.06 * p.conscientiousness + 0.05 * p.intelligence + 0.03 * p.extraversion
                 + p.wage_luck)
        return math.exp(log_w)

    # ============================================================ labour market
    def labour_market(self) -> None:
        """Search-and-matching flows: employed people lose jobs with hazard s_i,
        unemployed people find one with hazard f_i, and only where the occupation
        they qualify for has openings."""
        sim, P, rng = self.sim, self.P, self.sim.rng
        policy = sim.gov.policy
        workers = [p for p in sim.alive if p.stage == WORK and p.free]
        sep_mult = P.recession_separation if self.recession else 1.0
        police = []
        for p in workers:
            if not p.employed:
                continue
            if p.occupation == POLICE:
                police.append(p)
                continue
            s = P.separation_rate * sep_mult * math.exp(-0.3 * p.conscientiousness - 0.15 * p.intelligence)
            if rng.random() < s:
                self.lose_job(p, "Laid off in the recession" if self.recession else "Lost their job")
        police_target = round(policy.police_per_1000 * len(sim.alive) / 1000.0)
        if len(police) > police_target:                       # budget cuts
            for p in rng.sample(police, len(police) - police_target):
                self.lose_job(p, "Laid off in police budget cuts")
            police = [p for p in police if p.employed]

        counts = Counter(p.occupation for p in workers if p.employed)
        lf = len(workers)
        openings = {o.name: max(0, round(o.share * lf) - counts[o.name]) for o in OCCUPATIONS}
        openings[POLICE] = max(0, police_target - len(police))

        find_mult = P.recession_finding if self.recession else 1.0
        seekers = [p for p in workers if not p.employed]
        rng.shuffle(seekers)
        for p in seekers:
            f = P.job_finding_rate * find_mult * math.exp(
                0.25 * p.conscientiousness + 0.15 * p.intelligence + 0.05 * (p.education - 12)
                + P.weak_tie_bonus * math.log1p(self.useful_contacts(p))
                - P.record_penalty * (self.sim.month - p.last_conviction < 84))   # records lapse after 7 years
            if p.crisis_months:
                f *= 0.2
            if rng.random() < min(0.9, f):
                occ = self.choose_occupation(p, openings)
                if occ is not None:
                    self.hire(p, occ)
                    openings[occ.name] -= 1
        employed = sum(1 for p in workers if p.employed)
        self.unemployment = 1.0 - employed / lf if lf else 0.0

    def useful_contacts(self, p: Person) -> float:
        """Employed contacts who could pass on a job lead. Weak ties count double,
        since they know about jobs you don't already know about (Granovetter 1973)."""
        people = self.sim.people
        total = 0.0
        for oid, tie in p.ties.items():
            if people[oid].employed:
                total += 1.0 if tie.strength < 0.4 else 0.5
        return total

    def choose_occupation(self, p: Person, openings: dict) -> Occupation | None:
        """Multinomial logit over the vacancies the person qualifies for:
        U_k = trait fit + 1.5 ln(pay multiplier) + preference for using one's degree."""
        age = p.age(self.sim.month)
        options, utils = [], []
        for occ in OCCUPATIONS:
            if openings.get(occ.name, 0) <= 0 or p.education < occ.min_education:
                continue
            if occ.name == POLICE and (p.record > 0 or not 21 <= age <= 55):
                continue
            fit = sum(w * getattr(p, trait) for trait, w in occ.fit.items())
            options.append(occ)
            utils.append(fit + 1.5 * math.log(occ.wage_mult) + 0.3 * (occ.min_education - 12) / 4.0)
        return softmax_choice(self.sim.rng, options, utils) if options else None

    def hire(self, p: Person, occ: Occupation, quiet: bool = False) -> None:
        changed = p.occupation != occ.name
        p.employed = True
        p.occupation = occ.name
        p.firm = 0 if occ.public else self.sim.rng.randrange(1, self.n_firms)
        p.months_unemployed = 0
        p.wage_level = self.wage_level(p, occ)
        if not quiet:
            p.log(self.sim.month, f"Hired as {occ.name}" if changed else f"Back at work as {occ.name}")

    def lose_job(self, p: Person, reason: str, quiet: bool = False) -> None:
        p.employed = False
        p.last_wage = p.wage_level * self.productivity
        p.months_unemployed = 0
        p.firm = -1
        if not quiet:
            p.stress += 0.4
            p.life_sat -= 0.8
            p.log(self.sim.month, reason)
            self.sim.counters["job_losses"] += 1

    def refresh_wage(self, p: Person) -> None:
        if p.employed and p.occupation:
            p.wage_level = self.wage_level(p, OCC[p.occupation])

    # ======================================================== household budgets
    def income_tax(self, y: float) -> float:
        pol, P = self.sim.gov.policy, self.P
        return pol.income_tax * max(0.0, y - P.tax_allowance) + pol.top_tax * max(0.0, y - P.top_threshold)

    def living_cost(self, p: Person) -> float:
        """Essentials: half is housing, which scales with the district. A depleted
        commons makes food and energy dearer."""
        P = self.P
        cost = P.living_cost * (0.5 + 0.5 * P.district_housing[p.district]) * self.sim.commons.cost_multiplier
        return cost * (P.couple_scale if p.partner_id is not None else 1.0)

    def household_budgets(self) -> None:
        sim, P, rng = self.sim, self.P, self.sim.rng
        gov, pol, people, month = sim.gov, sim.gov.policy, sim.people, sim.month
        wages = [p.wage_level for p in sim.alive if p.employed and p.free]
        self.avg_wage = (sum(wages) / len(wages) if wages else P.base_wage) * self.productivity
        labour_income = 0.0
        dependants: list[Person] = []

        for p in sim.alive:
            if p.stage in (CHILD, SCHOOL):
                dependants.append(p)
                continue
            if p.incarcerated:
                self._debt_interest(p)
                p.income = 0.0
                continue
            gross = 0.0      # taxable income
            benefit = 0.0    # untaxed transfers
            required = self.living_cost(p)
            if p.stage == WORK:
                if p.employed:
                    pay = p.wage_level * self.productivity
                    if p.occupation == "Entrepreneur":
                        s = P.entrepreneur_volatility
                        pay *= math.exp(rng.gauss(-0.5 * s * s, s))
                    if p.crisis_months:
                        benefit += P.sick_pay * pay                 # sick leave, paid by the state
                    else:
                        if OCC[p.occupation].public:
                            self.transfer(gov, p, pay, "public_wages")
                        else:
                            self.external(p, pay, "private_wages")
                        gross += pay
                        labour_income += pay
                        p.experience += 1.0 / 12.0
                else:
                    p.months_unemployed += 1
                    if p.months_unemployed <= P.benefit_months:
                        benefit += pol.unemployment_replacement * p.last_wage
            elif p.stage == RETIRED:
                pension = pol.pension_rate * self.avg_wage
                self.transfer(gov, p, pension, "pensions")
                gross += pension
            elif p.stage == UNIVERSITY:
                subsidy = P.tuition * pol.education_subsidy
                self.external(gov, -subsidy, "education_subsidy")
                required += P.tuition - subsidy
                self._parental_support(p, required)

            if pol.ubi > 0.0:
                benefit += pol.ubi
            required += self._child_costs(p)
            benefit += self._child_benefit(p)
            capital = self._capital_return(p)
            tax = self.income_tax(gross + max(0.0, capital))
            self.transfer(gov, p, benefit, "benefits")
            self.transfer(p, gov, tax, "taxes")
            sim.counters["tax_revenue"] += tax
            net = gross + benefit + capital - tax + p.commons_income

            # Means-tested safety net: top income up to the guaranteed floor.
            if net < pol.welfare_floor and p.wealth < P.welfare_wealth_limit and p.stage != UNIVERSITY:
                net += self.transfer(gov, p, pol.welfare_floor - net, "welfare")

            # Consumption: essentials + MPC * surplus + a slice of wealth (buffer-stock
            # behaviour; Carroll 1997). Poorer households spend a larger share of any surplus.
            mpc = clamp(p.mpc + 0.25 * (0.5 - sim.income_pct.get(p.id, 0.5)), 0.3, 0.98)
            spend = required + mpc * max(0.0, net - required) + P.wealth_mpc * max(0.0, p.wealth)
            self.external(p, -spend, "consumption")
            # Unexpected bills (car repairs, medical costs); more likely in poor health.
            if rng.random() < P.expense_shock_prob * (1.0 + 2.0 * (1.0 - p.health)):
                shock = self.living_cost(p) * rng.lognormvariate(math.log(P.expense_shock_size) - 0.32, 0.8)
                self.external(p, -shock, "unexpected_expenses")
            self._debt_interest(p)
            p.income = net

            buffer = min(1.0, max(0.0, p.wealth) / (6.0 * required))
            gap = max(0.0, required - net) / required * (1.0 - buffer)
            debt = min(1.0, max(0.0, -p.wealth) / 20000.0)
            unemployed = 0.15 if p.stage == WORK and not p.employed else 0.0
            p.strain = clamp(0.6 * gap + 0.4 * debt + unemployed, 0.0, 1.0)

            if p.wealth < P.bankruptcy_threshold:
                self.external(p, -p.wealth, "debt_writeoff")
                p.stress += 1.0
                p.life_sat -= 1.0
                p.log(month, "Declared bankruptcy")
                sim.counters["bankruptcies"] += 1

        # Children share their family's financial situation; orphans are fostered by the state.
        for child in dependants:
            parents = [people[i] for i in (child.mother_id, child.father_id) if i is not None and people[i].alive]
            child.strain = max((q.strain for q in parents), default=0.3)
            if not parents:
                self.external(gov, -P.child_cost, "foster_care")
            child.income = 0.0

        self.labour_income_history.append(labour_income)
        if len(self.labour_income_history) > 12:
            self.labour_income_history.pop(0)

    def _dependent_children(self, p: Person) -> list[Person]:
        people = self.sim.people
        return [c for c in (people[i] for i in p.children) if c.alive and c.stage in (CHILD, SCHOOL)]

    def _child_costs(self, p: Person) -> float:
        """Each dependent child's cost is split between their living parents."""
        people, cost = self.sim.people, 0.0
        for c in self._dependent_children(p):
            n = sum(1 for i in (c.mother_id, c.father_id) if i is not None and people[i].alive)
            cost += self.P.child_cost / max(1, n)
        return cost

    def _child_benefit(self, p: Person) -> float:
        """Paid to the mother (or the other parent if she has died)."""
        people, total = self.sim.people, 0.0
        for c in self._dependent_children(p):
            recipient = c.mother_id if c.mother_id is not None and people[c.mother_id].alive else c.father_id
            if recipient == p.id:
                total += self.sim.gov.policy.child_benefit
        return total

    def _parental_support(self, student: Person, need: float) -> None:
        """Well-off parents pay for university; everyone else borrows (student debt)."""
        people = self.sim.people
        for pid in (student.mother_id, student.father_id):
            if pid is not None and people[pid].alive and people[pid].wealth > self.P.parent_support_wealth:
                self.transfer(people[pid], student, need, "parental_support")
                return

    def _capital_return(self, p: Person) -> float:
        """Idiosyncratic multiplicative returns make wealth a Kesten process,
        w' = a_t w + b_t, which generates a Pareto (power-law) upper tail."""
        w = p.wealth
        if w <= 0.0:
            return 0.0
        P, rng = self.P, self.sim.rng
        # The rich hold more risky, higher-yielding assets (Fagereng et al. 2020);
        # entrepreneurs hold their own business, which is riskier still.
        risky = min(0.95, 1.4 * p.risk_tolerance * w / (w + P.risky_scale))
        mu, sigma = P.equity_return, P.equity_volatility
        if p.employed and p.occupation == "Entrepreneur":
            risky, mu, sigma = 0.95, mu + 0.03, sigma * 2.0
        equity = (mu + (P.recession_return if self.recession else 0.0)) / 12.0 \
            + sigma / math.sqrt(12.0) * rng.gauss(0.0, 1.0)
        r = risky * equity + (1.0 - risky) * P.safe_return / 12.0
        gain = w * r
        self.external(p, gain, "capital_income")
        return gain

    def _debt_interest(self, p: Person) -> None:
        if p.wealth < 0.0:
            self.external(p, p.wealth * self.P.debt_rate / 12.0, "debt_interest")

    # ============================================================ public sector
    def public_accounts(self) -> None:
        sim, gov, P = self.sim, self.sim.gov, self.P
        self.external(gov, -gov.policy.public_services_pc * len(sim.alive), "public_services")
        self.external(gov, -gov.policy.mental_health_pc * len(sim.alive), "mental_health_services")
        self.external(gov, -P.prison_cost * len(sim.pools.prison), "prisons")
        if gov.wealth < 0.0:
            self.external(gov, gov.wealth * P.gov_debt_rate / 12.0, "public_debt_interest")

    @property
    def annual_labour_income(self) -> float:
        h = self.labour_income_history
        return sum(h) * 12.0 / len(h) if h else 0.0
