"""Two built-in studies.

1. Lever analysis ("what makes a society boom or collapse?"). Each factor is
   pushed from a low to a high setting while everything else stays at baseline,
   on the same random seeds. The paired difference (high - low) in the
   development index, growth, income, inequality and resources shows which
   parts of society to boost and which to suppress. This is a one-at-a-time
   sensitivity analysis; the results are shown as a "tornado" chart.

2. Commons study, which answers the research question: how do individual
   behaviour and resource-allocation rules affect inequality and resource
   availability over time? Every combination of 5 allocation rules x 3
   behaviour profiles runs on the same seeds, and the time paths of the resource
   stock, the income it provides and inequality are compared.

Both run in parallel on all CPU cores and write Markdown, JSON and a
self-contained HTML report.
"""
from __future__ import annotations

import html
import json
import math
import os
import time
from concurrent.futures import ProcessPoolExecutor

from .config import SimConfig
from .experiments import mean_ci
from .resources import RULE_LABELS, RULES
from .simulation import Simulation

SERIES = ("cdi", "commons_level", "commons_income_pc", "gini_income", "gini_wealth",
          "real_median_income", "population", "poverty_rate", "tfp", "quota_cheat_rate")

# (name, what it is, low setting, high setting); a setting is (parameter overrides, trait shift)
LEVERS = [
    ("Education subsidy", "share of university tuition paid by the state: 10% vs 95%",
     ({"policy.education_subsidy": 0.10}, {}), ({"policy.education_subsidy": 0.95}, {})),
    ("Public services", "schools, healthcare, infrastructure: $200 vs $450 per resident per month",
     ({"policy.public_services_pc": 200.0}, {}), ({"policy.public_services_pc": 450.0}, {})),
    ("Policing", "law-enforcement staff: 2.5 vs 10 per 1,000 residents",
     ({"policy.police_per_1000": 2.5}, {}), ({"policy.police_per_1000": 10.0}, {})),
    ("Welfare floor", "guaranteed minimum income: $450 vs $1,400 a month",
     ({"policy.welfare_floor": 450.0}, {}), ({"policy.welfare_floor": 1400.0}, {})),
    ("Mental-health care", "budget: $5 vs $35 per resident per month",
     ({"policy.mental_health_pc": 5.0}, {}), ({"policy.mental_health_pc": 35.0}, {})),
    ("Top income tax", "extra rate on incomes above $10k/month: 0% vs 25%",
     ({"policy.top_tax": 0.0}, {}), ({"policy.top_tax": 0.25}, {})),
    ("Honesty of citizens", "population average: -0.5 vs +0.5 s.d. (inherited)",
     ({}, {"honesty": -0.5}), ({}, {"honesty": 0.5})),
    ("Agreeableness", "population average: -0.5 vs +0.5 s.d.",
     ({}, {"agreeableness": -0.5}), ({}, {"agreeableness": 0.5})),
    ("Conscientiousness", "population average: -0.5 vs +0.5 s.d.",
     ({}, {"conscientiousness": -0.5}), ({}, {"conscientiousness": 0.5})),
    ("Curiosity (openness)", "population average: -0.5 vs +0.5 s.d.",
     ({}, {"openness": -0.5}), ({}, {"openness": 0.5})),
    ("Resource regrowth", "natural regeneration of the commons: 2.5% vs 6% a month",
     ({"commons.regen_rate": 0.025}, {}), ({"commons.regen_rate": 0.06}, {})),
    ("Resource governance", "open access vs community quota with equal shares",
     ({"policy.commons_rule": "open_access"}, {}), ({"policy.commons_rule": "equal_shares"}, {})),
]

PROFILES = {
    "cooperative": {"honesty": 0.6, "agreeableness": 0.6},
    "average": {},
    "selfish": {"honesty": -0.6, "agreeableness": -0.6},
}


# ================================================================== runner
def _run(job: tuple) -> dict:
    label, overrides, shift, seed, years, population = job
    cfg = SimConfig(seed=seed, years=years, initial_population=population, verbose=False, lock_policy=True)
    for key, value in overrides.items():
        cfg.override(key, value)
    cfg.traits.shift = dict(shift)
    sim = Simulation(cfg).run()
    return {"label": label, "seed": seed, "summary": sim.summary(),
            "series": {k: [r.get(k) for r in sim.history] for k in SERIES}}


