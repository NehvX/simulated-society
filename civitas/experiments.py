"""Controlled policy experiments.

One run of an agent-based model is a single anecdote. To compare policies
properly we:

* hold each regime's policy fixed (`lock_policy`), so elections cannot change it;
* keep every regime solvent: the flat income tax follows a fiscal reaction
  function that balances the budget, so the tax a regime *needs* is an outcome
  rather than a free choice (otherwise a low-tax regime could look good simply
  by running up unlimited debt);
* run every scenario on the same random seeds (common random numbers, which
  reduces the variance of the comparison);
* report means with 95% confidence intervals from Student's t distribution.
"""
from __future__ import annotations

import csv
import json
import math
import os
import statistics
import time
from concurrent.futures import ProcessPoolExecutor

from .config import SimConfig
from .simulation import Simulation

# Each scenario is a set of dotted-path overrides applied to the default config.
SCENARIOS: dict[str, dict] = {
    "baseline": {},
    "laissez-faire": {
        "policy.top_tax": 0.0, "policy.welfare_floor": 450.0, "policy.child_benefit": 50.0,
        "policy.education_subsidy": 0.1, "policy.mental_health_pc": 5.0, "policy.public_services_pc": 230.0,
        "policy.unemployment_replacement": 0.3, "policy.pension_rate": 0.30, "policy.inheritance_tax": 0.0,
    },
    "nordic": {
        "policy.top_tax": 0.15, "policy.welfare_floor": 1300.0, "policy.child_benefit": 300.0,
        "policy.education_subsidy": 0.95, "policy.mental_health_pc": 30.0, "policy.public_services_pc": 400.0,
        "policy.unemployment_replacement": 0.7, "policy.pension_rate": 0.55, "policy.inheritance_tax": 0.30,
    },
    "tough on crime": {
        "policy.police_per_1000": 10.0, "crime.custody_property": 0.6,
        "crime.theft_sentence": 10.0, "crime.assault_sentence": 24.0,
    },
    "universal basic income": {
        "policy.ubi": 700.0, "policy.welfare_floor": 0.0, "policy.unemployment_replacement": 0.2,
    },
}

METRICS = [
    ("gini_wealth", "Wealth Gini", "{:.3f}"),
    ("poverty_rate", "Poverty rate", "{:.1%}"),
    ("mobility_rank_rank_slope", "Rank-rank slope", "{:.3f}"),
    ("unemployment", "Unemployment", "{:.1%}"),
    ("property_crime_rate", "Property crime /1k", "{:.1f}"),
    ("incarceration_rate", "Prisoners /100k", "{:.0f}"),
    ("life_satisfaction", "Life satisfaction", "{:.2f}"),
    ("institutional_trust", "Institutional trust", "{:.3f}"),
    ("conspiracy_share", "Conspiracy belief", "{:.1%}"),
    ("life_expectancy", "Life expectancy", "{:.1f}"),
    ("income_tax", "Tax rate needed", "{:.1%}"),
    ("gov_debt_ratio", "Public debt / income", "{:.2f}"),
]

# two-sided 95% Student-t critical values by degrees of freedom
T95 = {1: 12.71, 2: 4.30, 3: 3.18, 4: 2.78, 5: 2.57, 6: 2.45, 7: 2.36, 8: 2.31, 9: 2.26, 10: 2.23,
       12: 2.18, 15: 2.13, 20: 2.09, 30: 2.04}


def t_critical(df: int) -> float:
    if df <= 0:
        return float("nan")
    keys = sorted(T95)
    for k in keys:
        if df <= k:
            return T95[k]
    return 1.96


def mean_ci(values: list[float]) -> tuple[float, float]:
    vals = [v for v in values if v is not None and not (isinstance(v, float) and math.isnan(v))]
    if not vals:
        return float("nan"), float("nan")
    m = statistics.fmean(vals)
    if len(vals) < 2:
        return m, float("nan")
    return m, t_critical(len(vals) - 1) * statistics.stdev(vals) / math.sqrt(len(vals))


