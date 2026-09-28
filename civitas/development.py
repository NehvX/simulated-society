"""Is the society developing, stagnating or collapsing, and why?

1. Civitas Development Index (CDI), in the spirit of the UN Human Development
   Index: the geometric mean of six dimensions, each scaled to [0, 1].

       health          (life expectancy - 20) / 65
       knowledge       mean schooling of adults aged 25-64 / 18 years
       living standard ln(real median income / 400) / ln(30)   (real = / price of essentials)
       equality        1 - income Gini
       cohesion        mean of institutional trust, cooperation rate and safety
       sustainability  commons stock / carrying capacity

   A geometric mean punishes imbalance: a rich society with an exhausted
   environment or no trust scores low.

2. Endogenous productivity growth. Each year trend productivity (which
   multiplies every wage) grows by

       g = base + human capital + innovation + social capital + institutions
           - corruption + public investment - crime - resource scarcity

   Each term is computed from the simulated people themselves, so individual
   behaviour and policy feed back into the long-run prosperity of the town
   (Barro 1991 on schooling; Knack & Keefer 1997 on trust; Mauro 1995 on
   corruption; Brander & Taylor 1998 on resource collapse).

3. The trajectory verdict: rapid growth, growth, stagnation, decline or
   collapse, with the factors that drove it and the real-world levers they
   correspond to.
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

from . import metrics
from .mathutil import clamp, mean
from .person import WORK

if TYPE_CHECKING:
    from .simulation import Simulation

DIMENSIONS = ("health", "knowledge", "living_standard", "equality", "cohesion", "sustainability")

# growth component -> (plain name, what to do about it in the real world)
GROWTH_FACTORS = {
    "human_capital": ("Education and skills",
                      "widen access to education: tuition support, better schools in poor districts"),
    "innovation": ("Curiosity and talent",
                   "reward curiosity and new ideas: research, entrepreneurship, open exchange"),
    "social_capital": ("Everyday cooperation",
                       "build trust between citizens: fair dealing, community ties, working reputation systems"),
    "institutions": ("Trust in institutions",
                     "competent, fair government that people believe in"),
    "corruption": ("Corruption",
                   "transparency, audits and prosecution of officials who steal"),
    "public_investment": ("Public investment",
                          "fund infrastructure, healthcare and public services"),
    "crime": ("Crime",
              "prevention (jobs, support, rehabilitation) as well as policing"),
    "scarcity": ("Resource scarcity",
                 "manage shared resources sustainably: quotas people respect, enforcement"),
}


# ======================================================== development index
def development_index(sim: "Simulation", record: dict) -> dict:
    month = sim.month
    e0 = record.get("life_expectancy")
    if e0 is None:
        e0 = next((r["life_expectancy"] for r in reversed(sim.history) if r.get("life_expectancy")), 75.0)
    adults = [p for p in sim.alive if 25.0 <= p.age(month) < 65.0]
    schooling = mean([p.education for p in adults], 12.0)
    real_income = record["median_income"] / sim.commons.cost_multiplier
    safety = 1.0 - min(1.0, (record["property_crime_rate"] + 3.0 * record["assault_rate"]) / 150.0)
    dims = {
        "health": clamp((e0 - 20.0) / 65.0, 0.0, 1.0),
        "knowledge": clamp(schooling / 18.0, 0.0, 1.0),
        "living_standard": clamp(math.log(max(real_income, 400.0) / 400.0) / math.log(30.0), 0.0, 1.0),
        "equality": clamp(1.0 - record["gini_income"], 0.0, 1.0),
        "cohesion": clamp((record["institutional_trust"] + record["cooperation_rate"] + safety) / 3.0, 0.0, 1.0),
        "sustainability": clamp(sim.commons.level, 0.0, 1.0),
    }
    cdi = math.exp(sum(math.log(max(v, 0.01)) for v in dims.values()) / len(dims))
    return {"cdi": cdi, "real_median_income": real_income,
            **{f"dim_{k}": v for k, v in dims.items()}}


# ======================================================== productivity growth
def growth_components(sim: "Simulation", record: dict) -> dict:
    """This year's contributions (annual rates) to trend productivity growth."""
    G, month = sim.cfg.growth, sim.month
    workers = [p for p in sim.alive if p.stage == WORK and p.free]
    schooling = mean([p.education for p in workers], 12.5)
    talent = mean([(p.openness + p.intelligence) / 2.0 for p in workers], 0.0)
    counters = sim.counters
    embezzled_share = counters["embezzled"] / max(1.0, counters["tax_revenue"])
    services = max(1.0, sim.gov.policy.public_services_pc)
    crime = record["property_crime_rate"] + 3.0 * record["assault_rate"]
    commons = sim.commons
    scarcity = commons.year_scarcity / max(1, commons.year_months)
    return {
        "base": G.base,
        "human_capital": G.human_capital * (schooling - 12.5),
        "innovation": G.innovation * talent,
        "social_capital": G.social_capital * (record["cooperation_rate"] - 0.945),
        "institutions": G.institutions * (record["institutional_trust"] - 0.46),
        "corruption": -G.corruption * embezzled_share,
        "public_investment": G.public_investment * math.log(services / 320.0),
        "crime": -G.crime * math.log1p(max(0.0, crime - 15.0) / 15.0),   # diminishing, not unbounded
        "scarcity": -G.scarcity * scarcity,
    }


