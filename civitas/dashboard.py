"""Export a finished simulation as a single self-contained interactive HTML page.

The page embeds all data as JSON and draws its charts with Chart.js (loaded
from a CDN), so it can be opened from disk in any modern browser, or shared.
"""
from __future__ import annotations

import html
import json
import math
from collections import deque
from datetime import date
from typing import TYPE_CHECKING

from . import __version__, metrics
from .development import verdict_text
from .report import biography
from .resources import RULE_LABELS
from .traits import TRAIT_NAMES

if TYPE_CHECKING:
    from .simulation import Simulation


def _r(x, nd=3):
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return None
    return round(x, nd) if isinstance(x, float) else x


def _year(month: int) -> int:
    return month // 12 + 1


def build_payload(sim: "Simulation") -> dict:
    month, people = sim.month, sim.people
    summary = {k: _r(v) for k, v in sim.summary().items()}

    history = [{k: _r(v) for k, v in row.items()} for row in sim.history]

    init, final = sim.initial_snapshot, sim.snapshot_distributions()

    def hist(values, bins=20):
        counts = [0] * bins
        for v in values:
            counts[min(bins - 1, int((v + 1.0) / 2.0 * bins))] += 1
        n = max(1, len(values))
        return [round(c / n, 4) for c in counts]

    def pyramid(ages):
        bands = 19
        m, f = [0] * bands, [0] * bands
        for age, sex in ages:
            b = min(bands - 1, age // 5)
            (m if sex == "M" else f)[b] += 1
        return {"m": m, "f": f}

    distributions = {
        "lorenz_initial": metrics.lorenz_curve(init["wealth"]),
        "lorenz_final": metrics.lorenz_curve(final["wealth"]),
        "ideology_initial": hist(init["ideology"]),
        "ideology_final": hist(final["ideology"]),
        "pyramid_initial": pyramid(init["ages"]),
        "pyramid_final": pyramid(final["ages"]),
    }

    persons = []
    for p in people:
        age = p.age(month) if p.alive else (p.death_month - p.birth_month) / 12.0
        persons.append({
            "i": p.id, "n": p.name, "s": p.sex, "a": p.alive,
            "by": _year(p.birth_month) if p.birth_month >= 0 else None,
            "dy": _year(p.death_month) if not p.alive else None,
            "dc": p.death_cause or None,
            "age": int(age), "job": p.job_title, "dist": sim.district_name(p.district),
            "tr": [round(getattr(p, t), 2) for t in TRAIT_NAMES],
            "w": round(p.wealth), "ls": round(p.life_sat, 1), "rep": round(p.reputation, 2),
            "coop": round(p.cooperation_rate, 3), "int": p.coop_count + p.defect_count,
            "cr": p.crimes, "rec": p.record, "off": p.offices, "edu": p.education,
            "ide": round(p.ideology, 2), "con": round(p.conspiracy, 2), "vic": p.victimized,
            "reach": round(sum(t.strength for t in p.ties.values()), 1),
            "fam": {"m": p.mother_id, "f": p.father_id, "p": p.partner_id, "c": p.children},
            "bio": biography(sim, p),
            "ev": [[_year(m), int((m - p.birth_month) / 12), t] for m, t in p.events[-60:]],
            "tj": [[y, w, ls] for y, _, _, w, ls, _, _ in p.trajectory],
        })

    elections = [{
        "year": _year(e.month), "reason": e.reason, "turnout": round(e.turnout, 3),
        "winner": e.winner_name, "winner_id": e.winner_id, "ideology": round(e.winner_ideology, 2),
        "candidates": [{**c, "share": round(c["share"], 3)} for c in e.candidates],
    } for e in sim.gov.elections]

    chronicle = [{"year": _year(m), "month": m % 12 + 1, "cat": c, "text": t} for m, c, t in sim.chronicle_log]
    reg = sim.success_regression()
    mayor = sim.politics.mayor
    trajectory = _clean(sim.trajectory())
    trajectory["text"] = verdict_text(sim.trajectory())

    return {
        "meta": {
            "version": __version__, "seed": sim.cfg.seed, "years": len(sim.history),
            "founders": sim.cfg.initial_population, "generated": date.today().isoformat(),
            "districts": list(sim.cfg.district_names), "traits": list(TRAIT_NAMES),
            "mayor": mayor.id if mayor else None,
            "policy": {k: _r(v) for k, v in vars(sim.gov.policy).items()},
            "scenario": sim.cfg.scenario,
            "rule": RULE_LABELS.get(sim.gov.policy.commons_rule, sim.gov.policy.commons_rule),
            "shift": sim.cfg.traits.shift,
            "trajectory": trajectory,
        },
        "summary": summary,
        "history": history,
        "distributions": distributions,
        "regression": reg,
        "elections": elections,
        "chronicle": chronicle,
        "network": network_sample(sim),
        "people": persons,
    }


def _clean(obj):
    """Round floats and drop NaN/inf so the payload is valid JSON."""
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    return _r(obj, 4) if isinstance(obj, float) else obj


def network_sample(sim: "Simulation", size: int = 180, min_strength: float = 0.2) -> dict:
    """A connected slice of the friendship network, grown breadth-first from the
    best-connected adult so the picture shows real local structure."""
    month, people = sim.month, sim.people
    adults = [p for p in sim.alive if p.free and p.age(month) >= 16]
    if not adults:
        return {"nodes": [], "edges": []}
    start = max(adults, key=lambda p: sum(t.strength for t in p.ties.values() if t.strength >= min_strength))
    chosen, queue = {start.id}, deque([start.id])
    while queue and len(chosen) < size:
        pid = queue.popleft()
        strong = sorted(((t.strength, oid) for oid, t in people[pid].ties.items() if t.strength >= min_strength),
                        reverse=True)
        for _, oid in strong:
            q = people[oid]
            if oid not in chosen and q.alive and q.free and q.age(month) >= 16:
                chosen.add(oid)
                queue.append(oid)
                if len(chosen) >= size:
                    break
    ranks = metrics.percentile_ranks([people[i].wealth for i in chosen])
    nodes = [{"i": i, "n": people[i].name, "ide": round(people[i].ideology, 2),
              "con": round(people[i].conspiracy, 2), "rec": people[i].record > 0,
              "w": round(r, 3)} for i, r in zip(chosen, ranks)]
    edges = []
    for i in chosen:
        for j, t in people[i].ties.items():
            if i < j and j in chosen and t.strength >= min_strength:
                edges.append([i, j, round(t.strength, 2)])
    return {"nodes": nodes, "edges": edges}


def write_dashboard(sim: "Simulation", path: str) -> str:
    payload = json.dumps(build_payload(sim), separators=(",", ":"), allow_nan=False)
    payload = payload.replace("</", "<\\/")
    title = f"Civitas · seed {sim.cfg.seed}"
    page = TEMPLATE.replace("__TITLE__", html.escape(title)).replace("__DATA__", payload)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(page)
    return path


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>__TITLE__</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=Public+Sans:ital,wght@0,400;0,500;0,600;0,800;1,400&display=swap">
<style>
:root {
  color-scheme: light;
  --page: #f3f5f8; --surface: #fcfdfe; --surface-2: #eef1f5;
  --ink: #0f141a; --ink-2: #4a5360; --muted: #7d8692;
  --grid: #e1e5ea; --axis: #c3c9d1; --border: rgba(15, 20, 26, 0.10);
  --accent: #1f5fa8; --accent-soft: #e2ecf7;
  --s1: #2a78d6; --s2: #eb6834; --s3: #1baf7a; --s4: #eda100;
  --left: #2a78d6; --right: #e34948; --mid: #c9ccd1;
  --good: #0ca30c; --warning: #fab219; --critical: #d03b3b;
  --band: rgba(208, 59, 59, 0.09);
  --sans: "Public Sans", system-ui, -apple-system, "Segoe UI", sans-serif;
  --mono: "IBM Plex Mono", ui-monospace, "Cascadia Mono", Consolas, monospace;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --page: #0d1015; --surface: #151a21; --surface-2: #1c222b;
    --ink: #f1f4f8; --ink-2: #b9c1cc; --muted: #87909b;
    --grid: #262d36; --axis: #3a424d; --border: rgba(255, 255, 255, 0.10);
    --accent: #6aa6ea; --accent-soft: #1a2a3e;
    --s1: #3987e5; --s2: #d95926; --s3: #199e70; --s4: #c98500;
    --left: #3987e5; --right: #e66767; --mid: #4a4f57;
    --band: rgba(230, 103, 103, 0.13);
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --page: #0d1015; --surface: #151a21; --surface-2: #1c222b;
  --ink: #f1f4f8; --ink-2: #b9c1cc; --muted: #87909b;
  --grid: #262d36; --axis: #3a424d; --border: rgba(255, 255, 255, 0.10);
  --accent: #6aa6ea; --accent-soft: #1a2a3e;
  --s1: #3987e5; --s2: #d95926; --s3: #199e70; --s4: #c98500;
  --left: #3987e5; --right: #e66767; --mid: #4a4f57;
  --band: rgba(230, 103, 103, 0.13);
}
* { box-sizing: border-box; }
html, body { margin: 0; }
body {
  background: var(--page); color: var(--ink); font-family: var(--sans);
  font-size: 15px; line-height: 1.5; padding: 0 16px 48px;
}
.wrap { max-width: 1180px; margin: 0 auto; }
.mono { font-family: var(--mono); }
.num { font-variant-numeric: tabular-nums; }
h1, h2, h3 { text-wrap: balance; margin: 0; }
a { color: var(--accent); }
button, input, select { font: inherit; color: inherit; }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }

/* masthead */
.masthead { padding-block: 32px 20px; border-bottom: 2px solid var(--ink); display: grid; gap: 10px; }
.masthead .eyebrow { font-size: 12px; letter-spacing: 0.14em; text-transform: uppercase; color: var(--ink-2); }
.masthead h1 { font-size: clamp(34px, 6vw, 56px); font-weight: 800; letter-spacing: 0.08em; line-height: 1; }
.masthead p { margin: 0; color: var(--ink-2); max-width: 70ch; }
.meta { display: flex; flex-wrap: wrap; gap: 6px 20px; font-size: 13px; color: var(--ink-2); }
.meta b { color: var(--ink); font-weight: 600; }

/* trajectory verdict */
.verdict { margin-top: 20px; background: var(--surface); border: 1px solid var(--border); padding: 16px 18px;
  display: grid; gap: 10px; }
.verdict .head { display: flex; flex-wrap: wrap; align-items: center; gap: 10px 14px; }
.verdict .status { display: inline-flex; align-items: center; gap: 8px; font-weight: 800; font-size: 20px;
  letter-spacing: 0.02em; }
.verdict .status .mark { width: 14px; height: 14px; border-radius: 3px; flex: none; }
.verdict p { margin: 0; color: var(--ink-2); max-width: 90ch; }
.levers { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px 24px; }
@media (max-width: 820px) { .levers { grid-template-columns: minmax(0, 1fr); } }
.levers h3 { font-size: 12px; letter-spacing: 0.08em; text-transform: uppercase; color: var(--ink-2); margin: 0 0 4px; }
.levers ul { margin: 0; padding-left: 18px; font-size: 14px; display: grid; gap: 3px; }

/* KPI strip */
.kpis { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 1px; background: var(--border);
  border: 1px solid var(--border); margin-block: 20px; }
.kpi { background: var(--surface); padding: 14px 16px; display: grid; gap: 2px; align-content: start; }
.kpi .label { font-size: 12px; letter-spacing: 0.06em; text-transform: uppercase; color: var(--ink-2); }
.kpi .value { font-size: 28px; font-weight: 600; line-height: 1.2; }
.kpi .sub { font-size: 13px; color: var(--muted); }
@media (max-width: 820px) { .kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); } }

/* tabs */
.tabs { display: flex; gap: 4px; overflow-x: auto; overflow-y: hidden; border-bottom: 1px solid var(--axis); margin-bottom: 20px;
  position: sticky; top: env(safe-area-inset-top, 0px); background: var(--page); z-index: 5; }
.tab { background: none; border: 0; padding: 10px 14px; cursor: pointer; color: var(--ink-2); white-space: nowrap;
  border-bottom: 3px solid transparent; margin-bottom: -1px; font-weight: 500; }
.tab:hover { color: var(--ink); }
.tab[aria-selected="true"] { color: var(--ink); border-bottom-color: var(--accent); }
.panel { display: grid; gap: 20px; }
.grid2 { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 20px; }
@media (max-width: 820px) { .grid2 { grid-template-columns: minmax(0, 1fr); } }

.card { background: var(--surface); border: 1px solid var(--border); padding: 16px; display: grid; gap: 8px; min-width: 0; }
.card h3 { font-size: 15px; font-weight: 600; }
.card .note { font-size: 13px; color: var(--ink-2); margin: 0; max-width: 72ch; }
.chart { position: relative; height: 240px; }
.chart.tall { height: 320px; }
.lede { color: var(--ink-2); margin: 0; max-width: 75ch; }

/* tables */
.scroll { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: 14px; }
th { text-align: left; font-weight: 600; font-size: 12px; letter-spacing: 0.05em; text-transform: uppercase;
  color: var(--ink-2); border-bottom: 1px solid var(--axis); padding: 6px 10px 6px 0; white-space: nowrap; }
td { border-bottom: 1px solid var(--grid); padding: 7px 10px 7px 0; vertical-align: top; }
td.num, th.num { text-align: right; }

.chip { display: inline-flex; align-items: center; gap: 5px; font-size: 12px; padding: 1px 8px; border-radius: 999px;
  border: 1px solid var(--border); background: var(--surface-2); color: var(--ink-2); white-space: nowrap; }
.chip.crit { color: var(--critical); border-color: currentColor; background: transparent; }
.chip.good { color: var(--good); border-color: currentColor; background: transparent; }
.chip.accent { color: var(--accent); border-color: currentColor; background: transparent; }
.dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; flex: none; }

/* chronicle */
.chron { list-style: none; margin: 0; padding: 0; display: grid; gap: 0; max-height: 420px; overflow-y: auto; }
.chron li { display: grid; grid-template-columns: 76px minmax(0, 1fr); gap: 10px; padding: 7px 0; border-bottom: 1px solid var(--grid); font-size: 14px; }
.chron .when { color: var(--muted); font-size: 12px; padding-top: 2px; }
.chron .politics .what { color: var(--ink); }
.chron .economy .what, .chron .crime .what { color: var(--ink-2); }