def _run_all(jobs: list[tuple], workers: int | None) -> list[dict]:
    workers = workers or max(1, (os.cpu_count() or 2) - 1)
    print(f"Running {len(jobs)} simulations on {workers} processes...")
    start, results = time.time(), []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for i, res in enumerate(pool.map(_run, jobs), 1):
            results.append(res)
            print(f"  [{i:>3}/{len(jobs)}] {res['label']:<44s} seed {res['seed']}  ({time.time() - start:5.0f}s)")
    return results


def _paired(results: list[dict], a: str, b: str, key: str) -> tuple[float, float]:
    """Mean and 95% CI of (b - a) for `key`, paired by seed."""
    ra = {r["seed"]: r["summary"].get(key) for r in results if r["label"] == a}
    diffs = [r["summary"][key] - ra[r["seed"]] for r in results
             if r["label"] == b and r["summary"].get(key) is not None and ra.get(r["seed"]) is not None]
    return mean_ci(diffs)


def _avg(results: list[dict], label: str, key: str) -> float:
    return mean_ci([r["summary"].get(key) for r in results if r["label"] == label])[0]


def _avg_series(results: list[dict], label: str, key: str) -> list[float]:
    runs = [r["series"][key] for r in results if r["label"] == label]
    n = min(len(s) for s in runs)
    return [round(sum(s[i] for s in runs if s[i] is not None) / len(runs), 4) for i in range(n)]


def _fmt(m: float, ci: float, fmt: str) -> str:
    if math.isnan(m):
        return "n/a"
    star = "*" if not math.isnan(ci) and abs(m) > ci else ""
    sign = "+" if m >= 0 else "−"
    body = f"{sign}{fmt.format(abs(m))}"
    return body + (f" ± {fmt.format(ci)}{star}" if not math.isnan(ci) else "")