def _run_one(job: tuple[str, dict, int, int, int]) -> dict:
    name, overrides, seed, years, population = job
    cfg = SimConfig(seed=seed, years=years, initial_population=population, verbose=False, lock_policy=True)
    for key, value in overrides.items():
        cfg.override(key, value)
    sim = Simulation(cfg).run()
    return {"scenario": name, "seed": seed, **sim.summary()}


def run_experiment(scenarios: dict[str, dict] | None = None, seeds: int = 4, years: int = 40,
                   population: int = 500, workers: int | None = None, out_dir: str | None = None) -> list[dict]:
    scenarios = scenarios or SCENARIOS
    jobs = [(name, ov, 1000 + s, years, population) for name, ov in scenarios.items() for s in range(seeds)]
    workers = workers or max(1, (os.cpu_count() or 2) - 1)
    print(f"Running {len(jobs)} simulations ({len(scenarios)} scenarios x {seeds} seeds, {years} years, "
          f"{population} founders) on {workers} processes...")
    start = time.time()
    results = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for i, res in enumerate(pool.map(_run_one, jobs), 1):
            results.append(res)
            print(f"  [{i:>3}/{len(jobs)}] {res['scenario']:<24s} seed {res['seed']}  "
                  f"({time.time() - start:5.0f}s elapsed)")
    table = summarise(results, list(scenarios))
    print()
    print(table)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, "experiment_runs.csv"), "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(results[0]))
            writer.writeheader()
            writer.writerows(results)
        with open(os.path.join(out_dir, "experiment_summary.md"), "w", encoding="utf-8") as fh:
            fh.write(table + "\n")
        with open(os.path.join(out_dir, "experiment_runs.json"), "w", encoding="utf-8") as fh:
            json.dump({"scenarios": scenarios, "runs": results}, fh, indent=1, default=str)
        print(f"\nSaved runs and summary to {out_dir}/")
    return results


def summarise(results: list[dict], order: list[str]) -> str:
    """Markdown table: mean +/- 95% CI half-width for each scenario and metric."""
    header = "| Scenario | " + " | ".join(label for _, label, _ in METRICS) + " |"
    lines = [header, "|" + "---|" * (len(METRICS) + 1)]
    for name in order:
        runs = [r for r in results if r["scenario"] == name]
        cells = []
        for key, _, fmt in METRICS:
            m, ci = mean_ci([r.get(key) for r in runs])
            cell = fmt.format(m) if not math.isnan(m) else "n/a"
            if not math.isnan(ci):
                cell += " ± " + fmt.format(ci).lstrip("$")
            cells.append(cell)
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    lines.append(f"\n(mean ± 95% CI over {len(results) // max(1, len(order))} seeds per scenario; "
                 f"policies held fixed)")
    if order and order[0] in {r["scenario"] for r in results}:
        lines.append("\n" + paired_summary(results, order))
    return "\n".join(lines)


def paired_summary(results: list[dict], order: list[str]) -> str:
    """Difference from the first scenario, paired by seed. Because every regime
    ran on the same seeds, differencing within a seed cancels much of the
    run-to-run noise (a paired t-test). '*' marks a 95% CI that excludes zero."""
    base_name = order[0]
    base = {r["seed"]: r for r in results if r["scenario"] == base_name}
    header = f"| Change vs {base_name} (paired) | " + " | ".join(label for _, label, _ in METRICS) + " |"
    lines = [header, "|" + "---|" * (len(METRICS) + 1)]
    for name in order[1:]:
        runs = [r for r in results if r["scenario"] == name and r["seed"] in base]
        cells = []
        for key, _, fmt in METRICS:
            diffs = [r[key] - base[r["seed"]][key] for r in runs
                     if r.get(key) is not None and base[r["seed"]].get(key) is not None]
            m, ci = mean_ci(diffs)
            if math.isnan(m):
                cells.append("n/a")
                continue
            star = "*" if not math.isnan(ci) and abs(m) > ci else ""
            sign = "+" if m >= 0 else "−"
            cells.append(f"{sign}{fmt.format(abs(m))} ± {fmt.format(ci)}{star}" if not math.isnan(ci)
                         else f"{sign}{fmt.format(abs(m))}")
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    lines.append("\n(* = the 95% confidence interval of the paired difference excludes zero)")
    return "\n".join(lines)
