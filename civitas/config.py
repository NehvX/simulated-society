"""Every tunable number in the model, in one place.

Parameters are grouped by subsystem. Where a value comes from the empirical
literature the source is noted; the rest are calibration choices made so that
the simulated society reproduces well-known stylised facts (see docs/MODEL.md).
"""
from __future__ import annotations

import copy
import json
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from typing import Any


@dataclass
class Policy:
    """Levers controlled by the elected mayor (or fixed, in experiments)."""
    income_tax: float = 0.26            # marginal rate above the allowance
    top_tax: float = 0.10               # extra marginal rate above the top threshold
    welfare_floor: float = 900.0        # guaranteed minimum monthly income (means-tested)
    ubi: float = 0.0                    # universal basic income per adult per month
    child_benefit: float = 150.0        # per dependent child per month
    police_per_1000: float = 5.0        # law-enforcement staff per 1,000 residents
    education_subsidy: float = 0.5      # share of university tuition paid by the state
    mental_health_pc: float = 15.0      # mental-health budget per resident per month
    public_services_pc: float = 320.0   # schools, healthcare, roads: per resident per month
    unemployment_replacement: float = 0.5
    pension_rate: float = 0.45          # pension as a share of the average wage
    inheritance_tax: float = 0.15
    # How the shared resource (the commons) is used and who gets its output:
    # open_access | regulated | equal_shares | need_based | private_ownership
    commons_rule: str = "regulated"


@dataclass
class TraitParams:
    # Narrow-sense heritability h^2 per trait. Personality ~0.40
    # (Vukasovic & Bratko 2015 meta-analysis); adult cognitive ability ~0.5-0.7.
    heritability: dict = field(default_factory=lambda: {
        "honesty": 0.40, "neuroticism": 0.40, "extraversion": 0.45,
        "agreeableness": 0.35, "conscientiousness": 0.40, "openness": 0.45,
        "intelligence": 0.55,
    })
    # Shift the founding population's average trait (in s.d.), e.g. {"honesty": -0.5}.
    # The shift is placed in the genes, so it is inherited by later generations.
    shift: dict = field(default_factory=dict)


@dataclass
class CommonsParams:
    """A shared renewable resource (farmland, fishery, forest, water) with
    logistic regrowth dR = rR(1 - R/K) - harvest."""
    capacity_per_capita: float = 60.0    # carrying capacity K, in units per founding resident
    regen_rate: float = 0.04             # monthly intrinsic regrowth r; max sustainable yield = rK/4
    initial_stock: float = 0.8           # R0 / K
    unit_value: float = 400.0            # $ earned per unit harvested
    base_effort: float = 1.0             # units a typical harvester wants per month
    target_stock: float = 0.6            # quotas steer the stock towards this share of K
    compliance_intercept: float = 1.0    # willingness to respect a quota
    scarcity_cost: float = 0.6           # essentials cost +60% when the commons is exhausted


@dataclass
class GrowthParams:
    """Annual productivity growth g = sum of the terms below (see docs/MODEL.md §14)."""
    base: float = 0.011                  # background technological progress
    human_capital: float = 0.010         # per year of workers' mean schooling above 12.5
    innovation: float = 0.010            # per s.d. of workers' mean (openness + intelligence) / 2
    social_capital: float = 0.040        # per unit of everyday cooperation rate above 0.945
    institutions: float = 0.030          # per unit of institutional trust above 0.46
    corruption: float = 0.5              # per share of tax revenue embezzled
    public_investment: float = 0.010     # per log-unit of public services relative to $320
    crime: float = 0.0045                # x ln(1 + excess/15), excess = (property + 3 x assault)/1,000 above 15
    scarcity: float = 0.040              # drag when the commons is fully exhausted
    max_rate: float = 0.06


@dataclass
class DemographyParams:
    # Gompertz-Makeham mortality mu(x) = A + B*exp(c*x) per year.
    # c = 0.092 means the death rate doubles every ln2/c ~ 7.5 years of age.
    makeham_a: float = 0.0004
    gompertz_b: float = 0.000035
    gompertz_c: float = 0.092
    infant_mortality: float = 0.004
    frailty_health: float = 3.0         # hazard multiplier exp(k * (normal health - own health))
    # Fertility: births per partnered woman-year = peak * exp(-((age-peak_age)/spread)^2)
    fertility_peak: float = 0.46
    fertility_peak_age: float = 30.0
    fertility_spread: float = 6.5
    ideal_children_weights: tuple = (0.08, 0.15, 0.42, 0.23, 0.12)   # for 0..4 children
    # Partnership formation and dissolution
    partner_search_prob: float = 0.35   # share of singles actively looking each month
    partnership_rate: float = 0.12
    max_partner_age_gap: float = 12.0
    divorce_base: float = 0.0016        # monthly hazard at relationship quality 0.6
    divorce_quality_slope: float = 5.0
    same_sex_share: float = 0.04
    retirement_age: int = 65
    relocation_prob: float = 0.25       # yearly chance a mis-housed household moves