# ========================================================== lever analysis
def run_levers(seeds: int = 3, years: int = 30, population: int = 400, workers: int | None = None,
               out_dir: str = os.path.join("out", "levers")) -> list[dict]:
    jobs = [("baseline", {}, {}, 2000 + s, years, population) for s in range(seeds)]
    for name, _, low, high in LEVERS:
        for side, (ov, sh) in (("low", low), ("high", high)):
            jobs += [(f"{name} | {side}", ov, sh, 2000 + s, years, population) for s in range(seeds)]
    results = _run_all(jobs, workers)

    rows = []
    for name, what, _, _ in LEVERS:
        lo, hi = f"{name} | low", f"{name} | high"
        rows.append({
            "name": name, "what": what,
            "d_cdi": _paired(results, lo, hi, "cdi_end"),
            "d_rate": _paired(results, lo, hi, "cdi_rate"),
            "d_income": _paired(results, lo, hi, "income_change"),
            "d_gini": _paired(results, lo, hi, "gini_wealth"),
            "d_resource": _paired(results, lo, hi, "commons_level"),
            "d_poverty": _paired(results, lo, hi, "poverty_rate"),
            "collapse_low": _avg(results, lo, "collapse"), "collapse_high": _avg(results, hi, "collapse"),
            "cdi_low": _avg(results, lo, "cdi_end"), "cdi_high": _avg(results, hi, "cdi_end"),
        })
    rows.sort(key=lambda r: -abs(r["d_cdi"][0]))
    base_cdi = _avg(results, "baseline", "cdi_end")

    lines = [f"# Lever analysis: what makes the society boom or collapse?\n",
             f"{seeds} seeds x {years} years x {population} founders per setting; policy held fixed, budget balanced. "
             f"Baseline development index at the end: {base_cdi:.3f}.\n",
             "Each row pushes one factor from its low to its high setting. Changes are high minus low, paired "
             "by seed (mean ± 95% CI; * = CI excludes zero).\n",
             "| Factor | Low → high | Δ Development index | Δ growth (%/yr) | Δ real income | Δ wealth Gini | "
             "Δ resource level | Δ poverty | Collapse rate (low / high) | Advice |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        m, ci = r["d_cdi"]
        advice = ("boost" if m > 0 else "suppress") if not math.isnan(ci) and abs(m) > ci else "no clear effect"
        lines.append(
            f"| {r['name']} | {r['what']} | {_fmt(*r['d_cdi'], '{:.3f}')} | "
            f"{_fmt(r['d_rate'][0] * 100, r['d_rate'][1] * 100, '{:.2f}')} | {_fmt(*r['d_income'], '{:.0%}')} | "
            f"{_fmt(*r['d_gini'], '{:.3f}')} | {_fmt(*r['d_resource'], '{:.0%}')} | {_fmt(*r['d_poverty'], '{:.1%}')} | "
            f"{r['collapse_low']:.0%} / {r['collapse_high']:.0%} | {advice} |")
    table = "\n".join(lines)
    print("\n" + table)

    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "levers.md"), "w", encoding="utf-8") as fh:
        fh.write(table + "\n")
    with open(os.path.join(out_dir, "levers.json"), "w", encoding="utf-8") as fh:
        json.dump({"rows": rows, "runs": [{k: v for k, v in r.items()} for r in results]}, fh, default=str)
    charts = [
        {"title": "Effect on the development index (high minus low)",
         "note": "Bars to the right: pushing this factor up makes the society more developed. "
                 "Hover for the 95% confidence interval.",
         "type": "tornado", "labels": [r["name"] for r in rows],
         "values": [round(r["d_cdi"][0], 4) for r in rows], "ci": [round(r["d_cdi"][1], 4) for r in rows]},
        {"title": "Effect on wealth inequality (Gini, high minus low)",
         "note": "Bars to the right: more unequal.", "type": "tornado", "labels": [r["name"] for r in rows],
         "values": [round(r["d_gini"][0], 4) for r in rows], "ci": [round(r["d_gini"][1], 4) for r in rows],
         "invert": True},
        {"title": "Effect on the shared resource (share of capacity, high minus low)",
         "note": "Bars to the right: a healthier resource stock at the end.", "type": "tornado",
         "labels": [r["name"] for r in rows], "values": [round(r["d_resource"][0], 4) for r in rows],
         "ci": [round(r["d_resource"][1], 4) for r in rows]},
    ]
    write_report(os.path.join(out_dir, "levers_report.html"), "Civitas levers",
                 "What makes a society boom or collapse?",
                 f"Each factor was pushed from a low to a high setting with everything else at baseline, on the same "
                 f"{seeds} random seeds ({years} years, {population} founders). The charts rank the factors by how "
                 f"much they move the development index.", charts, table)
    print(f"\nSaved {out_dir}/levers.md and levers_report.html")
    return results