def apply_growth(sim: "Simulation", record: dict) -> None:
    comps = growth_components(sim, record)
    G = sim.cfg.growth
    raw = sum(comps.values())
    rate = clamp(raw, -G.max_rate, G.max_rate)
    if raw != rate and raw != 0.0:                # when capped, attribute only the growth that happened
        comps = {k: v * rate / raw for k, v in comps.items()}
    sim.economy.tfp *= math.exp(rate)
    record["growth_rate"] = rate
    record["tfp"] = sim.economy.tfp
    for k, v in comps.items():
        record[f"g_{k}"] = v


# ================================================================ verdict
def classify(history: list[dict], initial_population: int | None = None) -> dict:
    """Name the society's trajectory and explain it."""
    if len(history) < 3:
        return {"status": "too short to tell"}
    # Skip a settling-in period: the founding population starts healthier and less
    # stressed than its long-run state, which would bias the trend downwards.
    settle = min(5, len(history) // 4)
    trend = history[settle:]
    years = [r["year"] for r in trend]
    cdi = [r["cdi"] for r in trend]
    slope, _ = _log_slope(years, cdi)
    pop0 = initial_population or history[0]["population"]
    pop_change = history[-1]["population"] / pop0 - 1.0
    inc0 = mean([r["real_median_income"] for r in trend[:3]])
    inc1 = mean([r["real_median_income"] for r in trend[-3:]])
    income_change = inc1 / inc0 - 1.0 if inc0 > 0 else 0.0
    cdi0, cdi1 = mean(cdi[:3]), mean(cdi[-3:])
    resource_end = history[-1]["commons_level"]
    collapse = (pop_change <= -0.25 or cdi1 / cdi0 - 1.0 <= -0.25
                or (resource_end < 0.10 and slope < 0))
    if collapse:
        status = "Collapse"
    elif slope >= 0.005:
        status = "Rapid growth"
    elif slope >= 0.001:
        status = "Growth"
    elif slope > -0.001:
        status = "Stagnation"
    else:
        status = "Decline"

    totals = {k: sum(r.get(f"g_{k}", 0.0) for r in history) for k in GROWTH_FACTORS}
    drivers = sorted(totals.items(), key=lambda kv: -abs(kv[1]))
    boosts = [(k, v) for k, v in drivers if v > 0.02]
    drags = [(k, v) for k, v in drivers if v < -0.02]
    dims0 = {d: mean([r[f"dim_{d}"] for r in trend[:3]]) for d in DIMENSIONS}
    dims1 = {d: mean([r[f"dim_{d}"] for r in trend[-3:]]) for d in DIMENSIONS}
    return {
        "status": status,
        "collapse": collapse,
        "start_year": trend[0]["year"], "start_index": settle,
        "cdi_start": cdi0, "cdi_end": cdi1, "cdi_rate": slope,
        "income_change": income_change, "population_change": pop_change,
        "tfp_end": history[-1]["tfp"], "resource_end": resource_end,
        "resource_min": min(r["commons_min_level"] for r in history),
        "dims_start": dims0, "dims_end": dims1,
        "drivers": [{"key": k, "label": GROWTH_FACTORS[k][0], "total": v, "lever": GROWTH_FACTORS[k][1]}
                    for k, v in drivers],
        "boost": [GROWTH_FACTORS[k][0] for k, _ in boosts[:3]],
        "suppress": [GROWTH_FACTORS[k][0] for k, _ in drags[:3]],
        "weakest_dimension": min(dims1, key=dims1.get),
    }


def _log_slope(xs: list[float], ys: list[float]) -> tuple[float, float]:
    """Annual growth rate from an OLS fit of ln(y) on time."""
    beta, r2 = metrics.ols([math.log(max(y, 1e-6)) for y in ys], [[x] for x in xs])
    return float(beta[1]), r2


def verdict_text(v: dict) -> str:
    """One paragraph explaining the verdict in plain words."""
    if "cdi_start" not in v:
        return "The run was too short to judge its trajectory."
    parts = [f"{v['status']}: from Year {v['start_year']} (after a settling-in period) the development index "
             f"went from {v['cdi_start']:.3f} to {v['cdi_end']:.3f} "
             f"({v['cdi_rate'] * 100:+.2f}% a year). Real median income changed by {v['income_change']:+.0%}, "
             f"population by {v['population_change']:+.0%}, and the shared resource ended at "
             f"{v['resource_end']:.0%} of capacity (low point {v['resource_min']:.0%})."]
    if v["boost"]:
        parts.append("What lifted productivity most: " + ", ".join(v["boost"]).lower() + ".")
    if v["suppress"]:
        parts.append("What held it back most: " + ", ".join(v["suppress"]).lower() + ".")
    parts.append(f"The weakest part of development at the end was {v['weakest_dimension'].replace('_', ' ')}.")
    return " ".join(parts)