@dataclass
class SocialParams:
    interactions_per_month: float = 4.0  # initiated per person (x exp(0.25 * extraversion))
    p_existing_tie: float = 0.60         # partner drawn from existing ties (by strength)
    p_friend_of_friend: float = 0.12     # triadic closure (Granovetter 1973)
    stranger_candidates: int = 3         # homophily: best of k random candidates
    homophily_strength: float = 4.0
    new_tie_strength: float = 0.06
    tie_gain: float = 0.07               # w += gain*(1-w) after a kind act
    tie_loss: float = 0.22               # w -= loss*w after being exploited (negativity bias)
    tie_decay: float = 0.05              # monthly exponential decay without contact
    family_tie_floor: float = 0.30
    min_tie_strength: float = 0.04
    max_ties: int = 150                  # Dunbar's number
    trust_memory: float = 0.93           # discounted Beta trust (Josang & Ismail 2002)
    gt_memory: float = 0.985             # generalised trust memory
    witness_prob: float = 0.08           # chance each mutual friend witnesses an interaction
    reputation_rate: float = 0.05
    gossip_weight: float = 0.6
    # Cooperation logit: U = b0 + bH*H + bA*A + bT*(2T-1) + bW*w + bE*ln(1+m) - bS*S - bN*strain
    coop_intercept: float = 1.1
    coop_honesty: float = 0.8
    coop_agreeableness: float = 0.5
    coop_trust: float = 2.0
    coop_tie: float = 1.0
    coop_embeddedness: float = 0.25
    coop_stress: float = 0.45
    coop_need: float = 0.6
    # Fraud and violence that can follow a defection
    fraud_intercept: float = -5.8
    violence_intercept: float = -8.9
    # Opinion dynamics: bounded confidence with repulsion (Deffuant 2000; Jager & Amblard 2005)
    opinion_talk_prob: float = 0.20
    confidence_bound: float = 0.45
    convergence_rate: float = 0.06
    repulsion_threshold: float = 0.6
    repulsion_rate: float = 0.04
    stubbornness: float = 0.10           # pull back towards one's anchor (Friedkin & Johnsen 1990)
    agree_bonding: float = 0.03          # agreement strengthens a tie ...
    disagree_distancing: float = 0.08    # ... strong disagreement weakens it
    # Misinformation contagion
    rumour_share_prob: float = 0.40
    rumour_adoption: float = 0.25
    debunk_prob: float = 0.30
    debunk_rate: float = 0.15
    rumour_decay: float = 0.02
    media_exposure: float = 0.04         # monthly pull towards one's susceptibility via media
    susceptibility_intercept: float = -1.2
    susceptibility_distrust: float = 2.5  # weight on (1/2 - institutional trust)
    rumour_seeds_per_year: float = 4.0


@dataclass
class EconomyParams:
    base_wage: float = 3000.0            # monthly, 12 years schooling, no experience
    return_to_schooling: float = 0.08    # Mincer; Psacharopoulos & Patrinos (2018)
    exp_linear: float = 0.035
    exp_quadratic: float = 0.0006
    wage_luck_sd: float = 0.22           # persistent unobserved productivity
    entrepreneur_volatility: float = 0.35
    separation_rate: float = 0.012       # monthly job-loss hazard
    job_finding_rate: float = 0.10       # monthly job-finding hazard, before the network bonus
    weak_tie_bonus: float = 0.25         # Granovetter's "strength of weak ties"
    record_penalty: float = 0.7          # exp(-0.7) ~ halves call-backs (Pager 2003)
    recession_separation: float = 1.6
    recession_finding: float = 0.70
    recession_depth: float = 0.05        # productivity drop in a recession
    mean_expansion_months: float = 84.0  # 2-state Markov business cycle (Hamilton 1989)
    mean_recession_months: float = 14.0
    n_firms: int = 0                     # 0 = one firm per ~25 residents
    benefit_months: int = 12
    sick_pay: float = 0.7
    tax_allowance: float = 1000.0
    top_threshold: float = 10000.0
    living_cost: float = 1150.0          # monthly adult essentials at housing multiplier 1
    couple_scale: float = 0.75           # each partner pays 75% (OECD equivalence ~1.5)
    child_cost: float = 450.0
    tuition: float = 900.0
    parent_support_wealth: float = 40000.0
    welfare_wealth_limit: float = 15000.0
    mpc_base: float = 0.88               # marginal propensity to consume, shifted by traits
    wealth_mpc: float = 0.0025           # monthly consumption out of wealth
    expense_shock_prob: float = 0.05     # monthly chance of an unexpected bill (car, medical, ...)
    expense_shock_size: float = 1.5      # mean size, in months of living costs
    safe_return: float = 0.01            # annual
    equity_return: float = 0.07          # annual mean
    equity_volatility: float = 0.20      # annual s.d. (Kesten process -> Pareto tail)
    recession_return: float = -0.15      # annual equity drag during a recession
    risky_scale: float = 30000.0
    debt_rate: float = 0.10              # annual interest on negative wealth
    bankruptcy_threshold: float = -45000.0
    gov_debt_rate: float = 0.03
    prison_cost: float = 3000.0          # per inmate per month
    district_housing: tuple = (0.70, 0.85, 1.00, 1.25, 1.60)