# ============================================================ commons study
def run_commons_study(seeds: int = 3, years: int = 40, population: int = 400, workers: int | None = None,
                      regen: float = 0.035, out_dir: str = os.path.join("out", "commons")) -> list[dict]:
    jobs = []
    for rule in RULES:
        for profile, shift in PROFILES.items():
            overrides = {"policy.commons_rule": rule, "commons.regen_rate": regen}
            jobs += [(f"{rule} | {profile}", overrides, shift, 3000 + s, years, population) for s in range(seeds)]
    results = _run_all(jobs, workers)

    metrics = [("commons_level", "Resource left (share of capacity)", "{:.0%}"),
               ("commons_min", "Lowest point", "{:.0%}"),
               ("commons_income_pc", "Resource income per adult ($/month)", "${:,.0f}"),
               ("gini_income", "Income Gini", "{:.3f}"),
               ("gini_wealth", "Wealth Gini", "{:.3f}"),
               ("poverty_rate", "Poverty", "{:.1%}"),
               ("cdi_end", "Development index", "{:.3f}"),
               ("collapse", "Collapse rate", "{:.0%}")]
    lines = [f"# Research question: how do individual behaviour and resource-allocation rules affect inequality "
             f"and resource availability over time?\n",
             f"{len(RULES)} rules x {len(PROFILES)} behaviour profiles x {seeds} seeds; {years} years, "
             f"{population} founders, a fragile resource (regrowth {regen:.1%} a month). Values are means at the "
             f"end of the run (± 95% CI).\n",
             "| Rule | Behaviour | " + " | ".join(label for _, label, _ in metrics) + " |",
             "|---|---|" + "---|" * len(metrics)]
    points = []
    for rule in RULES:
        for profile in PROFILES:
            label = f"{rule} | {profile}"
            cells = []
            for key, _, fmt in metrics:
                m, ci = mean_ci([r["summary"].get(key) for r in results if r["label"] == label])
                cells.append("n/a" if math.isnan(m) else fmt.format(m) + ("" if math.isnan(ci) else " ± " + fmt.format(ci)))
            lines.append(f"| {RULE_LABELS[rule]} | {profile} | " + " | ".join(cells) + " |")
            points.append({"rule": rule, "profile": profile,
                           "x": round(_avg(results, label, "gini_income"), 4),
                           "y": round(_avg(results, label, "commons_level"), 4)})
    table = "\n".join(lines)
    print("\n" + table)

    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "commons_study.md"), "w", encoding="utf-8") as fh:
        fh.write(table + "\n")
    with open(os.path.join(out_dir, "commons_study.json"), "w", encoding="utf-8") as fh:
        json.dump({"regen": regen, "runs": results}, fh, default=str)

    charts = [{"title": "Inequality vs resources left, every rule and behaviour",
               "note": "Each point is one rule and behaviour profile (mean over seeds). The top-left corner is the "
                       "goal: plenty of resource left and low inequality.",
               "type": "scatter", "points": points, "rules": list(RULES), "rule_labels": RULE_LABELS}]
    for key, title, note in (
            ("commons_level", "Resource stock (share of capacity)", "How much of the shared resource is left."),
            ("commons_income_pc", "Resource income per adult ($/month)", "Resource availability to residents."),
            ("gini_income", "Income inequality (Gini)", "Including each person's share of the resource.")):
        for profile in PROFILES:
            charts.append({"title": f"{title}: {profile} population", "note": note, "type": "lines",
                           "labels": list(range(1, years + 1)),
                           "series": [{"label": RULE_LABELS[rule],
                                       "data": _avg_series(results, f"{rule} | {profile}", key)} for rule in RULES],
                           "percent": key == "commons_level", "money": key == "commons_income_pc"})
    write_report(os.path.join(out_dir, "commons_report.html"), "Civitas commons study",
                 "Behaviour, rules and the shared resource",
                 "How do individual behaviour and resource-allocation rules affect inequality and resource "
                 f"availability over time? Each line averages {seeds} runs. 'Cooperative' and 'selfish' populations "
                 "are 0.6 s.d. above or below average in honesty and agreeableness.", charts, table)
    print(f"\nSaved {out_dir}/commons_study.md and commons_report.html")
    return results


# ============================================================= HTML report
def write_report(path: str, title: str, heading: str, intro: str, charts: list[dict], table_md: str) -> None:
    page = (REPORT_TEMPLATE.replace("__TITLE__", html.escape(title)).replace("__HEADING__", html.escape(heading))
            .replace("__INTRO__", html.escape(intro)).replace("__TABLE__", _md_table_to_html(table_md))
            .replace("__CHARTS__", json.dumps(charts).replace("</", "<\\/")))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(page)


def _md_table_to_html(md: str) -> str:
    rows = [l for l in md.splitlines() if l.startswith("|") and not l.startswith("|---")]
    if not rows:
        return ""
    cells = [[html.escape(c.strip()) for c in r.strip("|").split("|")] for r in rows]
    head = "".join(f"<th>{c}</th>" for c in cells[0])
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in cells[1:])
    return f'<div class="scroll"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


