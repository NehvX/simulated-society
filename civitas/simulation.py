"""The simulation engine: owns the world state and advances it month by month.

Order of events in one month (Delta t = 1 month):
    1. demography   birthdays, school/retirement transitions, deaths, couples, births
    2. refresh      rebuild meeting pools, income ranks, police strength
    3. economy      business cycle, labour market, the commons, incomes, taxes, spending
    4. social       everyday interactions (cooperation, trust, gossip, opinions, rumours)
    5. justice      property crime, arrests, bribery, releases
    6. wellbeing    health, stress, crises, life satisfaction
    7. politics     institutional trust, corruption, elections, fiscal rule
    8. statistics   yearly snapshot, development index and productivity growth
"""
from __future__ import annotations

import random
import statistics
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable

from . import development, metrics
from .config import SimConfig
from .crime import Justice
from .demography import Demography
from .economy import POLICE, Economy
from .mathutil import clamp, mean, sigmoid
from .names import FEMALE_NAMES, MALE_NAMES
from .person import CHILD, RETIRED, SCHOOL, UNIVERSITY, WORK, Person
from .politics import Government, Politics
from .resources import Commons
from .social import SocialLife
from .wellbeing import Wellbeing


@dataclass
class Pools:
    """Who can meet whom this month (rebuilt monthly for speed)."""
    district: list[list[Person]] = field(default_factory=list)
    school: dict = field(default_factory=dict)
    university: list[Person] = field(default_factory=list)
    firms: dict = field(default_factory=dict)
    prison: list[Person] = field(default_factory=list)
    police: list[Person] = field(default_factory=list)
    district_income: list[float] = field(default_factory=list)