@dataclass
class CrimeParams:
    # Becker (1968) expected-utility crime decision, as a logit.
    intercept: float = -7.5
    need: float = 1.8
    unemployed: float = 0.7
    honesty: float = 0.9
    conscientiousness: float = 0.45
    agreeableness: float = 0.35
    neuroticism: float = 0.25
    youth: float = 0.8
    male: float = 0.45
    peers: float = 2.0                   # differential association (Sutherland 1947)
    prior_record: float = 0.7
    deterrence: float = 3.0              # weight on expected punishment p * sentence
    legitimacy: float = 1.2              # Tyler (1990): trusted institutions are obeyed
    mean_loot: float = 700.0
    police_effect: float = 0.085         # p_arrest = 1 - exp(-k * officers_per_1000)
    violent_clearance_mult: float = 1.6
    conviction_prob: float = 0.85
    custody_property: float = 0.25       # share of property convictions that lead to prison
    custody_violent: float = 0.60
    fine: float = 800.0
    theft_sentence: float = 4.0          # months, before prior-record multiplier
    assault_sentence: float = 10.0
    fraud_sentence: float = 4.0
    bribe_intercept: float = -2.6
    internal_affairs: float = 0.15


@dataclass
class WellbeingParams:
    life_sat_base: float = 6.9           # 0-10 Cantril ladder
    adaptation_rate: float = 0.15        # Ornstein-Uhlenbeck mean reversion per month
    life_sat_noise: float = 0.25
    stress_recovery: float = 0.14
    crisis_intercept: float = -7.3
    crisis_recovery: float = 0.12
    treatment_scale: float = 12.0        # access = 1 - exp(-budget_pc / scale)
    trauma_half_life: float = 36.0       # months (12 if treated)


@dataclass
class PoliticsParams:
    term_months: int = 48
    term_limit: int = 2
    candidates: int = 3
    min_candidate_age: int = 30
    ideology_weight: float = 3.0
    trust_weight: float = 1.5
    reputation_weight: float = 2.0
    charisma_weight: float = 0.35
    incumbency_weight: float = 1.5
    max_embezzle: float = 0.06           # max share of monthly revenue a crooked mayor skims
    scandal_hazard: float = 0.02         # detection hazard per month of embezzling
    scandal_trust_shock: float = 0.20
    fiscal_debt_limit: float = 0.9       # public debt / annual labour income
    trust_adjust: float = 0.05
    conspiracy_distrust: float = 0.15    # conspiracy believers distrust institutions


@dataclass
class SimConfig:
    seed: int = 42
    years: int = 40
    initial_population: int = 600
    burn_in_months: int = 18
    district_names: tuple = ("Eastfield", "Riverside", "Old Town", "Northgate", "Hillcrest")
    elections: bool = True
    lock_policy: bool = False            # experiments: policy fixed; tax auto-balances the budget
    verbose: bool = True
    policy: Policy = field(default_factory=Policy)
    traits: TraitParams = field(default_factory=TraitParams)
    demography: DemographyParams = field(default_factory=DemographyParams)
    social: SocialParams = field(default_factory=SocialParams)
    economy: EconomyParams = field(default_factory=EconomyParams)
    crime: CrimeParams = field(default_factory=CrimeParams)
    wellbeing: WellbeingParams = field(default_factory=WellbeingParams)
    politics: PoliticsParams = field(default_factory=PoliticsParams)
    commons: CommonsParams = field(default_factory=CommonsParams)
    growth: GrowthParams = field(default_factory=GrowthParams)
    scenario: str = "baseline"

    # ---------------------------------------------------------------- helpers
    def copy(self) -> "SimConfig":
        return copy.deepcopy(self)

    def to_dict(self) -> dict:
        return asdict(self)

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2)

    @classmethod
    def from_dict(cls, data: dict) -> "SimConfig":
        cfg = cls()
        _merge(cfg, data)
        return cfg

    @classmethod
    def load(cls, path: str) -> "SimConfig":
        with open(path, encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))

    def override(self, dotted: str, value: Any) -> None:
        """Set e.g. 'policy.income_tax' or 'crime.deterrence' from the command line."""
        target: Any = self
        *path, leaf = dotted.split(".")
        for part in path:
            target = getattr(target, part)
        if not hasattr(target, leaf):
            raise AttributeError(f"unknown parameter '{dotted}'")
        current = getattr(target, leaf)
        setattr(target, leaf, type(current)(value) if not isinstance(current, (tuple, dict)) else value)


def _merge(obj: Any, data: dict) -> None:
    for f in fields(obj):
        if f.name not in data:
            continue
        current, incoming = getattr(obj, f.name), data[f.name]
        if is_dataclass(current) and isinstance(incoming, dict):
            _merge(current, incoming)
        elif isinstance(current, tuple):
            setattr(obj, f.name, tuple(incoming))
        else:
            setattr(obj, f.name, incoming)
