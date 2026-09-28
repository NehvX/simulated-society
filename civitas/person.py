"""The agent: one simulated human being, and the ties that connect them."""
from __future__ import annotations

from .traits import TRAIT_NAMES

# Life stages
CHILD, SCHOOL, UNIVERSITY, WORK, RETIRED = "child", "school", "university", "work", "retired"

# Kinds of social tie
FAMILY, PARTNER, FRIEND = "family", "partner", "friend"


class Tie:
    """One person's view of a relationship with another person.

    strength  w in [0, 1]: closeness, which sets how often the two meet.
    alpha, beta: pseudo-counts of observed cooperation and defection. Trust is
    the mean of the Beta(alpha, beta) belief, E[p_cooperate] = alpha / (alpha + beta),
    with old evidence discounted by a forgetting factor (Josang & Ismail 2002).
    Ties are stored per direction, so trust can be asymmetric.
    """

    __slots__ = ("strength", "alpha", "beta", "kind")

    def __init__(self, strength: float, trust: float, kind: str = FRIEND, weight: float = 3.0):
        self.strength = strength
        self.alpha = trust * weight
        self.beta = (1.0 - trust) * weight
        self.kind = kind

    @property
    def trust(self) -> float:
        return self.alpha / (self.alpha + self.beta)


class Person:
    __slots__ = (
        # identity & family
        "id", "first_name", "last_name", "sex", "same_sex_pref", "birth_month",
        "mother_id", "father_id", "partner_id", "children",
        "alive", "death_month", "death_cause",
        # nature
        "genes", *TRAIT_NAMES,
        # life course & work
        "district", "stage", "education", "occupation", "employed", "firm",
        "wage_level", "last_wage", "months_unemployed", "experience", "wage_luck",
        # money
        "wealth", "income", "strain", "mpc", "risk_tolerance", "commons_income",
        # body & mind
        "health", "stress", "trauma", "life_sat", "crisis_months", "treated",
        # beliefs
        "ideology", "anchor", "conspiracy", "inst_trust", "gt_alpha", "gt_beta", "reputation",
        # relationships
        "ties", "rel_quality", "ideal_children",
        # crime
        "prison_release", "record", "crimes", "victimized", "last_victimized", "bribes_taken",
        "last_offence", "last_conviction",
        # running statistics
        "coop_count", "defect_count", "social_month", "conflicts_month",
        "parent_pct", "parent_pct_n", "offices", "events", "trajectory",
    )

    def __init__(self, pid: int, sex: str, birth_month: int, first_name: str, last_name: str,
                 genes: list[float], traits: list[float], district: int,
                 mother_id: int | None = None, father_id: int | None = None):
        self.id = pid
        self.first_name, self.last_name = first_name, last_name
        self.sex = sex
        self.same_sex_pref = False
        self.birth_month = birth_month
        self.mother_id, self.father_id = mother_id, father_id
        self.partner_id: int | None = None
        self.children: list[int] = []
        self.alive = True
        self.death_month: int | None = None
        self.death_cause = ""

        self.genes = genes
        for name, value in zip(TRAIT_NAMES, traits):
            setattr(self, name, value)

        self.district = district
        self.stage = CHILD
        self.education = 0
        self.occupation: str | None = None
        self.employed = False
        self.firm = -1
        self.wage_level = 0.0
        self.last_wage = 0.0
        self.months_unemployed = 0
        self.experience = 0.0
        self.wage_luck = 0.0

        self.wealth = 0.0
        self.income = 0.0
        self.strain = 0.0
        self.mpc = 0.7
        self.risk_tolerance = 0.5
        self.commons_income = 0.0      # this month's share of the shared resource

        self.health = 1.0
        self.stress = 0.2
        self.trauma = 0.0
        self.life_sat = 7.0
        self.crisis_months = 0
        self.treated = False

        self.ideology = 0.0
        self.anchor = 0.0           # one's own "home" position (Friedkin-Johnsen stubbornness)
        self.conspiracy = 0.0
        self.inst_trust = 0.55
        self.gt_alpha, self.gt_beta = 6.0, 4.0
        self.reputation = 0.5

        self.ties: dict[int, Tie] = {}
        self.rel_quality = 0.0
        self.ideal_children = 2

        self.prison_release = 0
        self.record = 0
        self.crimes = 0
        self.victimized = 0
        self.last_victimized = -10_000
        self.bribes_taken = 0
        self.last_offence = -10_000
        self.last_conviction = -10_000

        self.coop_count = 0
        self.defect_count = 0
        self.social_month = 0.0
        self.conflicts_month = 0
        self.parent_pct: float | None = None     # parents' income rank, averaged over ages 10-15
        self.parent_pct_n = 0
        self.offices = 0
        self.events: list[tuple[int, str]] = []
        self.trajectory: list[tuple] = []

    # ----------------------------------------------------------------- queries
    @property
    def name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    def age(self, month: int) -> float:
        return (month - self.birth_month) / 12.0

    @property
    def incarcerated(self) -> bool:
        return self.prison_release > 0

    @property
    def free(self) -> bool:
        return self.alive and self.prison_release == 0

    @property
    def generalized_trust(self) -> float:
        """Trust in strangers: a Beta belief updated by every encounter with them."""
        return self.gt_alpha / (self.gt_alpha + self.gt_beta)

    @property
    def cooperation_rate(self) -> float:
        n = self.coop_count + self.defect_count
        return self.coop_count / n if n else 1.0

    @property
    def job_title(self) -> str:
        if not self.alive:
            return "Deceased"
        if self.incarcerated:
            return "Incarcerated"
        if self.stage == WORK:
            return self.occupation if self.employed else "Unemployed"
        return {CHILD: "Child", SCHOOL: "Student", UNIVERSITY: "University", RETIRED: "Retired"}[self.stage]

    def traits(self) -> dict[str, float]:
        return {name: getattr(self, name) for name in TRAIT_NAMES}

    def log(self, month: int, text: str) -> None:
        self.events.append((month, text))

    def __repr__(self) -> str:
        return f"<Person #{self.id} {self.name}>"
