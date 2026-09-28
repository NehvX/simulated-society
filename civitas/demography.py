"""Birth, the life course, partnership and death.

Mortality follows the Gompertz-Makeham law, adjusted for individual frailty:

    mu_i(x) = [A + B e^{c x}] * exp(k (h_ref(x) - h_i) - 0.08 C_i)      (per year)
    P(death this month) = 1 - exp(-mu_i / 12)

Poor health for one's age, which in this model is driven by stress and
poverty, raises the death rate. That is how the socioeconomic health gradient
(Marmot 2005) arises. Conscientiousness lowers it (health behaviours; Kern &
Friedman 2008).

Fertility for a partnered woman of age a:
    f(a) = f_peak * exp(-((a - a_peak) / s)^2) * desire * economic security
where desire falls as the couple approaches its ideal family size.
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

from .economy import OCC, OCCUPATIONS, POLICE
from .mathutil import clamp, poisson, sigmoid, softmax_choice
from .names import SURNAMES
from .network import FAMILY, FRIEND, PARTNER, is_relative, link, similarity
from .person import CHILD, RETIRED, SCHOOL, UNIVERSITY, WORK, Person
from .traits import founder_traits, inherited_traits
from .wellbeing import reference_health

if TYPE_CHECKING:
    from .simulation import Simulation


def age_band(age: float) -> int:
    """Life-table bands: 0, 1-4, 5-9, ..., 80-84, 85+ (19 bands)."""
    if age < 1.0:
        return 0
    if age < 5.0:
        return 1
    return min(18, 2 + int((age - 5.0) // 5))


class Demography:
    def __init__(self, sim: "Simulation"):
        self.sim = sim
        self.P = sim.cfg.demography

    # ================================================================= month
    def step(self) -> None:
        sim, month = self.sim, self.sim.month
        for p in list(sim.alive):
            months_old = month - p.birth_month
            if months_old > 0 and months_old % 12 == 0:
                self.birthday(p, months_old // 12)
        self.mortality()
        self.partnerships()
        self.couples()
        if month % 12 == 6:
            self.relocation()

    def hazard(self, p: Person, age: float) -> float:
        D = self.P
        mu = D.makeham_a + D.gompertz_b * math.exp(D.gompertz_c * age)
        if age < 1.0:
            mu += D.infant_mortality
        frailty = math.exp(D.frailty_health * (reference_health(age) - p.health) - 0.08 * p.conscientiousness)
        return mu * frailty

    def mortality(self) -> None:
        sim, rng, month = self.sim, self.sim.rng, self.sim.month
        for p in list(sim.alive):
            age = p.age(month)
            sim.exposure[age_band(age)] += 1.0 / 12.0
            if p.sex == "F" and 15.0 <= age < 50.0:
                sim.female_exposure[int((age - 15.0) // 5)] += 1.0 / 12.0
            if rng.random() < 1.0 - math.exp(-self.hazard(p, age) / 12.0):
                if age < 1.0:
                    cause = "complications in infancy"
                elif age < 45.0:
                    cause = rng.choice(("an accident", "an illness"))
                elif p.health < reference_health(age) - 0.15:
                    cause = "a stress-related illness"
                else:
                    cause = "natural causes"
                self.die(p, cause)

    # ============================================================ life course
    def birthday(self, p: Person, age: int) -> None:
        sim, rng, month, econ = self.sim, self.sim.rng, self.sim.month, self.sim.economy
        if age == 6 and p.stage == CHILD:
            p.stage = SCHOOL
        elif age == 16 and p.stage == SCHOOL:
            if rng.random() >= econ.continue_education_prob(p, 16):
                self.finish_education(p, 10)
        if age == 18:
            # impressionable years (Krosnick & Alwin 1989): views absorbed from one's
            # social circle while growing up become part of one's lasting anchor
            p.anchor = 0.5 * (p.anchor + p.ideology)
        if age == 18 and p.stage == SCHOOL:
            p.education = 12
            if rng.random() < econ.continue_education_prob(p, 18):
                p.stage = UNIVERSITY
                p.log(month, "Started university")
            else:
                self.finish_education(p, 12)
        elif age == 22 and p.stage == UNIVERSITY and p.education < 16:
            p.education = 16
            if rng.random() < econ.continue_education_prob(p, 22):
                p.log(month, "Graduated and began a postgraduate degree")
            else:
                self.finish_education(p, 16)
        elif age == 24 and p.stage == UNIVERSITY:
            self.finish_education(p, 18)
        if p.stage == WORK:
            econ.refresh_wage(p)
            if age >= self.P.retirement_age or (age >= 55 and p.health < 0.3):
                self.retire(p)

    def finish_education(self, p: Person, years: int) -> None:
        p.education = years
        p.stage = WORK
        p.employed = False
        p.months_unemployed = 0
        label = {10: "Left school at 16", 12: "Finished high school",
                 16: "Graduated from university", 18: "Completed a postgraduate degree"}[years]
        p.log(self.sim.month, f"{label} and entered the job market")

    def retire(self, p: Person) -> None:
        if p.employed:
            self.sim.economy.lose_job(p, "", quiet=True)
        p.stage = RETIRED
        p.log(self.sim.month, "Retired")

    # ================================================================= death
    def die(self, p: Person, cause: str) -> None:
        sim, month, people = self.sim, self.sim.month, self.sim.people
        age = p.age(month)
        p.alive = False
        p.death_month = month
        p.death_cause = cause
        p.log(month, f"Died of {cause} at age {int(age)}")
        sim.counters["deaths"] += 1
        sim.deaths_by_band[age_band(age)] += 1
        if p.partner_id is not None:
            partner = people[p.partner_id]
            partner.partner_id = None
            partner.life_sat -= 1.5
            partner.stress += 0.8
            partner.trauma = min(1.0, partner.trauma + 0.1)
            partner.log(month, f"Widowed: {p.name} died")
        for kin_id in (*p.children, p.mother_id, p.father_id):
            if kin_id is not None and people[kin_id].alive:
                people[kin_id].life_sat -= 0.8
                people[kin_id].stress += 0.4
        self.settle_estate(p)
        p.employed = False
        for oid in list(p.ties):
            people[oid].ties.pop(p.id, None)
        p.ties.clear()
        if p.prison_release:
            sim.pools.prison.remove(p)
            p.prison_release = 0
        sim.alive.remove(p)
        if sim.gov.mayor_id == p.id:
            sim.politics.remove_mayor("died in office")

    def settle_estate(self, p: Person) -> None:
        """Inheritance: tax, then half to a surviving partner, the rest split equally
        among living children; an estate with no heirs goes to the treasury.
        Unpaid debts die with the debtor (written off by creditors)."""
        sim, econ, people = self.sim, self.sim.economy, self.sim.people
        if p.wealth <= 0.0:
            econ.external(p, -p.wealth, "debt_writeoff")
            return
        econ.transfer(p, sim.gov, p.wealth * sim.gov.policy.inheritance_tax, "inheritance_tax")
        partner = people[p.partner_id] if p.partner_id is not None else None
        children = [people[i] for i in p.children if people[i].alive]
        if partner is not None and partner.alive:
            share = 0.5 if children else 1.0
            econ.transfer(p, partner, p.wealth * share, "inheritance")
        if children:
            each = p.wealth / len(children)
            for c in children:
                econ.transfer(p, c, each, "inheritance")
        if p.wealth > 0.0:
            econ.transfer(p, sim.gov, p.wealth, "unclaimed_estates")
        p.wealth = 0.0          # clear floating-point dust

    # ========================================================== partnerships
    @staticmethod
    def compatible(a: Person, b: Person) -> bool:
        if a.same_sex_pref != b.same_sex_pref:
            return False
        return a.sex == b.sex if a.same_sex_pref else a.sex != b.sex

    def partnerships(self) -> None:
        """Singles look among the people they already know. Attraction mixes
        closeness with similarity, so mating is assortative on age, education and
        ideology, as observed empirically."""
        sim, D, rng, month, people = self.sim, self.P, self.sim.rng, self.sim.month, self.sim.people
        for p in sim.alive:
            if p.partner_id is not None or not p.free or rng.random() > D.partner_search_prob:
                continue
            age = p.age(month)
            if not 18.0 <= age <= 70.0:
                continue
            best, best_score = None, 0.0
            for oid, tie in p.ties.items():
                if tie.strength < 0.12:
                    continue
                q = people[oid]
                if (q.partner_id is not None or not q.free or not self.compatible(p, q)
                        or abs(q.age(month) - age) > D.max_partner_age_gap or q.age(month) < 18.0
                        or is_relative(p, q)):
                    continue
                score = 0.6 * tie.strength + 0.4 * similarity(p, q, month)
                if score > best_score:
                    best, best_score = q, score
            if best is not None and rng.random() < D.partnership_rate * best_score:
                self.form_couple(p, best)

    def form_couple(self, a: Person, b: Person, quiet: bool = False) -> None:
        sim, month = self.sim, self.sim.month
        a.partner_id, b.partner_id = b.id, a.id
        q = clamp(0.62 + 0.25 * similarity(a, b, month) + 0.05 * (a.agreeableness + b.agreeableness), 0.3, 1.0)
        a.rel_quality = b.rel_quality = q
        link(a, b, 0.9, PARTNER, 0.8, 0.8)
        home = a.district if a.income >= b.income else b.district
        for x in (a, b):
            self.move(x, home, quiet=True)
        if not quiet:
            sim.counters["partnerships"] += 1
            a.life_sat += 0.5
            b.life_sat += 0.5
            a.log(month, f"Married {b.name}")
            b.log(month, f"Married {a.name}")

    def couples(self) -> None:
        sim, D, rng, month, people = self.sim, self.P, self.sim.rng, self.sim.month, self.sim.people
        for a in list(sim.alive):
            if a.partner_id is None or a.id > a.partner_id or not a.alive:
                continue
            b = people[a.partner_id]
            # relationship quality drifts towards a set point shaped by personality and hardship
            target = (0.75 + 0.04 * (a.agreeableness + b.agreeableness) - 0.04 * (a.neuroticism + b.neuroticism)
                      - 0.06 * (a.stress + b.stress) - 0.15 * max(a.strain, b.strain)
                      + 0.10 * (similarity(a, b, month) - 0.5) - 0.2 * (a.incarcerated or b.incarcerated))
            q = clamp(a.rel_quality + 0.05 * (target - a.rel_quality) + rng.gauss(0.0, 0.02), 0.0, 1.0)
            a.rel_quality = b.rel_quality = q
            divorce = D.divorce_base * math.exp(-D.divorce_quality_slope * (q - 0.6))
            if rng.random() < divorce:
                self.divorce(a, b)
                continue
            self.fertility(a, b)

    def divorce(self, a: Person, b: Person) -> None:
        sim, month = self.sim, self.sim.month
        a.partner_id = b.partner_id = None
        sim.counters["divorces"] += 1
        for x, y in ((a, b), (b, a)):
            tie = x.ties.get(y.id)
            if tie is not None:
                tie.kind = FRIEND
                tie.strength = 0.2
                tie.beta += 3.0
            x.life_sat -= 0.9
            x.stress += 0.5
            x.log(month, f"Divorced {y.name}")

    # ============================================================== fertility
    def fertility(self, a: Person, b: Person) -> None:
        sim, D, rng, month = self.sim, self.P, self.sim.rng, self.sim.month
        women = [x for x in (a, b) if x.sex == "F"]
        if not women or not (a.free and b.free):
            return
        mother = min(women, key=lambda x: -x.birth_month)       # the younger woman
        partner = b if mother is a else a
        age = mother.age(month)
        if not 18.0 <= age <= 45.0:
            return
        living = sum(1 for i in mother.children if sim.people[i].alive)
        ideal = 0.5 * (a.ideal_children + b.ideal_children)
        desire = clamp((ideal - living) / max(ideal, 1.0), 0.0, 1.0) + 0.03
        pct = max(sim.income_pct.get(a.id, 0.3), sim.income_pct.get(b.id, 0.3))
        security = 0.6 + 0.8 * sigmoid(2.0 * (pct - 0.4) - 2.0 * max(a.strain, b.strain))
        rate = D.fertility_peak * math.exp(-((age - D.fertility_peak_age) / D.fertility_spread) ** 2)
        if rng.random() < rate * desire * security / 12.0:
            self.birth(mother, partner)

    def birth(self, mother: Person, partner: Person) -> Person:
        sim, rng, month = self.sim, self.sim.rng, self.sim.month
        h2 = sim.cfg.traits.heritability
        if partner.sex == "M":
            other_genes = partner.genes
        else:                                                   # donor conception
            other_genes, _ = founder_traits(rng, h2, sim.cfg.traits.shift)
        genes, traits = inherited_traits(rng, mother.genes, other_genes, h2)
        sex = rng.choice("FM")
        surname = rng.choice((mother.last_name, partner.last_name))
        child = sim.new_person(sex, month, surname, genes, traits, mother.district,
                               mother_id=mother.id, father_id=partner.id)
        # Political orientation = parental socialisation (Jennings & Niemi 1968) plus the
        # child's own personality: open people lean left, conscientious people right
        # (Gerber et al. 2010), which makes ideology partly heritable (Hatemi et al. 2014).
        own = self.disposition(child)
        child.ideology = child.anchor = clamp(0.25 * (mother.ideology + partner.ideology) + 0.8 * own, -1.0, 1.0)
        self.connect_family(child)
        sim.counters["births"] += 1
        sim.births_by_band[int((mother.age(month) - 15.0) // 5)] += 1
        for parent in (mother, partner):
            parent.life_sat += 0.6
            parent.stress += 0.15
            parent.log(month, f"Became a parent: {child.first_name} was born")
        child.log(month, f"Born in {sim.district_name(child.district)} to {mother.name} and {partner.name}")
        return child

    def disposition(self, p: Person, class_pct: float = 0.5) -> float:
        """A person's own ideological leaning from personality and class position."""
        return math.tanh(0.3 * p.conscientiousness - 0.7 * p.openness + 0.6 * (2.0 * class_pct - 1.0)
                         + self.sim.rng.gauss(0.0, 1.0))

    def connect_family(self, child: Person) -> None:
        people = self.sim.people
        parents = [people[i] for i in (child.mother_id, child.father_id) if i is not None]
        for parent in parents:
            parent.children.append(child.id)
            if parent.alive:
                link(child, parent, 0.95, FAMILY, 0.9, 0.9)
            for sib_id in parent.children:
                sib = people[sib_id]
                if sib is not child and sib.alive:
                    link(child, sib, 0.7, FAMILY, 0.8, 0.8)
            for gp_id in (parent.mother_id, parent.father_id):
                if gp_id is not None and people[gp_id].alive:
                    link(child, people[gp_id], 0.5, FAMILY, 0.85, 0.85)

    # ============================================================ relocation
    def move(self, p: Person, district: int, quiet: bool = False) -> None:
        if p.district == district:
            return
        p.district = district
        if not quiet:
            p.log(self.sim.month, f"Moved to {self.sim.district_name(district)}")
        for c in (self.sim.people[i] for i in p.children):
            if c.alive and c.stage in (CHILD, SCHOOL):
                c.district = district

    def relocation(self) -> None:
        """Households whose rent is unaffordable move down-market; prosperous ones
        move up. This simple rule is enough for income segregation to emerge
        (compare Schelling 1971)."""
        sim, E, D, rng, people = self.sim, self.sim.economy.P, self.P, self.sim.rng, self.sim.people
        n = len(E.district_housing)
        for p in list(sim.alive):
            if p.stage in (CHILD, SCHOOL) or not p.free or (p.partner_id is not None and p.partner_id < p.id):
                continue
            members = [p] + ([people[p.partner_id]] if p.partner_id is not None else [])
            income = sum(max(0.0, m.income) for m in members) / len(members)
            wealth = sum(m.wealth for m in members) / len(members)
            housing = 0.5 * E.living_cost * E.district_housing[p.district]
            share = housing / max(income, 1.0)
            target = p.district
            if share > 0.35 and p.district > 0:
                target = p.district - 1
            elif share < 0.15 and wealth > 30000.0 and p.district < n - 1:
                target = p.district + 1
            if target != p.district and rng.random() < D.relocation_prob * (2.0 if target < p.district else 1.0):
                for m in members:
                    self.move(m, target)

    # ===================================================== founding population
    def survival(self, age: float) -> float:
        D = self.P
        cumulative = D.makeham_a * age + D.gompertz_b / D.gompertz_c * (math.exp(D.gompertz_c * age) - 1.0)
        return math.exp(-cumulative)

    def populate(self) -> None:
        """Build a founding population of households whose ages follow the
        stationary (life-table) distribution, with real family links, so that
        parents and children share genes and mobility can be measured."""
        sim, D, rng, cfg = self.sim, self.P, self.sim.rng, self.sim.cfg
        ages = list(range(18, 91))
        weights = [self.survival(a) for a in ages]
        households: list[list[Person]] = []
        while len(sim.people) < cfg.initial_population:
            age = rng.choices(ages, weights)[0]
            if rng.random() < 0.30 or age > 82:
                households.append([self.founder(age, rng.choice("FM"))])
                continue
            a = self.founder(age, "F")
            partner_age = int(clamp(age + round(rng.gauss(2.0, 3.0)), 18, 95))
            same_sex = rng.random() < D.same_sex_share
            b = self.founder(partner_age, "F" if same_sex else "M")
            a.same_sex_pref = b.same_sex_pref = same_sex
            self.form_couple(a, b, quiet=True)
            household = [a, b]
            if 22 <= age <= 70 and rng.random() < 0.8:
                for _ in range(max(1, min(4, a.ideal_children + rng.choice((-1, 0, 0, 1))))):
                    child_age = age - rng.randint(20, 38)
                    if child_age < 0:
                        continue
                    other = b if not same_sex else None
                    kid = self.founder_child(a, other, child_age)
                    if child_age >= 18:
                        households.append([kid])
                    else:
                        household.append(kid)
            households.append(household)
        self.initialise_adults(households)

    def founder(self, age: int, sex: str) -> Person:
        sim, rng = self.sim, self.sim.rng
        genes, traits = founder_traits(rng, sim.cfg.traits.heritability, sim.cfg.traits.shift)
        p = sim.new_person(sex, sim.month - age * 12 - rng.randrange(12), rng.choice(SURNAMES), genes, traits, 0)
        p.same_sex_pref = rng.random() < self.P.same_sex_share
        return p

    def founder_child(self, mother: Person, father: Person | None, age: int) -> Person:
        sim, rng = self.sim, self.sim.rng
        h2 = sim.cfg.traits.heritability
        other_genes = father.genes if father is not None else founder_traits(rng, h2, sim.cfg.traits.shift)[0]
        genes, traits = inherited_traits(rng, mother.genes, other_genes, h2)
        surname = father.last_name if father is not None and rng.random() < 0.5 else mother.last_name
        kid = sim.new_person(rng.choice("FM"), sim.month - age * 12 - rng.randrange(12), surname, genes, traits,
                             0, mother_id=mother.id, father_id=father.id if father else None)
        self.connect_family(kid)
        return kid

    def initialise_adults(self, households: list[list[Person]]) -> None:
        """Education, jobs, wealth, neighbourhood, opinions and friendships for t = 0."""
        sim, rng, econ, month = self.sim, self.sim.rng, self.sim.economy, self.sim.month
        people = sim.people
        # schooling and life stage
        for p in people:
            age = p.age(month)
            if age >= 16:
                p.parent_pct = rng.random() if p.mother_id is None else None
                years = 10
                if rng.random() < econ.continue_education_prob(p, 16):
                    years = 12
                    if age >= 18 and rng.random() < econ.continue_education_prob(p, 18):
                        years = 16
                        if age >= 22 and rng.random() < econ.continue_education_prob(p, 22):
                            years = 18
                p.education = years
                finished_at = {10: 16, 12: 18, 16: 22, 18: 24}[years]
                if age < finished_at:
                    p.education, p.stage = (12, UNIVERSITY) if years >= 16 else (10, SCHOOL)
                elif age >= self.P.retirement_age:
                    p.stage = RETIRED
                else:
                    p.stage = WORK
                p.experience = max(0.0, age - finished_at - rng.uniform(0.0, 3.0))
            elif age >= 6:
                p.stage = SCHOOL
                p.education = int(age) - 6
        # jobs: fill openings among working-age founders; retirees get a past career for their biography
        workers = [p for p in people if p.stage == WORK]
        rng.shuffle(workers)
        openings = {o.name: round(o.share * len(workers) * 0.95) for o in OCCUPATIONS}
        openings[POLICE] = round(sim.gov.policy.police_per_1000 * len(people) / 1000.0)
        for p in workers:
            occ = econ.choose_occupation(p, openings)
            if occ is not None:
                econ.hire(p, occ, quiet=True)
                openings[occ.name] -= 1
            else:
                p.last_wage = econ.P.base_wage * 0.8
        for p in people:
            if p.stage == RETIRED:
                occ = econ.choose_occupation(p, {o.name: 1 for o in OCCUPATIONS if o.name != POLICE})
                p.occupation = occ.name if occ else "Labourer"
        # wealth: savings accumulated over a working life, with lognormal luck
        for p in people:
            age = p.age(month)
            if age < 18:
                continue
            annual = 12.0 * (econ.wage_level(p, OCC[p.occupation]) if p.occupation else econ.P.base_wage * 0.8)
            years = max(0.0, age - 22.0)
            p.wealth = annual * 0.07 * years * rng.lognormvariate(-0.3, 0.85)
            if age < 32 and rng.random() < 0.35:
                p.wealth -= rng.uniform(2000.0, 20000.0)          # student and consumer debt
            p.income = annual / 12.0 * 0.75
        # neighbourhoods: richer households live in pricier districts (with noise)
        n = len(econ.P.district_housing)
        ranked = sorted(households, key=lambda h: sum(m.income for m in h) / len(h))
        for rank, household in enumerate(ranked):
            pct = clamp(rank / len(ranked) + rng.gauss(0.0, 0.2), 0.0, 0.999)
            for m in household:
                m.district = int(pct * n)
        # partners share a home
        for p in people:
            if p.partner_id is not None and p.partner_id > p.id:
                q = people[p.partner_id]
                for m in (p, q):
                    self.move(m, p.district, quiet=True)
        sim.refresh()
        for p in people:                          # founders' older children: record parental rank now
            if p.mother_id is not None and 16.0 <= p.age(month) <= 25.0:
                p.parent_pct = econ.parent_income_pct(p)
                p.parent_pct_n = 1
        # opinions: openness -> left, conscientiousness and income -> right; drawn from the
        # same generative model as newborns so polarisation starts near its steady state
        for p in people:
            p.ideology = 0.75 * self.disposition(p, sim.income_pct.get(p.id, 0.5))
            p.inst_trust = clamp(0.55 + rng.gauss(0.0, 0.12), 0.0, 1.0)
        for p in people:
            if p.age(month) < 18 and p.mother_id is not None:
                parents = [people[i].ideology for i in (p.mother_id, p.father_id) if i is not None]
                p.ideology = clamp(0.5 * sum(parents) / len(parents) + 0.8 * self.disposition(p), -1.0, 1.0)
            p.anchor = p.ideology
        susceptible = sorted(people, key=lambda x: -sim.social.susceptibility(x) + rng.gauss(0.0, 0.5))
        for p in people:
            p.conspiracy = rng.uniform(0.0, 0.15)
        for p in susceptible[: max(1, len(people) // 25)]:
            if p.age(month) >= 16:
                p.conspiracy = rng.uniform(0.6, 0.9)
        # friendships: homophilous contacts within the neighbourhood and workplace
        for p in people:
            if p.age(month) < 6:
                continue
            pool = sim.social.context_pool(p) or sim.pools.district[p.district]
            for _ in range(poisson(rng, 6.0 * math.exp(0.25 * p.extraversion))):
                cands = [rng.choice(pool) for _ in range(3)]
                q = softmax_choice(rng, cands, [4.0 * similarity(p, c, month) for c in cands])
                if q is not p and q.id not in p.ties:
                    link(p, q, rng.uniform(0.1, 0.5), FRIEND, rng.uniform(0.5, 0.8), rng.uniform(0.5, 0.8))