class Simulation:
    def __init__(self, config: SimConfig | None = None):
        self.cfg = config or SimConfig()
        self.rng = random.Random(self.cfg.seed)
        self.month = 0
        self.people: list[Person] = []
        self.alive: list[Person] = []
        self.pools = Pools()
        self.income_pct: dict[int, float] = {}
        self.gov = Government(policy=self.cfg.policy.__class__(**vars(self.cfg.policy)))

        self.economy = Economy(self)
        self.commons = Commons(self)
        self.social = SocialLife(self)
        self.justice = Justice(self)
        self.wellbeing = Wellbeing(self)
        self.demography = Demography(self)
        self.politics = Politics(self)

        self.history: list[dict] = []
        self.chronicle_log: list[tuple[int, str, str]] = []
        self.counters: Counter = Counter()
        self.monthly = Counter()          # accumulators within the current year
        n_bands = 19
        self.exposure = [0.0] * n_bands
        self.deaths_by_band = [0] * n_bands
        self.female_exposure = [0.0] * 7
        self.births_by_band = [0] * 7
        self._window: list[dict] = []     # last 10 years of life-table inputs

        self.demography.populate()
        self.initial_money = sum(p.wealth for p in self.people) + self.gov.wealth   # for the ledger check
        self.refresh()
        self.initial_snapshot = self.snapshot_distributions()
        for _ in range(self.cfg.burn_in_months):
            self.social.step(burn_in=True)
        self.counters.clear()
        self.politics.election("founding")

    # ============================================================ bookkeeping
    def new_person(self, sex: str, birth_month: int, surname: str, genes: list[float], traits: list[float],
                   district: int, mother_id: int | None = None, father_id: int | None = None) -> Person:
        rng = self.rng
        rng.choice(FEMALE_NAMES if sex == "F" else MALE_NAMES)   # kept so random streams (and seeds) are unchanged
        pid = len(self.people)
        p = Person(pid, sex, birth_month, f"#{pid}", "", genes, traits, district, mother_id, father_id)
        # dispositions derived from traits
        p.mpc = clamp(self.cfg.economy.mpc_base - 0.12 * p.conscientiousness + rng.gauss(0.0, 0.05), 0.35, 0.95)
        p.risk_tolerance = clamp(0.5 + 0.15 * p.openness - 0.15 * p.neuroticism + rng.gauss(0.0, 0.1), 0.05, 0.95)
        p.wage_luck = rng.gauss(0.0, self.cfg.economy.wage_luck_sd)
        gt = sigmoid(0.4 + 0.5 * p.agreeableness)
        p.gt_alpha, p.gt_beta = 10.0 * gt, 10.0 * (1.0 - gt)
        p.reputation = clamp(0.5 + rng.gauss(0.0, 0.05), 0.0, 1.0)
        p.ideal_children = rng.choices(range(5), self.cfg.demography.ideal_children_weights)[0]
        p.same_sex_pref = rng.random() < self.cfg.demography.same_sex_share
        p.life_sat = clamp(7.0 + rng.gauss(0.0, 1.0), 0.0, 10.0)
        self.people.append(p)
        self.alive.append(p)
        return p

    def district_name(self, i: int) -> str:
        return self.cfg.district_names[i]

    def chronicle(self, category: str, text: str) -> None:
        self.chronicle_log.append((self.month, category, text))
        if self.cfg.verbose and category == "politics":
            print(f"  [{self.date(self.month)}] {text}")

    @staticmethod
    def date(month: int) -> str:
        return f"Year {month // 12 + 1:>2}, month {month % 12 + 1:>2}"

    def refresh(self) -> None:
        """Rebuild the meeting pools and income ranks used during the month."""
        n = len(self.cfg.economy.district_housing)
        pools = Pools(district=[[] for _ in range(n)])
        month = self.month
        earners: list[Person] = []
        for p in self.alive:
            if p.incarcerated:
                pools.prison.append(p)
                continue
            age_months = month - p.birth_month
            if p.stage in (CHILD, SCHOOL):
                if age_months >= 72:
                    pools.school.setdefault((p.district, age_months // 36), []).append(p)
                continue
            if age_months >= 192:
                pools.district[p.district].append(p)
            if p.stage == UNIVERSITY:
                pools.university.append(p)
            if p.employed:
                pools.firms.setdefault(p.firm, []).append(p)
                if p.occupation == POLICE:
                    pools.police.append(p)
            if p.stage in (WORK, RETIRED):
                earners.append(p)
        earners.sort(key=lambda q: q.income)
        k = len(earners)
        self.income_pct = {q.id: (r + 0.5) / k for r, q in enumerate(earners)}
        for d in range(n):
            incomes = [q.income for q in pools.district[d] if q.stage in (WORK, RETIRED)]
            pools.district_income.append(mean(incomes, 2500.0))
        self.pools = pools
        self.justice.update_detection()

    # ================================================================== run
    def step(self) -> None:
        self.demography.step()
        self.refresh()
        self.economy.step()
        self.social.step()
        self.justice.step()
        self.wellbeing.step()
        self.politics.step()
        self.monthly["unemployment"] += self.economy.unemployment
        self.monthly["recession"] += self.economy.recession
        if self.month % 12 == 11:
            self.record_year()
        self.month += 1

    def run(self, years: int | None = None, progress: Callable[["Simulation"], None] | None = None) -> "Simulation":
        for _ in range(12 * (years if years is not None else self.cfg.years)):
            self.step()
            if progress is not None and self.month % 12 == 0:
                progress(self)
            if not self.alive:
                break
        return self

    # ============================================================ statistics
    def adults(self) -> list[Person]:
        return [p for p in self.alive if self.month - p.birth_month >= 216]

    def snapshot_distributions(self) -> dict:
        adults = self.adults()
        return {
            "wealth": [p.wealth for p in adults],
            "income": [p.income for p in adults if p.stage in (WORK, RETIRED)],
            "ideology": [p.ideology for p in adults],
            "ages": [(int(p.age(self.month)), p.sex) for p in self.alive],
        }

    def record_year(self) -> None:
        month, counters = self.month, self.counters
        year = month // 12 + 1
        alive, adults = self.alive, self.adults()
        n = max(1, len(alive))
        free_adults = [p for p in adults if p.free]
        incomes = [p.income for p in adults if p.stage in (WORK, RETIRED) and p.free]
        wealth = [p.wealth for p in adults]

        self._window.append({"deaths": list(self.deaths_by_band), "exposure": list(self.exposure),
                             "births": list(self.births_by_band), "fexp": list(self.female_exposure)})
        self._window = self._window[-10:]
        deaths = [sum(w["deaths"][i] for w in self._window) for i in range(19)]
        exposure = [sum(w["exposure"][i] for w in self._window) for i in range(19)]
        births = [sum(w["births"][i] for w in self._window) for i in range(7)]
        fexp = [sum(w["fexp"][i] for w in self._window) for i in range(7)]

        ideology = [p.ideology for p in free_adults]
        pairs = [(p.ideology, self.people[j].ideology, t.strength)
                 for p in free_adults for j, t in p.ties.items() if t.strength >= 0.15]
        poor_cut = sorted(incomes)[int(0.4 * len(incomes))] if incomes else 0
        rich_cut = sorted(incomes)[int(0.8 * len(incomes))] if incomes else 0
        earners = [p for p in adults if p.stage in (WORK, RETIRED) and p.free]
        interactions = max(1, counters["interactions"])
        mayor = self.politics.mayor
        record = {
            "year": year,
            "population": len(alive),
            "births": counters["births"],
            "deaths": counters["deaths"],
            "partnerships": counters["partnerships"],
            "divorces": counters["divorces"],
            "median_age": statistics.median(p.age(month) for p in alive) if alive else 0,
            "life_expectancy": metrics.life_expectancy(deaths, exposure),
            "tfr": metrics.total_fertility_rate(births, fexp),
            "unemployment": self.monthly["unemployment"] / 12.0,
            "recession_months": int(self.monthly["recession"]),
            "mean_income": mean(incomes),
            "median_income": statistics.median(incomes) if incomes else 0.0,
            "median_wealth": statistics.median(wealth) if wealth else 0.0,
            "gini_income": metrics.gini(incomes),
            "gini_wealth": metrics.gini(wealth),
            "top10_wealth": metrics.top_share(wealth, 0.10),
            "poverty_rate": metrics.poverty_rate(incomes),
            "gov_debt_ratio": -self.gov.wealth / max(1.0, self.economy.annual_labour_income),
            "income_tax": self.gov.policy.income_tax,
            "welfare_floor": self.gov.policy.welfare_floor,
            "police_per_1000": 1000.0 * len(self.pools.police) / n,
            "property_crime_rate": 1000.0 * counters["property_crimes"] / n,
            "assault_rate": 1000.0 * counters["assaults"] / n,
            "fraud_rate": 1000.0 * counters["frauds"] / n,
            "arrests": counters["arrests"],
            "bribes": counters["bribes"],
            "incarceration_rate": 100_000.0 * len(self.pools.prison) / n,
            "cooperation_rate": counters["cooperations"] / (2.0 * interactions),
            "generalized_trust": mean([p.generalized_trust for p in adults]),
            "institutional_trust": mean([p.inst_trust for p in adults]),
            "reputation_mean": mean([p.reputation for p in adults]),
            "avg_ties": mean([sum(1 for t in p.ties.values() if t.strength >= 0.15) for p in adults]),
            "clustering": metrics.clustering_coefficient(alive, self.rng, sample=100),
            "ideology_mean": mean(ideology),
            "polarization": float(statistics.pstdev(ideology)) if len(ideology) > 1 else 0.0,
            "bimodality": metrics.bimodality_coefficient(ideology),
            "echo_chamber": metrics.weighted_assortativity(pairs),
            "conspiracy_share": mean([1.0 if p.conspiracy > 0.5 else 0.0 for p in adults]),
            "life_satisfaction": mean([p.life_sat for p in adults]),
            "stress": mean([p.stress for p in adults]),
            "crises": counters["crises"],
            "treated_share": counters["crises_treated"] / counters["crises"] if counters["crises"] else None,
            "segregation": metrics.dissimilarity_index(
                [p.district for p in earners if p.income <= poor_cut],
                [p.district for p in earners if p.income >= rich_cut],
                len(self.cfg.economy.district_housing)),
            "commons_level": self.commons.level,
            "commons_min_level": self.commons.year_min_level,
            "commons_harvest_pc": self.commons.year_units / n,
            "commons_income_pc": self.commons.year_value / 12.0 / max(1, len(adults)),
            "quota_cheat_rate": self.commons.year_cheats / max(1, self.commons.year_harvester_months),
            "cost_of_living": self.commons.cost_multiplier,
            "mayor": mayor.name if mayor else None,
            "mayor_ideology": mayor.ideology if mayor else None,
            "embezzled": counters["embezzled"],
        }
        record.update(development.development_index(self, record))
        development.apply_growth(self, record)
        self.commons.reset_year()
        self.history.append(record)
        for p in alive:
            p.trajectory.append((year, round(p.age(month), 1), p.job_title, round(p.wealth),
                                 round(p.life_sat, 2), round(p.stress, 2), round(p.income)))
            # parents' income rank, averaged over the child's ages 10-15 (as in Chetty et al. 2014)
            if 10.0 <= p.age(month) < 16.0 and p.mother_id is not None:
                pct = self.economy.parent_income_pct(p)
                p.parent_pct_n += 1
                p.parent_pct = pct if p.parent_pct is None else p.parent_pct + (pct - p.parent_pct) / p.parent_pct_n

        if self.cfg.verbose:
            le = record["life_expectancy"]
            print(f"Year {year:>3} | pop {record['population']:>4} | unemp {record['unemployment']:5.1%} "
                  f"| Gini(w) {record['gini_wealth']:.2f} | crime/1k {record['property_crime_rate']:5.1f} "
                  f"| trust {record['institutional_trust']:.2f} | polar {record['polarization']:.2f} "
                  f"| LS {record['life_satisfaction']:.2f} | e0 {le if le is None else round(le, 1)} "
                  f"| CDI {record['cdi']:.3f} | resource {record['commons_level']:4.0%}"
                  f"{' | RECESSION' if record['recession_months'] >= 6 else ''}")

        self.counters = Counter()
        self.monthly = Counter()
        self.exposure = [0.0] * 19
        self.deaths_by_band = [0] * 19
        self.female_exposure = [0.0] * 7
        self.births_by_band = [0] * 7

    # ============================================================== analysis
    def mobility(self) -> dict:
        """Intergenerational rank-rank slope (Chetty et al. 2014) for adults aged
        25-60 whose parents' income rank is known. To cut transitory noise the
        child's income is averaged over their last five years, and the parents'
        rank over the child's ages 10-15."""
        cohort = [p for p in self.alive if 25.0 <= p.age(self.month) <= 60.0
                  and p.parent_pct is not None and p.stage in (WORK, RETIRED) and p.trajectory]
        child = [mean([t[6] for t in p.trajectory[-5:]]) for p in cohort]
        slope = metrics.rank_rank_slope([p.parent_pct for p in cohort], child)
        return {"rank_rank_slope": slope, "n": len(cohort)}

    def success_regression(self) -> dict | None:
        """What predicts economic success here? Standardised OLS of income rank
        among working adults aged 30-64 on their traits and schooling."""
        from .traits import TRAIT_NAMES
        people = [p for p in self.alive if 30.0 <= p.age(self.month) < 65.0 and p.stage == WORK and p.free]
        if len(people) < 40:
            return None
        y = metrics.percentile_ranks([p.income for p in people])
        names = list(TRAIT_NAMES) + ["education"]
        cols = [[getattr(p, t) for t in TRAIT_NAMES] + [p.education] for p in people]
        import numpy as np
        X = np.asarray(cols, dtype=float)
        X = (X - X.mean(axis=0)) / np.where(X.std(axis=0) > 0, X.std(axis=0), 1.0)
        Y = np.asarray(y)
        Y = (Y - Y.mean()) / Y.std()
        beta, r2 = metrics.ols(Y, X)
        return {"coefficients": dict(zip(names, (float(b) for b in beta[1:]))), "r2": r2, "n": len(people)}

    def summary(self) -> dict:
        h = self.history
        last5 = h[-5:] if h else []
        return {
            "years": len(h),
            "final_population": len(self.alive),
            "people_ever_lived": len(self.people),
            "gini_wealth": h[-1]["gini_wealth"] if h else None,
            "gini_income": h[-1]["gini_income"] if h else None,
            "top10_wealth": h[-1]["top10_wealth"] if h else None,
            "poverty_rate": mean([r["poverty_rate"] for r in last5]),
            "unemployment": mean([r["unemployment"] for r in h]),
            "property_crime_rate": mean([r["property_crime_rate"] for r in h]),
            "assault_rate": mean([r["assault_rate"] for r in h]),
            "incarceration_rate": mean([r["incarceration_rate"] for r in h]),
            "recidivism": self.justice.recidivism_rate(),
            "life_expectancy": mean([r["life_expectancy"] for r in h if r["life_expectancy"]], float("nan")),
            "tfr": mean([r["tfr"] for r in h if r["tfr"]], float("nan")),
            "life_satisfaction": mean([r["life_satisfaction"] for r in last5]),
            "institutional_trust": mean([r["institutional_trust"] for r in last5]),
            "generalized_trust": mean([r["generalized_trust"] for r in last5]),
            "cooperation_rate": mean([r["cooperation_rate"] for r in h]),
            "polarization": h[-1]["polarization"] if h else None,
            "echo_chamber": h[-1]["echo_chamber"] if h else None,
            "conspiracy_share": mean([r["conspiracy_share"] for r in last5]),
            "segregation": h[-1]["segregation"] if h else None,
            "gov_debt_ratio": h[-1]["gov_debt_ratio"] if h else None,
            "income_tax": mean([r["income_tax"] for r in h]),
            **self._trajectory_summary(),
            "elections": len(self.gov.elections),
            "scandals": sum(1 for _, c, t in self.chronicle_log if t.startswith("SCANDAL")),
            **{f"mobility_{k}": v for k, v in self.mobility().items()},
        }

    def trajectory(self) -> dict:
        """Growth, stagnation, decline or collapse, with its drivers (see development.py)."""
        return development.classify(self.history, self.cfg.initial_population)

    def _trajectory_summary(self) -> dict:
        v = self.trajectory()
        if "cdi_start" not in v:
            return {}
        return {"trajectory": v["status"], "collapse": 1.0 if v["collapse"] else 0.0,
                "cdi_start": v["cdi_start"], "cdi_end": v["cdi_end"], "cdi_rate": v["cdi_rate"],
                "income_change": v["income_change"], "tfp_end": v["tfp_end"],
                "commons_level": v["resource_end"], "commons_min": v["resource_min"],
                "commons_income_pc": mean([r["commons_income_pc"] for r in self.history[-5:]])}

    # ============================================================= lookups
    def find(self, query: str) -> list[Person]:
        """Find people by id ('#12' or '12') or by (part of) their name."""
        q = query.strip().lstrip("#")
        if q.isdigit():
            i = int(q)
            return [self.people[i]] if 0 <= i < len(self.people) else []
        q = q.lower()
        return [p for p in self.people if q in p.name.lower()]