/* people */
.people { display: grid; grid-template-columns: minmax(0, 330px) minmax(0, 1fr); gap: 20px; align-items: start; }
@media (max-width: 900px) { .people { grid-template-columns: minmax(0, 1fr); } }
.register { display: grid; gap: 10px; }
.controls { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.controls input[type="search"], .controls select { background: var(--surface); border: 1px solid var(--axis);
  padding: 7px 10px; border-radius: 4px; min-width: 0; }
.controls input[type="search"] { flex: 1 1 180px; }
.plist { list-style: none; margin: 0; padding: 0; max-height: 640px; overflow-y: auto; border: 1px solid var(--border); background: var(--surface); }
.plist button { width: 100%; text-align: left; background: none; border: 0; border-bottom: 1px solid var(--grid);
  padding: 8px 12px; cursor: pointer; display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 2px 8px; }
.plist button:hover { background: var(--surface-2); }
.plist button[aria-current="true"] { background: var(--accent-soft); }
.plist .pname { font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.plist .pid { color: var(--muted); font-size: 12px; }
.plist .pjob { color: var(--ink-2); font-size: 13px; grid-column: 1 / -1; }
.count { font-size: 13px; color: var(--muted); }

.dossier { display: grid; gap: 16px; }
.dossier header { display: grid; gap: 8px; }
.dossier h2 { font-size: 26px; font-weight: 800; }
.dossier h2 .mono { font-size: 16px; font-weight: 400; color: var(--muted); margin-left: 6px; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.family { font-size: 14px; color: var(--ink-2); display: flex; flex-wrap: wrap; gap: 4px 14px; }
.linkish { background: none; border: 0; padding: 0; color: var(--accent); cursor: pointer; text-decoration: underline;
  text-underline-offset: 2px; }
.traits { display: grid; gap: 6px; }
.trait { display: grid; grid-template-columns: 140px minmax(0, 1fr) 64px; gap: 10px; align-items: center; font-size: 14px; }
.track { position: relative; height: 10px; background: var(--surface-2); border-radius: 5px; }
.track::after { content: ""; position: absolute; left: 50%; top: -3px; bottom: -3px; width: 1px; background: var(--axis); }
.fill { position: absolute; left: 0; top: 0; bottom: 0; border-radius: 5px; background: var(--s1); }
.bio { margin: 0; max-width: 70ch; font-size: 15px; }
.timeline { list-style: none; margin: 0; padding: 0; font-size: 14px; max-height: 360px; overflow-y: auto; }
.timeline li { display: grid; grid-template-columns: 110px minmax(0, 1fr); gap: 10px; padding: 5px 0; border-bottom: 1px solid var(--grid); }
.timeline .when { color: var(--muted); font-size: 12px; padding-top: 2px; }
.minis { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.minis .chart { height: 160px; }
@media (max-width: 560px) { .minis { grid-template-columns: minmax(0, 1fr); } .trait { grid-template-columns: 110px minmax(0, 1fr) 56px; } }

/* network */
.netwrap { position: relative; height: 560px; border: 1px solid var(--border); background: var(--surface); }
.netwrap canvas { width: 100%; height: 100%; display: block; cursor: grab; }
.tooltip { position: absolute; pointer-events: none; background: var(--ink); color: var(--page); font-size: 13px;
  padding: 6px 9px; border-radius: 4px; white-space: nowrap; transform: translate(-50%, calc(-100% - 12px)); }
.legend { display: flex; flex-wrap: wrap; gap: 6px 16px; font-size: 13px; color: var(--ink-2); align-items: center; }
.ramp { width: 140px; height: 10px; border-radius: 5px; display: inline-block; }
footer { margin-top: 40px; padding-top: 14px; border-top: 1px solid var(--axis); font-size: 13px; color: var(--muted); }
@media (prefers-reduced-motion: reduce) { * { transition: none !important; animation: none !important; } }
</style>
</head>
<body>
<div class="wrap">
  <header class="masthead">
    <div class="eyebrow">Town registry · agent-based simulation</div>
    <h1>CIVITAS</h1>
    <p id="lede"></p>
    <div class="meta" id="meta"></div>
  </header>

  <section class="verdict" id="verdict" aria-label="Trajectory of the society"></section>

  <section class="kpis" id="kpis" aria-label="Key results"></section>

  <nav class="tabs" role="tablist" aria-label="Sections" id="tabs"></nav>

  <main>
    <section class="panel" id="overview" role="tabpanel">
      <div class="grid2">
        <div class="card"><h3>Population</h3><div class="chart"><canvas id="c-pop"></canvas></div></div>
        <div class="card"><h3>Births and deaths per year</h3><div class="chart"><canvas id="c-vital"></canvas></div></div>
        <div class="card"><h3>Average life satisfaction (0–10)</h3>
          <p class="note">A mean-reverting process: shocks such as job loss or bereavement fade as people adapt.</p>
          <div class="chart"><canvas id="c-ls"></canvas></div></div>
        <div class="card"><h3>Chronicle</h3><ul class="chron" id="chronicle"></ul></div>
      </div>
    </section>

    <section class="panel" id="development" role="tabpanel" hidden>
      <div class="grid2">
        <div class="card"><h3>Civitas Development Index</h3>
          <p class="note">Geometric mean of health, knowledge, living standard, equality, cohesion and sustainability (0–1), like the UN's Human Development Index.</p>
          <div class="chart"><canvas id="c-cdi"></canvas></div></div>
        <div class="card"><h3>The six dimensions of development</h3>
          <p class="note">A geometric mean punishes imbalance: the weakest dimension drags the index down most.</p>
          <div class="chart"><canvas id="c-dims"></canvas></div></div>
        <div class="card"><h3>What drove productivity over the run</h3>
          <p class="note">Cumulative contribution of each factor to productivity growth. Right = pushed the society forward; left = held it back.</p>
          <div class="chart"><canvas id="c-drivers"></canvas></div></div>
        <div class="card"><h3>Productivity growth per year</h3>
          <p class="note">Productivity multiplies every wage. It grows with education, cooperation and trust, and shrinks with crime, corruption and resource scarcity.</p>
          <div class="chart"><canvas id="c-growth"></canvas></div></div>
        <div class="card"><h3>Real median income per month</h3>
          <p class="note">Net income adjusted for the price of essentials.</p>
          <div class="chart"><canvas id="c-real"></canvas></div></div>
        <div class="card"><h3>Shared resource stock</h3>
          <p class="note" id="res-note"></p>
          <p class="note">The dashed line is the share of harvesters breaking their quota each year.</p>
          <div class="chart"><canvas id="c-res"></canvas></div></div>
        <div class="card"><h3>Resource income per adult ($ per month)</h3>
          <p class="note">What the shared resource provides to residents, after the allocation rule is applied.</p>
          <div class="chart"><canvas id="c-resinc"></canvas></div></div>
        <div class="card"><h3>Price of essentials</h3>
          <p class="note">Food and energy get dearer as the shared resource runs out (1 = normal, up to 1.6 when exhausted).</p>
          <div class="chart"><canvas id="c-col"></canvas></div></div>
      </div>
    </section>

    <section class="panel" id="economy" role="tabpanel" hidden>
      <div class="grid2">
        <div class="card"><h3>Unemployment rate</h3>
          <p class="note">Shaded years were in recession for at least six months.</p>
          <div class="chart"><canvas id="c-unemp"></canvas></div></div>
        <div class="card"><h3>Inequality (Gini coefficient)</h3>
          <p class="note">0 = everyone has the same; 1 = one person has everything.</p>
          <div class="chart"><canvas id="c-gini"></canvas></div></div>
        <div class="card"><h3>Lorenz curve of wealth</h3>
          <p class="note">The further the curve sags below the diagonal, the more unequal the society.</p>
          <div class="chart"><canvas id="c-lorenz"></canvas></div></div>
        <div class="card"><h3>What predicts a high income?</h3>
          <p class="note" id="reg-note"></p>
          <div class="chart"><canvas id="c-reg"></canvas></div></div>
        <div class="card"><h3>Median monthly net income</h3><div class="chart"><canvas id="c-income"></canvas></div></div>
        <div class="card"><h3>Relative poverty rate</h3>
          <p class="note">Share of adults living on under half the median income (OECD definition).</p>
          <div class="chart"><canvas id="c-pov"></canvas></div></div>
        <div class="card"><h3>Public debt as a share of annual labour income</h3>
          <p class="note">Below zero means the treasury holds a surplus.</p>
          <div class="chart"><canvas id="c-debt"></canvas></div></div>
        <div class="card"><h3>Income tax rate</h3><div class="chart"><canvas id="c-tax"></canvas></div></div>
      </div>
    </section>

    <section class="panel" id="justice" role="tabpanel" hidden>
      <div class="grid2">
        <div class="card"><h3>Crime per 1,000 residents per year</h3><div class="chart"><canvas id="c-crime"></canvas></div></div>
        <div class="card"><h3>Prisoners per 100,000 residents</h3><div class="chart"><canvas id="c-prison"></canvas></div></div>
        <div class="card"><h3>Law-enforcement staff per 1,000 residents</h3>
          <p class="note">Set by the mayor's budget. More officers raise the chance an offender is caught.</p>
          <div class="chart"><canvas id="c-police"></canvas></div></div>
        <div class="card"><h3>Arrests and bribes per year</h3><div class="chart"><canvas id="c-arrests"></canvas></div></div>
      </div>
    </section>

    <section class="panel" id="politics" role="tabpanel" hidden>
      <div class="grid2">
        <div class="card"><h3>Trust in institutions</h3>
          <p class="note">Dashed lines mark elections. Scandals and recessions knock trust down.</p>
          <div class="chart"><canvas id="c-trust"></canvas></div></div>
        <div class="card"><h3>Conspiracy believers</h3>
          <p class="note">Share of adults whose belief exceeds 0.5. Belief spreads person to person and through media, but only takes hold in the predisposed.</p>
          <div class="chart"><canvas id="c-consp"></canvas></div></div>
        <div class="card"><h3>Political polarisation</h3>
          <p class="note">Standard deviation of ideology on a scale from −1 (left) to +1 (right).</p>
          <div class="chart"><canvas id="c-polar"></canvas></div></div>
        <div class="card"><h3>Echo chambers</h3>
          <p class="note">Correlation of ideology between friends. 0 = friendships ignore politics.</p>
          <div class="chart"><canvas id="c-echo"></canvas></div></div>
        <div class="card"><h3>Distribution of ideology</h3><div class="chart"><canvas id="c-ideo"></canvas></div></div>
        <div class="card"><h3>Everyday cooperation rate</h3>
          <p class="note">Share of interactions in which people cooperated rather than exploited each other.</p>
          <div class="chart"><canvas id="c-coop"></canvas></div></div>
      </div>
      <div class="card"><h3>Elections</h3>
        <div class="scroll"><table id="elections"><thead><tr>
          <th>Year</th><th>Type</th><th>Winner</th><th class="num">Ideology</th><th class="num">Vote</th><th class="num">Turnout</th><th>Field</th>
        </tr></thead><tbody></tbody></table></div></div>
    </section>

    <section class="panel" id="network" role="tabpanel" hidden>
      <div class="card">
        <h3>A neighbourhood of the social network</h3>
        <p class="note" id="net-note"></p>
        <div class="controls">
          <label for="net-color">Colour by</label>
          <select id="net-color">
            <option value="ide">Ideology (left to right)</option>
            <option value="con">Conspiracy belief</option>
            <option value="rec">Criminal record</option>
          </select>
          <div class="legend" id="net-legend"></div>
        </div>
        <div class="netwrap" id="netwrap"><canvas id="net"></canvas><div class="tooltip" id="net-tip" hidden></div></div>
      </div>
    </section>

    <section class="panel" id="people" role="tabpanel" hidden>
      <div class="people">
        <div class="register">
          <div class="controls">
            <input type="search" id="person-search" placeholder="Search name or #id" aria-label="Search people">
            <select id="person-sort" aria-label="Sort people">
              <option value="reach">Most connected</option>
              <option value="w">Wealthiest</option>
              <option value="debt">Most indebted</option>
              <option value="rep">Most trusted</option>
              <option value="cr">Most offences</option>
              <option value="off">Mayors first</option>
              <option value="n">Name</option>
            </select>
          </div>
          <label class="count"><input type="checkbox" id="show-dead"> Include people who died</label>
          <div class="count" id="person-count"></div>
          <ul class="plist" id="plist"></ul>
        </div>
        <article class="card dossier" id="dossier" aria-live="polite"></article>
      </div>
    </section>

    <section class="panel" id="population" role="tabpanel" hidden>
      <div class="grid2">
        <div class="card"><h3>Age structure, Year 1</h3><div class="chart tall"><canvas id="c-pyr0"></canvas></div></div>
        <div class="card"><h3 id="pyr1-title">Age structure, final year</h3><div class="chart tall"><canvas id="c-pyr1"></canvas></div></div>
        <div class="card"><h3>Life expectancy at birth</h3>
          <p class="note">Period life table over a rolling ten-year window.</p>
          <div class="chart"><canvas id="c-e0"></canvas></div></div>
        <div class="card"><h3>Total fertility rate</h3>
          <p class="note">Children per woman at current age-specific rates. About 2.1 keeps a population stable.</p>
          <div class="chart"><canvas id="c-tfr"></canvas></div></div>
        <div class="card"><h3>Marriages and divorces per year</h3><div class="chart"><canvas id="c-marr"></canvas></div></div>
        <div class="card"><h3>Income segregation between districts</h3>
          <p class="note">Dissimilarity index between the poorest 40% and richest 20%.</p>
          <div class="chart"><canvas id="c-seg"></canvas></div></div>
      </div>
    </section>
  </main>

  <footer id="footer"></footer>
</div>

<script id="civitas-data" type="application/json">__DATA__</script>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.js"></script>
<script>
(function () {
"use strict";
const D = JSON.parse(document.getElementById("civitas-data").textContent);
const H = D.history, S = D.summary, M = D.meta;
const YEARS = H.map(r => r.year);
const PEOPLE = D.people;
const byId = new Map(PEOPLE.map(p => [p.i, p]));
const TRAIT_LABELS = ["Honesty", "Neuroticism", "Extraversion", "Agreeableness", "Conscientiousness", "Openness", "Intelligence"];

const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const el = id => document.getElementById(id);
const esc = s => String(s).replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const pct = (x, d = 0) => x == null ? "n/a" : (x * 100).toFixed(d) + "%";
const fix = (x, d = 2) => x == null ? "n/a" : Number(x).toFixed(d);
const money = x => x == null ? "n/a" : (x < 0 ? "−$" : "$") + Math.abs(Math.round(x)).toLocaleString("en-US");
const last = H[H.length - 1], first = H[0];
const mean = a => { const v = a.filter(x => x != null); return v.length ? v.reduce((s, x) => s + x, 0) / v.length : null; };

/* ---------------------------------------------------------------- header */
el("lede").textContent =
  `${S.people_ever_lived.toLocaleString()} simulated people were born, worked, befriended, cheated, voted, ` +
  `married and died over ${M.years} years. Each one's choices come from explicit equations of personality, trust and ` +
  `circumstance; nothing below was scripted.`;
el("meta").innerHTML = [
  ["Seed", M.seed], ["Founders", M.founders], ["Alive at end", S.final_population],
  ["Elections", S.elections], ["Scandals", S.scandals], ["Generated", M.generated]
].map(([k, v]) => `<span>${k} <b class="num">${esc(v)}</b></span>`).join("");
el("footer").innerHTML = `Civitas v${esc(M.version)}. Every figure on this page emerges from the agent-level equations ` +
  `documented in <span class="mono">docs/MODEL.md</span>. Re-run with <span class="mono">python main.py run --seed ${esc(M.seed)}</span> to reproduce it exactly.`;

/* ------------------------------------------------------------------ KPIs */
const peakU = H.reduce((a, r) => r.unemployment > a.unemployment ? r : a, H[0]);
const V = M.trajectory || {};
const kpis = [
  ["Development index", fix(S.cdi_end, 3), `from ${fix(S.cdi_start, 3)} · ${S.cdi_rate == null ? "" : (S.cdi_rate >= 0 ? "+" : "") + (S.cdi_rate * 100).toFixed(2) + "% a year"}`],
  ["Population", S.final_population.toLocaleString(), `from ${first.population} in Year 1`],
  ["Real median income", money(last.real_median_income), `${S.income_change == null ? "" : (S.income_change >= 0 ? "+" : "") + pct(S.income_change)} since Year 1 · productivity ×${fix(S.tfp_end, 2)}`],
  ["Shared resource", pct(S.commons_level), `of capacity at the end · low point ${pct(S.commons_min)}`],
  ["Wealth Gini", fix(S.gini_wealth), `richest 10% own ${pct(S.top10_wealth)}`],
  ["Unemployment", pct(S.unemployment, 1), `peak ${pct(peakU.unemployment, 1)} in Year ${peakU.year}`],
  ["Property crime", fix(S.property_crime_rate, 1), `per 1,000 a year · ${Math.round(S.incarceration_rate)} prisoners /100k`],
  ["Life expectancy", fix(S.life_expectancy, 1), `years · mobility slope ${S.mobility_rank_rank_slope == null ? "n/a" : fix(S.mobility_rank_rank_slope)}`],
];
const STATUS_COLOR = { "Rapid growth": "var(--good)", "Growth": "var(--good)", "Stagnation": "var(--warning)",
  "Decline": "#ec835a", "Collapse": "var(--critical)" };
if (V.status && V.cdi_start != null) {
  const drivers = V.drivers || [];
  const up = drivers.filter(d => d.total > 0.02).slice(0, 3), down = drivers.filter(d => d.total < -0.02).slice(0, 3);
  const li = d => `<li><b>${esc(d.label)}</b> (${d.total >= 0 ? "+" : ""}${(d.total * 100).toFixed(1)}%): ${esc(d.lever)}</li>`;
  const shift = Object.entries(M.shift || {}).map(([k, v]) => `${k} ${v >= 0 ? "+" : ""}${v} s.d.`).join(", ");
  el("verdict").innerHTML = `
    <div class="head"><span class="status"><span class="mark" style="background:${STATUS_COLOR[V.status] || "var(--muted)"}"></span>${esc(V.status)}</span>
      <span class="chip">Scenario: ${esc(M.scenario)}</span><span class="chip">${esc(M.rule)}</span>
      ${shift ? `<span class="chip">Population: ${esc(shift)}</span>` : ""}</div>
    <p>${esc(V.text)}</p>
    <div class="levers">
      <div><h3>Boost: these drove growth</h3><ul>${up.map(li).join("") || "<li>No factor added much growth.</li>"}</ul></div>
      <div><h3>Suppress or fix: these held it back</h3><ul>${down.map(li).join("") || "<li>No factor held growth back much.</li>"}</ul></div>
    </div>`;
} else {
  el("verdict").hidden = true;
}
el("kpis").innerHTML = kpis.map(([l, v, s]) =>
  `<div class="kpi"><span class="label">${l}</span><span class="value">${v}</span><span class="sub">${esc(s)}</span></div>`).join("");

/* ------------------------------------------------------------------ tabs */
const TABS = [["overview", "Overview"], ["development", "Development"], ["economy", "Economy"], ["justice", "Crime & justice"],
  ["politics", "Politics & beliefs"], ["network", "Network"], ["people", "People"], ["population", "Population"]];
el("tabs").innerHTML = TABS.map(([id, label]) =>
  `<button class="tab" role="tab" id="tab-${id}" aria-controls="${id}" data-tab="${id}">${label}</button>`).join("");
const built = new Set();
function show(id) {
  if (!TABS.some(t => t[0] === id)) id = "overview";
  for (const [t] of TABS) {
    el(t).hidden = t !== id;
    el("tab-" + t).setAttribute("aria-selected", String(t === id));
  }
  if (!built.has(id)) { built.add(id); BUILDERS[id](); }
  if (id === "network") drawNetwork();
}
el("tabs").addEventListener("click", e => {
  const b = e.target.closest("[data-tab]");
  if (b) { show(b.dataset.tab); history.replaceState(null, "", "#" + b.dataset.tab); }
});

/* ---------------------------------------------------------------- charts */
const charts = [];
function palette() {
  return { ink: css("--ink"), ink2: css("--ink-2"), muted: css("--muted"), grid: css("--grid"), axis: css("--axis"),
    s1: css("--s1"), s2: css("--s2"), s3: css("--s3"), s4: css("--s4"), band: css("--band"),
    left: css("--left"), right: css("--right"), mid: css("--mid"), surface: css("--surface"), crit: css("--critical") };
}
let C = palette();

const bandsPlugin = {
  id: "bands",
  beforeDatasetsDraw(chart, _args, opts) {
    if (!opts || !opts.years) return;
    const { ctx, chartArea: a, scales: { x } } = chart;
    ctx.save();
    ctx.fillStyle = C.band;
    for (const i of opts.years) {
      const x0 = x.getPixelForValue(i - 0.5), x1 = x.getPixelForValue(i + 0.5);
      ctx.fillRect(Math.max(a.left, x0), a.top, Math.min(a.right, x1) - Math.max(a.left, x0), a.bottom - a.top);
    }
    ctx.restore();
  }
};
const linesPlugin = {
  id: "vlines",
  afterDatasetsDraw(chart, _args, opts) {
    if (!opts || !opts.at) return;
    const { ctx, chartArea: a, scales: { x } } = chart;
    ctx.save();
    ctx.strokeStyle = C.muted; ctx.setLineDash([4, 4]); ctx.lineWidth = 1;
    for (const i of opts.at) {
      const px = x.getPixelForValue(i);
      ctx.beginPath(); ctx.moveTo(px, a.top); ctx.lineTo(px, a.bottom); ctx.stroke();
    }
    ctx.restore();
  }
};

function baseOptions(o = {}) {
  return {
    responsive: true, maintainAspectRatio: false, animation: false,
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: { display: !!o.legend, position: "top", align: "start",
        labels: { color: C.ink2, boxWidth: 10, boxHeight: 10, usePointStyle: true, pointStyle: "rectRounded" } },
      tooltip: { backgroundColor: C.ink, titleColor: C.surface, bodyColor: C.surface, padding: 8, boxPadding: 4,
        callbacks: o.tip ? { label: ctx => {
          const v = ctx.chart.options.indexAxis === "y" ? ctx.parsed.x : ctx.parsed.y;
          return `${ctx.dataset.label}: ${v == null ? "n/a" : o.tip(v, ctx)}`;
        } } : {} },
      bands: o.bands ? { years: o.bands } : false,
      vlines: o.vlines ? { at: o.vlines } : false,
    },
    scales: {
      x: { type: o.xType || "category", grid: { display: false }, border: { color: C.axis },
        ticks: { color: C.muted, maxTicksLimit: 10, maxRotation: 0, callback: o.xTick }, min: o.xMin, max: o.xMax,
        title: o.xTitle ? { display: true, text: o.xTitle, color: C.muted } : undefined, stacked: !!o.stacked },
      y: { grid: { color: C.grid }, border: { display: false }, min: o.yMin, max: o.yMax, beginAtZero: o.zero !== false,
        ticks: { color: C.muted, maxTicksLimit: 6, callback: o.yTick }, stacked: !!o.stacked,
        title: o.yTitle ? { display: true, text: o.yTitle, color: C.muted } : undefined },
    },
  };
}
function make(id, config) {
  const ctx = el(id);
  if (!ctx) return;
  const ch = new Chart(ctx, config);
  charts.push({ id, ch, config });
  return ch;
}
const yearLabels = YEARS.map(y => "Year " + y);
const series = key => H.map(r => r[key]);
function line(id, sets, o = {}) {
  return make(id, { type: "line", plugins: [bandsPlugin, linesPlugin], data: { labels: YEARS,
    datasets: sets.map(s => ({ label: s.label, data: s.data, borderColor: s.color, backgroundColor: s.fill || s.color,
      fill: !!s.fill, borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, tension: 0.25, spanGaps: true,
      borderDash: s.dash || [] })) },
    options: baseOptions({ ...o, legend: sets.length > 1, xTick: function (v) { return "Y" + this.getLabelForValue(v); } }) });
}
function bars(id, sets, o = {}) {
  return make(id, { type: "bar", data: { labels: o.labels || YEARS,
    datasets: sets.map(s => ({ label: s.label, data: s.data, backgroundColor: s.color, borderRadius: 3,
      borderSkipped: "start", categoryPercentage: 0.8, barPercentage: 0.9 })) },
    options: baseOptions({ ...o, legend: sets.length > 1,
      xTick: o.xTick || function (v) { return "Y" + this.getLabelForValue(v); } }) });
}
const recessionYears = H.map((r, i) => r.recession_months >= 6 ? i : null).filter(i => i != null);
const electionIdx = D.elections.map(e => YEARS.indexOf(e.year)).filter(i => i >= 0);
const withAlpha = (hex, a) => {
  const m = hex.match(/^#([0-9a-f]{6})$/i);
  if (!m) return hex;
  const n = parseInt(m[1], 16);
  return `rgba(${n >> 16}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
};

const BUILDERS = {
  overview() {
    line("c-pop", [{ label: "Population", data: series("population"), color: C.s1, fill: withAlpha(C.s1, 0.10) }],
      { zero: false, tip: v => Math.round(v) });
    bars("c-vital", [{ label: "Births", data: series("births"), color: C.s1 }, { label: "Deaths", data: series("deaths"), color: C.s2 }]);
    line("c-ls", [{ label: "Life satisfaction", data: series("life_satisfaction"), color: C.s3 }],
      { zero: false, yMin: 5, yMax: 9, tip: v => v.toFixed(2) });
    const chron = D.chronicle.filter(c => c.cat !== "debug");
    el("chronicle").innerHTML = chron.length ? chron.map(c =>
      `<li class="${esc(c.cat)}"><span class="when num">Y${c.year} · M${c.month}</span><span class="what">${esc(c.text)}</span></li>`).join("")
      : "<li><span></span><span>A quiet history: no recessions, scandals or dismissals.</span></li>";
  },
  development() {
    line("c-cdi", [{ label: "Development index", data: series("cdi"), color: C.s1, fill: withAlpha(C.s1, 0.10) }],
      { zero: false, tip: v => v.toFixed(3), bands: recessionYears });
    const dimNames = [["dim_health", "Health"], ["dim_knowledge", "Knowledge"], ["dim_living_standard", "Living standard"],
      ["dim_equality", "Equality"], ["dim_cohesion", "Cohesion"], ["dim_sustainability", "Sustainability"]];
    const dimColors = [C.s1, C.s2, C.s3, C.s4, css("--ink-2"), css("--right")];
    line("c-dims", dimNames.map(([k, l], i) => ({ label: l, data: series(k), color: dimColors[i] })),
      { yMin: 0, yMax: 1, tip: v => v.toFixed(3) });
    const drivers = (V.drivers || []).slice().sort((a, b) => b.total - a.total);
    make("c-drivers", { type: "bar", data: { labels: drivers.map(d => d.label),
      datasets: [{ label: "Contribution", data: drivers.map(d => d.total * 100), borderRadius: 3,
        backgroundColor: drivers.map(d => d.total >= 0 ? C.left : C.right) }] },
      options: { ...baseOptions({ tip: v => (v >= 0 ? "+" : "") + v.toFixed(1) + "%" }), indexAxis: "y",
        interaction: { mode: "index", axis: "y", intersect: false },
        scales: { x: { grid: { color: C.grid }, border: { display: false }, ticks: { color: C.muted, callback: v => v + "%" } },
                  y: { grid: { display: false }, border: { color: C.axis }, ticks: { color: C.ink2 } } } } });
    make("c-growth", { type: "bar", data: { labels: YEARS, datasets: [{ label: "Productivity growth",
      data: series("growth_rate").map(v => v == null ? null : v * 100), borderRadius: 2,
      backgroundColor: series("growth_rate").map(v => (v || 0) >= 0 ? C.left : C.right) }] },
      options: baseOptions({ zero: false, yTick: v => v + "%", tip: v => (v >= 0 ? "+" : "") + v.toFixed(2) + "%",
        xTick: function (v) { return "Y" + this.getLabelForValue(v); } }) });
    line("c-real", [{ label: "Real median income", data: series("real_median_income"), color: C.s1 }],
      { zero: false, yTick: v => money(v), tip: v => money(v), bands: recessionYears });
    el("res-note").textContent = `Share of the resource's carrying capacity left. Rule: ${M.rule}. It regrows fastest at half capacity; below that, harvests start to exceed regrowth.`;
    line("c-res", [{ label: "Resource stock (share of capacity)", data: series("commons_level"), color: C.s3, fill: withAlpha(C.s3, 0.12) },
      { label: "Harvesters breaking the quota", data: series("quota_cheat_rate"), color: C.s2, dash: [5, 4] }],
      { yMin: 0, yMax: 1, yTick: v => pct(v), tip: v => pct(v, 1) });
    line("c-resinc", [{ label: "Resource income per adult", data: series("commons_income_pc"), color: C.s3 }],
      { yTick: v => money(v), tip: v => money(v) });
    line("c-col", [{ label: "Price of essentials", data: series("cost_of_living"), color: C.s2 }],
      { zero: false, yMin: 0.9, tip: v => "×" + v.toFixed(2) });
  },
  economy() {
    line("c-unemp", [{ label: "Unemployment", data: series("unemployment"), color: C.s1 }],
      { bands: recessionYears, yTick: v => pct(v), tip: v => pct(v, 1) });
    line("c-gini", [{ label: "Wealth", data: series("gini_wealth"), color: C.s1 },
      { label: "Income", data: series("gini_income"), color: C.s2 }], { yMin: 0, yMax: 1, tip: v => v.toFixed(3) });
    const L0 = D.distributions.lorenz_initial, L1 = D.distributions.lorenz_final;
    make("c-lorenz", { type: "line", data: { datasets: [
      { label: "Perfect equality", data: [{ x: 0, y: 0 }, { x: 1, y: 1 }], borderColor: C.muted, borderDash: [4, 4], borderWidth: 1, pointRadius: 0 },
      { label: "Year 1", data: L0.map(([x, y]) => ({ x, y })), borderColor: C.axis, borderWidth: 2, pointRadius: 0, tension: 0.2 },
      { label: `Year ${last.year}`, data: L1.map(([x, y]) => ({ x, y })), borderColor: C.s1, borderWidth: 2, pointRadius: 0, tension: 0.2,
        fill: 0, backgroundColor: withAlpha(C.s1, 0.08) },
    ] }, options: baseOptions({ legend: true, xType: "linear", xMin: 0, xMax: 1, yMin: 0, yMax: 1,
      xTick: v => pct(v), yTick: v => pct(v), xTitle: "Share of adults, poorest first", yTitle: "Share of wealth",
      tip: v => pct(v, 1) }) });
    const reg = D.regression;
    if (reg) {
      const entries = Object.entries(reg.coefficients).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));
      el("reg-note").textContent = `Standardised regression of income rank for working adults aged 30–64 (n = ${reg.n}, ` +
        `R² = ${reg.r2.toFixed(2)}). Bars show how many standard deviations of income rank one standard deviation of each factor is worth. Nobody programmed these answers in.`;
      make("c-reg", { type: "bar", data: { labels: entries.map(e => e[0][0].toUpperCase() + e[0].slice(1)),
        datasets: [{ label: "Effect", data: entries.map(e => e[1]), borderRadius: 3,
          backgroundColor: entries.map(e => e[1] >= 0 ? C.left : C.right) }] },
        options: { ...baseOptions({ tip: v => (v >= 0 ? "+" : "") + v.toFixed(3) }), indexAxis: "y",
          interaction: { mode: "index", axis: "y", intersect: false },
          scales: { x: { grid: { color: C.grid }, border: { display: false }, ticks: { color: C.muted } },
                    y: { grid: { display: false }, border: { color: C.axis }, ticks: { color: C.ink2 } } } } });
    } else {
      el("reg-note").textContent = "Not enough working-age adults to estimate this.";
    }
    line("c-income", [{ label: "Median net income", data: series("median_income"), color: C.s1 }],
      { zero: false, yTick: v => money(v), tip: v => money(v), bands: recessionYears });
    line("c-pov", [{ label: "Poverty rate", data: series("poverty_rate"), color: C.s2 }], { yTick: v => pct(v), tip: v => pct(v, 1) });
    line("c-debt", [{ label: "Debt / income", data: series("gov_debt_ratio"), color: C.s1 }], { zero: false, tip: v => v.toFixed(2) });
    line("c-tax", [{ label: "Income tax rate", data: series("income_tax"), color: C.s1 }],
      { yMin: 0, yMax: 0.6, yTick: v => pct(v), tip: v => pct(v, 1), vlines: electionIdx });
  },
  justice() {
    line("c-crime", [{ label: "Property crime", data: series("property_crime_rate"), color: C.s1 },
      { label: "Fraud", data: series("fraud_rate"), color: C.s3 }, { label: "Assault", data: series("assault_rate"), color: C.s2 }],
      { tip: v => v.toFixed(1) });
    line("c-prison", [{ label: "Prisoners per 100k", data: series("incarceration_rate"), color: C.s1, fill: withAlpha(C.s1, 0.10) }],
      { tip: v => Math.round(v) });
    line("c-police", [{ label: "Officers per 1,000", data: series("police_per_1000"), color: C.s1 }],
      { tip: v => v.toFixed(1), vlines: electionIdx });
    bars("c-arrests", [{ label: "Arrests", data: series("arrests"), color: C.s1 }, { label: "Bribes taken", data: series("bribes"), color: C.s2 }]);
  },
  politics() {
    line("c-trust", [{ label: "Institutional trust", data: series("institutional_trust"), color: C.s1 }],
      { yMin: 0, yMax: 1, vlines: electionIdx, bands: recessionYears, tip: v => v.toFixed(3) });
    line("c-consp", [{ label: "Believers", data: series("conspiracy_share"), color: C.s2, fill: withAlpha(C.s2, 0.10) }],
      { yTick: v => pct(v), tip: v => pct(v, 1) });
    line("c-polar", [{ label: "Polarisation", data: series("polarization"), color: C.s1 }], { yMin: 0, tip: v => v.toFixed(3) });
    line("c-echo", [{ label: "Opinion assortativity", data: series("echo_chamber"), color: C.s3 }], { yMin: 0, yMax: 1, tip: v => v.toFixed(3) });
    const binLabels = Array.from({ length: 20 }, (_, i) => (-1 + i * 0.1 + 0.05).toFixed(2));
    bars("c-ideo", [{ label: "Year 1", data: D.distributions.ideology_initial, color: C.axis },
      { label: `Year ${last.year}`, data: D.distributions.ideology_final, color: C.s1 }],
      { labels: binLabels, yTick: v => pct(v), tip: v => pct(v, 1),
        xTick: function (v) { const l = Number(this.getLabelForValue(v)); return Math.abs(l + 0.95) < 1e-6 ? "Left" : Math.abs(l - 0.95) < 1e-6 ? "Right" : Math.abs(l - 0.05) < 1e-6 ? "Centre" : ""; } });
    line("c-coop", [{ label: "Cooperation", data: series("cooperation_rate"), color: C.s3 }],
      { zero: false, yTick: v => pct(v), tip: v => pct(v, 1) });
    el("elections").querySelector("tbody").innerHTML = D.elections.map(e => {
      const side = e.ideology < -0.15 ? "left" : e.ideology > 0.15 ? "right" : "centrist";
      const color = e.ideology < -0.15 ? "var(--left)" : e.ideology > 0.15 ? "var(--right)" : "var(--mid)";
      const win = e.candidates.find(c => c.id === e.winner_id);
      const field = e.candidates.map(c => `${esc(c.name)}${c.incumbent ? " (inc.)" : ""} ${pct(c.share)}`).join(" · ");
      return `<tr><td class="num">${e.year}</td><td>${esc(e.reason)}</td>
        <td><button class="linkish" data-person="${e.winner_id}">${esc(e.winner)}</button></td>
        <td class="num"><span class="chip"><span class="dot" style="background:${color}"></span>${side} ${e.ideology >= 0 ? "+" : ""}${e.ideology.toFixed(2)}</span></td>
        <td class="num">${win ? pct(win.share) : ""}</td><td class="num">${pct(e.turnout)}</td><td>${field}</td></tr>`;
    }).join("");
  },
  network() { buildNetwork(); },
  people() { buildPeople(); },
  population() {
    el("pyr1-title").textContent = `Age structure, Year ${last.year}`;
    const bandsLbl = Array.from({ length: 19 }, (_, i) => i === 18 ? "90+" : `${i * 5}–${i * 5 + 4}`).reverse();
    for (const [id, pyr] of [["c-pyr0", D.distributions.pyramid_initial], ["c-pyr1", D.distributions.pyramid_final]]) {
      make(id, { type: "bar", data: { labels: bandsLbl, datasets: [
        { label: "Men", data: pyr.m.slice().reverse().map(v => -v), backgroundColor: C.s1, borderRadius: 2 },
        { label: "Women", data: pyr.f.slice().reverse(), backgroundColor: C.s2, borderRadius: 2 }] },
        options: { ...baseOptions({ legend: true, stacked: true }), indexAxis: "y",
          interaction: { mode: "index", axis: "y", intersect: false },
          plugins: { ...baseOptions({ legend: true }).plugins,
            tooltip: { backgroundColor: C.ink, titleColor: C.surface, bodyColor: C.surface,
              callbacks: { label: ctx => `${ctx.dataset.label}: ${Math.abs(ctx.parsed.x)}` } } },
          scales: { x: { stacked: true, grid: { color: C.grid }, border: { display: false },
                         ticks: { color: C.muted, callback: v => Math.abs(v) } },
                    y: { stacked: true, grid: { display: false }, border: { color: C.axis },
                         ticks: { color: C.muted, autoSkip: true, maxTicksLimit: 10 } } } } });
    }
    line("c-e0", [{ label: "Life expectancy", data: series("life_expectancy"), color: C.s1 }], { zero: false, tip: v => v.toFixed(1) + " years" });
    line("c-tfr", [{ label: "Total fertility rate", data: series("tfr"), color: C.s2 }], { zero: false, tip: v => v.toFixed(2) });
    bars("c-marr", [{ label: "Marriages", data: series("partnerships"), color: C.s1 }, { label: "Divorces", data: series("divorces"), color: C.s2 }]);
    line("c-seg", [{ label: "Dissimilarity", data: series("segregation"), color: C.s1 }], { yMin: 0, yMax: 1, tip: v => v.toFixed(3) });
  },
};

/* --------------------------------------------------------------- people */
let current = null;
function statusChips(p) {
  const out = [];
  out.push(p.a ? `<span class="chip good">Alive, age ${p.age}</span>` : `<span class="chip">Died Year ${p.dy}, age ${p.age}</span>`);
  out.push(`<span class="chip">${esc(p.job)}</span>`, `<span class="chip">${esc(p.dist)}</span>`);
  if (p.off) out.push(`<span class="chip accent">Mayor ×${p.off}</span>`);
  if (M.mayor === p.i) out.push(`<span class="chip accent">Current mayor</span>`);
  if (p.rec) out.push(`<span class="chip crit">Convicted ×${p.rec}</span>`);
  return out.join("");
}
function personLink(id, label) {
  const q = byId.get(id);
  return q ? `<span>${label}: <button class="linkish" data-person="${id}">${esc(q.n)}</button></span>` : "";
}
const miniCharts = [];
function renderDossier(id) {
  const p = byId.get(id);
  if (!p) return;
  current = id;
  const kids = p.fam.c.filter(c => byId.has(c)).map(c =>
    `<button class="linkish" data-person="${c}">${esc(byId.get(c).n.split(" ")[0])}</button>`);
  const fam = [personLink(p.fam.m, "Mother"), personLink(p.fam.f, "Other parent"), personLink(p.fam.p, "Partner"),
    kids.length ? `<span>Children: ${kids.join(", ")}</span>` : ""].filter(Boolean).join("");
  const traits = p.tr.map((z, k) => {
    const q = 0.5 * (1 + erf(z / Math.SQRT2));
    return `<div class="trait"><span>${TRAIT_LABELS[k]}</span><span class="track" role="img" aria-label="${TRAIT_LABELS[k]} percentile ${Math.round(q * 100)}">
      <span class="fill" style="width:${(q * 100).toFixed(1)}%"></span></span><span class="num">${ordinal(Math.round(q * 100))}</span></div>`;
  }).join("");
  el("dossier").innerHTML = `
    <header>
      <h2>Citizen ${esc(p.n)}</h2>
      <div class="chips">${statusChips(p)}</div>
      <div class="family">${fam || "No recorded family."}</div>
    </header>
    <section class="traits" aria-label="Personality and ability, as population percentiles">${traits}</section>
    <p class="bio">${esc(p.bio)}</p>
    <div class="minis">
      <div><h3>Net worth</h3><div class="chart"><canvas id="m-w"></canvas></div></div>
      <div><h3>Life satisfaction</h3><div class="chart"><canvas id="m-ls"></canvas></div></div>
    </div>
    <div><h3>Timeline</h3><ul class="timeline">${p.ev.map(([y, a, t]) =>
      `<li><span class="when num">Year ${y} · age ${a}</span><span>${esc(t)}</span></li>`).join("") || "<li><span></span><span>No recorded events.</span></li>"}</ul></div>`;
  while (miniCharts.length) miniCharts.pop().destroy();
  const labels = p.tj.map(t => t[0]);
  const mk = (cid, data, color, o) => miniCharts.push(new Chart(el(cid), { type: "line",
    data: { labels, datasets: [{ label: o.label, data, borderColor: color, backgroundColor: withAlpha(color, 0.10), fill: true,
      borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, tension: 0.25 }] },
    options: baseOptions({ zero: o.zero, yMin: o.yMin, yMax: o.yMax, yTick: o.yTick, tip: o.tip,
      xTick: function (v) { return "Y" + this.getLabelForValue(v); } }) }));
  mk("m-w", p.tj.map(t => t[1]), C.s1, { label: "Net worth", zero: false, yTick: v => money(v), tip: v => money(v) });
  mk("m-ls", p.tj.map(t => t[2]), C.s3, { label: "Life satisfaction", yMin: 0, yMax: 10, tip: v => v.toFixed(1) });
  document.querySelectorAll("#plist button").forEach(b => b.setAttribute("aria-current", String(Number(b.dataset.id) === id)));
}
function ordinal(n) { const s = ["th", "st", "nd", "rd"], v = n % 100; return n + (s[(v - 20) % 10] || s[v] || s[0]); }
function erf(x) { // Abramowitz-Stegun 7.1.26
  const t = 1 / (1 + 0.3275911 * Math.abs(x));
  const y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-x * x);
  return x >= 0 ? y : -y;
}
function buildPeople() {
  const render = () => {
    const q = el("person-search").value.trim().toLowerCase().replace(/^#/, "");
    const dead = el("show-dead").checked, sort = el("person-sort").value;
    let list = PEOPLE.filter(p => (dead || p.a) && (!q || p.n.toLowerCase().includes(q) || String(p.i) === q));
    const key = { reach: p => -p.reach, w: p => -p.w, debt: p => p.w, rep: p => -(p.int >= 100 ? p.rep : 0),
      cr: p => -p.cr, off: p => -p.off * 1e6 - p.reach, n: null }[sort];
    list.sort(key ? (a, b) => key(a) - key(b) : (a, b) => a.n.localeCompare(b.n));
    el("person-count").textContent = `${list.length.toLocaleString()} ${list.length === 1 ? "person" : "people"}` +
      (list.length > 250 ? " · showing the first 250" : "");
    el("plist").innerHTML = list.slice(0, 250).map(p =>
      `<li><button data-id="${p.i}" aria-current="${p.i === current}"><span class="pname">${esc(p.n)}</span>
       <span class="pid num"></span><span class="pjob">${p.a ? esc(p.job) + " · " + p.age : "Died Year " + p.dy}</span></button></li>`).join("");
  };
  el("person-search").addEventListener("input", render);
  el("person-sort").addEventListener("change", render);
  el("show-dead").addEventListener("change", render);
  el("plist").addEventListener("click", e => { const b = e.target.closest("button[data-id]"); if (b) renderDossier(Number(b.dataset.id)); });
  render();
  if (current == null) {
    const start = M.mayor != null ? M.mayor : PEOPLE.filter(p => p.a).sort((a, b) => b.reach - a.reach)[0].i;
    renderDossier(start);
  }
}
document.addEventListener("click", e => {
  const b = e.target.closest("[data-person]");
  if (!b) return;
  const id = Number(b.dataset.person);
  if (!built.has("people")) { current = id; }
  show("people"); renderDossier(id);
  history.replaceState(null, "", "#people");
  el("dossier").scrollIntoView({ behavior: "smooth", block: "start" });
});

/* -------------------------------------------------------------- network */
const NET = D.network;
let net = null;
function buildNetwork() {
  const n = NET.nodes.length;
  el("net-note").textContent = `${n} residents and the ${NET.edges.length} strong friendships among them (closeness ≥ 0.2), ` +
    `grown outward from the best-connected adult. Node size shows wealth rank. Hover a person to see who they are; click to open their dossier.`;
  const idx = new Map(NET.nodes.map((d, i) => [d.i, i]));
  const nodes = NET.nodes.map((d, i) => ({ ...d, x: Math.cos(i * 2.4) * (50 + i), y: Math.sin(i * 2.4) * (50 + i), vx: 0, vy: 0 }));
  const edges = NET.edges.map(([a, b, w]) => [idx.get(a), idx.get(b), w]).filter(e => e[0] != null && e[1] != null);
  // Fruchterman-Reingold style layout, run once up front
  const k = 30;
  for (let it = 0; it < 350; it++) {
    const temp = 8 * (1 - it / 350) + 0.5;
    for (const a of nodes) { a.fx = -a.x * 0.01; a.fy = -a.y * 0.01; }
    for (let i = 0; i < nodes.length; i++) for (let j = i + 1; j < nodes.length; j++) {
      const a = nodes[i], b = nodes[j]; let dx = a.x - b.x, dy = a.y - b.y; let d2 = dx * dx + dy * dy + 0.01;
      const f = (k * k) / d2; a.fx += dx * f; a.fy += dy * f; b.fx -= dx * f; b.fy -= dy * f;
    }
    for (const [i, j, w] of edges) {
      const a = nodes[i], b = nodes[j]; const dx = a.x - b.x, dy = a.y - b.y; const d = Math.sqrt(dx * dx + dy * dy) + 0.01;
      const f = (d * d / k) * (0.3 + w) / d; a.fx -= dx * f * 0.05; a.fy -= dy * f * 0.05; b.fx += dx * f * 0.05; b.fy += dy * f * 0.05;
    }
    for (const a of nodes) {
      const m = Math.sqrt(a.fx * a.fx + a.fy * a.fy) + 1e-9, s = Math.min(m, temp) / m;
      a.x += a.fx * s; a.y += a.fy * s;
    }
  }
  net = { nodes, edges, hover: null };
  const canvas = el("net");
  canvas.addEventListener("mousemove", ev => {
    const hit = pick(ev);
    if (hit !== net.hover) { net.hover = hit; drawNetwork(); }
    const tip = el("net-tip");
    if (hit == null) { tip.hidden = true; return; }
    const d = nodes[hit], r = canvas.getBoundingClientRect();
    tip.hidden = false;
    tip.style.left = (ev.clientX - r.left) + "px"; tip.style.top = (ev.clientY - r.top) + "px";
    tip.textContent = `${d.n} · ideology ${d.ide >= 0 ? "+" : ""}${d.ide.toFixed(2)} · belief ${d.con.toFixed(2)}${d.rec ? " · record" : ""}`;
  });
  canvas.addEventListener("mouseleave", () => { net.hover = null; el("net-tip").hidden = true; drawNetwork(); });
  canvas.addEventListener("click", ev => {
    const hit = pick(ev);
    if (hit == null) return;
    show("people"); renderDossier(nodes[hit].i); history.replaceState(null, "", "#people");
  });
  el("net-color").addEventListener("change", drawNetwork);
  window.addEventListener("resize", () => { if (!el("network").hidden) drawNetwork(); });
}
function nodeColor(d, mode) {
  if (mode === "rec") return d.rec ? C.crit : C.mid;
  if (mode === "con") return mix(C.mid, C.s2, Math.min(1, d.con / 0.8));
  return d.ide < 0 ? mix(C.mid, C.left, Math.min(1, -d.ide / 0.8)) : mix(C.mid, C.right, Math.min(1, d.ide / 0.8));
}
function hexRgb(h) { const m = h.match(/^#([0-9a-f]{6})$/i); const n = m ? parseInt(m[1], 16) : 0x888888; return [n >> 16, (n >> 8) & 255, n & 255]; }
function mix(a, b, t) { const x = hexRgb(a), y = hexRgb(b); return `rgb(${x.map((v, i) => Math.round(v + (y[i] - v) * t)).join(",")})`; }
function transform() {
  const canvas = el("net"), w = canvas.clientWidth, h = canvas.clientHeight;
  let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
  for (const d of net.nodes) { x0 = Math.min(x0, d.x); x1 = Math.max(x1, d.x); y0 = Math.min(y0, d.y); y1 = Math.max(y1, d.y); }
  const s = Math.min((w - 40) / Math.max(1, x1 - x0), (h - 40) / Math.max(1, y1 - y0));
  return { s, ox: w / 2 - (x0 + x1) / 2 * s, oy: h / 2 - (y0 + y1) / 2 * s };
}
function pick(ev) {
  const r = el("net").getBoundingClientRect(), t = transform();
  const mx = ev.clientX - r.left, my = ev.clientY - r.top;
  let best = null, bd = 144;
  net.nodes.forEach((d, i) => { const dx = d.x * t.s + t.ox - mx, dy = d.y * t.s + t.oy - my, q = dx * dx + dy * dy; if (q < bd) { bd = q; best = i; } });
  return best;
}
function drawNetwork() {
  if (!net) return;
  const canvas = el("net"), dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth, h = canvas.clientHeight;
  canvas.width = w * dpr; canvas.height = h * dpr;
  const ctx = canvas.getContext("2d"); ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  const t = transform(), mode = el("net-color").value;
  const nb = new Set();
  if (net.hover != null) for (const [i, j] of net.edges) { if (i === net.hover) nb.add(j); if (j === net.hover) nb.add(i); }
  for (const [i, j, wt] of net.edges) {
    const a = net.nodes[i], b = net.nodes[j];
    const on = net.hover != null && (i === net.hover || j === net.hover);
    ctx.strokeStyle = on ? C.ink : C.axis; ctx.globalAlpha = on ? 0.9 : 0.25 + 0.5 * wt; ctx.lineWidth = on ? 1.5 : 0.6 + wt;
    ctx.beginPath(); ctx.moveTo(a.x * t.s + t.ox, a.y * t.s + t.oy); ctx.lineTo(b.x * t.s + t.ox, b.y * t.s + t.oy); ctx.stroke();
  }
  ctx.globalAlpha = 1;
  net.nodes.forEach((d, i) => {
    const r = 3 + 5 * d.w, x = d.x * t.s + t.ox, y = d.y * t.s + t.oy;
    const dim = net.hover != null && i !== net.hover && !nb.has(i);
    ctx.globalAlpha = dim ? 0.35 : 1;
    ctx.beginPath(); ctx.arc(x, y, r + 1.5, 0, Math.PI * 2); ctx.fillStyle = C.surface; ctx.fill();
    ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fillStyle = nodeColor(d, mode); ctx.fill();
    if (i === net.hover) { ctx.lineWidth = 2; ctx.strokeStyle = C.ink; ctx.stroke(); }
  });
  ctx.globalAlpha = 1;
  const legend = {
    ide: `<span>Left</span><span class="ramp" style="background:linear-gradient(90deg, ${C.left}, ${C.mid}, ${C.right})"></span><span>Right</span>`,
    con: `<span>Sceptic</span><span class="ramp" style="background:linear-gradient(90deg, ${C.mid}, ${C.s2})"></span><span>Believer</span>`,
    rec: `<span class="chip"><span class="dot" style="background:${C.crit}"></span>Criminal record</span><span class="chip"><span class="dot" style="background:${C.mid}"></span>No record</span>`,
  }[mode];
  el("net-legend").innerHTML = legend;
}

/* ---------------------------------------------------------- theme change */
function rebuild() {
  C = palette();
  for (const c of charts) c.ch.destroy();
  charts.length = 0;
  const open = [...built]; built.clear();
  const visible = TABS.find(([id]) => !el(id).hidden)[0];
  for (const id of open) { if (id !== "people" && id !== "network") { built.add(id); BUILDERS[id](); } else built.add(id); }
  if (current != null && built.has("people")) renderDossier(current);
  if (visible === "network") drawNetwork();
}
if (window.matchMedia) window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", rebuild);
new MutationObserver(rebuild).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });

if (typeof Chart === "undefined") {
  el("overview").insertAdjacentHTML("afterbegin",
    '<p class="lede">Charts need the Chart.js library, which loads from cdn.jsdelivr.net. Connect to the internet and reload to see them; the People register below works offline.</p>');
  window.Chart = function () { return { destroy() {} }; };
} else {
  Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
  Chart.defaults.color = C.ink2;
}
show((location.hash || "#overview").slice(1));
})();
</script>
</body>
</html>
"""