REPORT_TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Public+Sans:wght@400;600;800&display=swap">
<style>
:root { color-scheme: light; --page:#f3f5f8; --surface:#fcfdfe; --ink:#0f141a; --ink-2:#4a5360; --muted:#7d8692;
  --grid:#e1e5ea; --axis:#c3c9d1; --border:rgba(15,20,26,.1);
  --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a; --s4:#eda100; --s5:#e87ba4; --good:#2a78d6; --bad:#e34948; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { color-scheme: dark; --page:#0d1015;
  --surface:#151a21; --ink:#f1f4f8; --ink-2:#b9c1cc; --muted:#87909b; --grid:#262d36; --axis:#3a424d;
  --border:rgba(255,255,255,.1); --s1:#3987e5; --s2:#d95926; --s3:#199e70; --s4:#c98500; --s5:#d55181;
  --good:#3987e5; --bad:#e66767; } }
:root[data-theme="dark"] { color-scheme: dark; --page:#0d1015; --surface:#151a21; --ink:#f1f4f8; --ink-2:#b9c1cc;
  --muted:#87909b; --grid:#262d36; --axis:#3a424d; --border:rgba(255,255,255,.1); --s1:#3987e5; --s2:#d95926;
  --s3:#199e70; --s4:#c98500; --s5:#d55181; --good:#3987e5; --bad:#e66767; }
* { box-sizing: border-box; }
body { margin: 0; background: var(--page); color: var(--ink); font: 15px/1.5 "Public Sans", system-ui, sans-serif;
  padding: 0 16px 48px; }
.wrap { max-width: 1180px; margin: 0 auto; display: grid; gap: 20px; }
header { padding-block: 28px 16px; border-bottom: 2px solid var(--ink); }
header .eyebrow { font-size: 12px; letter-spacing: .14em; text-transform: uppercase; color: var(--ink-2); }
h1 { margin: 4px 0 8px; font-size: clamp(26px, 4vw, 38px); font-weight: 800; text-wrap: balance; }
header p { margin: 0; color: var(--ink-2); max-width: 75ch; }
.grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 20px; }
@media (max-width: 820px) { .grid { grid-template-columns: minmax(0, 1fr); } }
.card { background: var(--surface); border: 1px solid var(--border); padding: 16px; display: grid; gap: 8px; min-width: 0; }
.card.wide { grid-column: 1 / -1; }
.card h2 { margin: 0; font-size: 15px; font-weight: 600; }
.card p { margin: 0; font-size: 13px; color: var(--ink-2); }
.chart { position: relative; height: 300px; }
.scroll { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: 13px; font-variant-numeric: tabular-nums; }
th { text-align: left; font-size: 12px; color: var(--ink-2); border-bottom: 1px solid var(--axis); padding: 6px 10px 6px 0; }
td { border-bottom: 1px solid var(--grid); padding: 6px 10px 6px 0; vertical-align: top; }
</style></head>
<body><div class="wrap">
<header><div class="eyebrow">Civitas study</div><h1>__HEADING__</h1><p>__INTRO__</p></header>
<section class="grid" id="charts"></section>
<section class="card wide"><h2>Full results</h2>__TABLE__</section>
</div>
<script id="charts-data" type="application/json">__CHARTS__</script>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.js"></script>
<script>
(function () {
const CH = JSON.parse(document.getElementById("charts-data").textContent);
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const esc = s => String(s).replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const host = document.getElementById("charts");
let made = [];
function draw() {
  made.forEach(c => c.destroy()); made = []; host.innerHTML = "";
  if (typeof Chart === "undefined") { host.innerHTML = "<p>Charts need Chart.js from cdn.jsdelivr.net; the table below works offline.</p>"; return; }
  const C = { ink: css("--ink"), ink2: css("--ink-2"), muted: css("--muted"), grid: css("--grid"), axis: css("--axis"),
    good: css("--good"), bad: css("--bad"), s: [css("--s1"), css("--s2"), css("--s3"), css("--s4"), css("--s5")], surface: css("--surface") };
  Chart.defaults.color = C.ink2; Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
  const tip = { backgroundColor: C.ink, titleColor: C.surface, bodyColor: C.surface, padding: 8 };
  CH.forEach((c, i) => {
    const card = document.createElement("div");
    card.className = "card" + (c.type === "tornado" || c.type === "scatter" ? " wide" : "");
    const h = c.type === "tornado" ? Math.max(260, 34 * c.labels.length) : 300;
    card.innerHTML = `<h2>${esc(c.title)}</h2><p>${esc(c.note || "")}</p><div class="chart" style="height:${h}px"><canvas id="ch${i}"></canvas></div>`;
    host.appendChild(card);
    const ctx = document.getElementById("ch" + i);
    const scales = (xo, yo) => ({ x: { grid: { color: C.grid }, border: { display: false }, ticks: { color: C.muted }, ...xo },
                                  y: { grid: { color: C.grid }, border: { display: false }, ticks: { color: C.muted }, ...yo } });
    if (c.type === "tornado") {
      const good = v => (c.invert ? v < 0 : v > 0);
      made.push(new Chart(ctx, { type: "bar", data: { labels: c.labels, datasets: [{ label: "Change", data: c.values,
        backgroundColor: c.values.map(v => good(v) ? C.good : C.bad), borderRadius: 3 }] },
        options: { indexAxis: "y", responsive: true, maintainAspectRatio: false, animation: false,
          plugins: { legend: { display: false }, tooltip: { ...tip, callbacks: { label: t =>
            `${t.parsed.x >= 0 ? "+" : ""}${t.parsed.x.toFixed(3)}  (95% CI ± ${Number(c.ci[t.dataIndex]).toFixed(3)})` } } },
          scales: scales({}, { grid: { display: false }, ticks: { color: C.ink2 } }) } }));
    } else if (c.type === "scatter") {
      const shapes = { cooperative: "circle", average: "rectRot", selfish: "triangle" };
      made.push(new Chart(ctx, { type: "scatter", data: { datasets: c.rules.map((r, k) => ({ label: c.rule_labels[r],
        data: c.points.filter(p => p.rule === r).map(p => ({ x: p.x, y: p.y, profile: p.profile })),
        backgroundColor: C.s[k % 5], borderColor: C.surface, borderWidth: 2, pointRadius: 8, pointHoverRadius: 10,
        pointStyle: c.points.filter(p => p.rule === r).map(p => shapes[p.profile]) })) },
        options: { responsive: true, maintainAspectRatio: false, animation: false,
          plugins: { legend: { position: "top", align: "start", labels: { usePointStyle: true, boxWidth: 8 } },
            tooltip: { ...tip, callbacks: { label: t => `${t.dataset.label}, ${t.raw.profile}: Gini ${t.parsed.x.toFixed(3)}, resource ${(t.parsed.y * 100).toFixed(0)}%` } } },
          scales: scales({ title: { display: true, text: "Income Gini (inequality)", color: C.muted } },
                         { min: 0, max: 1, title: { display: true, text: "Resource left (share of capacity)", color: C.muted },
                           ticks: { color: C.muted, callback: v => Math.round(v * 100) + "%" } }) } }));
    } else {
      const fmt = v => c.percent ? Math.round(v * 100) + "%" : c.money ? "$" + Math.round(v) : Number(v).toFixed(3);
      made.push(new Chart(ctx, { type: "line", data: { labels: c.labels.map(y => "Y" + y), datasets: c.series.map((s, k) => ({
        label: s.label, data: s.data, borderColor: C.s[k % 5], backgroundColor: C.s[k % 5], borderWidth: 2,
        pointRadius: 0, pointHoverRadius: 4, tension: .25 })) },
        options: { responsive: true, maintainAspectRatio: false, animation: false, interaction: { mode: "index", intersect: false },
          plugins: { legend: { position: "top", align: "start", labels: { boxWidth: 10, boxHeight: 10 } },
            tooltip: { ...tip, callbacks: { label: t => `${t.dataset.label}: ${fmt(t.parsed.y)}` } } },
          scales: scales({ grid: { display: false }, ticks: { color: C.muted, maxTicksLimit: 10 } },
                         { beginAtZero: true, max: c.percent ? 1 : undefined, ticks: { color: C.muted, callback: fmt } }) } }));
    }
  });
}
draw();
if (window.matchMedia) matchMedia("(prefers-color-scheme: dark)").addEventListener("change", draw);
new MutationObserver(draw).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
})();
</script>
</body></html>
"""
