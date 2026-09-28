"""Human-readable output: the end-of-run report, leaderboards, and dossiers
with auto-generated life stories."""
from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from .mathutil import normal_cdf
from .network import social_support
from .person import Person
from .traits import TRAIT_NAMES, describe

if TYPE_CHECKING:
    from .simulation import Simulation

WIDTH = 78


def rule(title: str = "", char: str = "=") -> str:
    if not title:
        return char * WIDTH
    pad = max(2, WIDTH - len(title) - 2)
    return f"{char * (pad // 2)} {title} {char * (pad - pad // 2)}"


def money(x: float) -> str:
    return f"-${-x:,.0f}" if x < 0 else f"${x:,.0f}"


def bar(value: float, lo: float, hi: float, width: int = 20) -> str:
    frac = 0.0 if hi == lo else max(0.0, min(1.0, (value - lo) / (hi - lo)))
    n = round(frac * width)
    return "#" * n + "." * (width - n)


def year_of(month: int) -> int:
    return month // 12 + 1


# ============================================================ the big report
def print_report(sim: "Simulation") -> None:
    h, s = sim.history, sim.summary()
    first, last = h[0], h[-1]
    print()
    print(rule(f"CIVITAS: {s['years']}-YEAR REPORT (seed {sim.cfg.seed})"))
    print(f"{s['people_ever_lived']} people lived in the simulation; {s['final_population']} are alive at the end.")
    print()
    print(rule("How the society changed", "-"))
    rows = [
        ("Population", "population", "{:.0f}"),
        ("Unemployment rate", "unemployment", "{:.1%}"),
        ("Median net income / month", "median_income", "${:,.0f}"),
        ("Wealth Gini (0 = equal)", "gini_wealth", "{:.2f}"),
        ("Top 10% share of wealth", "top10_wealth", "{:.0%}"),
        ("Relative poverty rate", "poverty_rate", "{:.1%}"),
        ("Property crimes per 1,000", "property_crime_rate", "{:.1f}"),
        ("Assaults per 1,000", "assault_rate", "{:.1f}"),
        ("Prisoners per 100,000", "incarceration_rate", "{:.0f}"),
        ("Trust in institutions (0-1)", "institutional_trust", "{:.2f}"),
        ("Political polarisation (s.d.)", "polarization", "{:.2f}"),
        ("Echo chambers (opinion assortativity)", "echo_chamber", "{:.2f}"),
        ("Conspiracy believers", "conspiracy_share", "{:.1%}"),
        ("Income segregation (dissimilarity)", "segregation", "{:.2f}"),
        ("Life satisfaction (0-10)", "life_satisfaction", "{:.2f}"),
    ]
    print(f"{'':38s} {'Year 1':>12s} {'Year ' + str(last['year']):>12s}")
    for label, key, fmt in rows:
        print(f"{label:38s} {fmt.format(first[key]):>12s} {fmt.format(last[key]):>12s}")
    print()
    le, tfr = s["life_expectancy"], s["tfr"]
    print(f"Life expectancy at birth (period life table): {le:.1f} years   Total fertility rate: {tfr:.2f}")
    rr = s["mobility_rank_rank_slope"]
    if rr is not None:
        print(f"Intergenerational mobility: rank-rank slope {rr:.2f} (n={s['mobility_n']}; "
              f"USA ~0.34, Denmark ~0.18, 0 = parents' rank irrelevant)")
    rec = s["recidivism"]
    if rec is not None:
        print(f"Recidivism: {rec:.0%} of released prisoners reconvicted within 3 years")
    print(f"Everyday cooperation rate: {s['cooperation_rate']:.1%} of interactions")
    print_trajectory(sim)

    print()
    print(rule("Elections", "-"))
    for e in sim.gov.elections:
        field = ", ".join(f"{c['name']} {c['share']:.0%}{'*' if c['incumbent'] else ''}" for c in e.candidates)
        print(f"Year {year_of(e.month):>2} {e.reason:<9s} winner {e.winner_name:<18s} ({e.winner_ideology:+.2f}) "
              f"turnout {e.turnout:.0%} | {field}")
    print("(* = incumbent; ideology -1 left ... +1 right)")

    notable = [(m, t) for m, c, t in sim.chronicle_log if c in ("economy", "crime", "politics")
               and not t.startswith(tuple(e.winner_name for e in sim.gov.elections))]
    if notable:
        print()
        print(rule("Chronicle", "-"))
        for m, t in notable[:40]:
            print(f"Year {year_of(m):>2}: {t}")

    print_leaderboards(sim)
    print_success_analysis(sim)


def print_trajectory(sim: "Simulation") -> None:
    """Growth or decline, what drove it, and which real-world levers it points to."""
    from .development import DIMENSIONS, verdict_text
    from .resources import RULE_LABELS
    v = sim.trajectory()
    if "cdi_start" not in v:
        return
    h = sim.history
    h0 = h[v["start_index"]]
    print()
    print(rule(f"Trajectory of the society: {v['status'].upper()}", "-"))
    print(f"Scenario: {sim.cfg.scenario}   |   Resource rule: {RULE_LABELS.get(sim.gov.policy.commons_rule)}")
    for line in _wrap(verdict_text(v), WIDTH - 2, ""):
        print(line)
    print()
    print(f"{'Development index and its dimensions':38s} {'Year ' + str(h0['year']):>12s} "
          f"{'Year ' + str(h[-1]['year']):>12s}")
    print(f"{'  Civitas Development Index':38s} {v['cdi_start']:>12.3f} {v['cdi_end']:>12.3f}")
    for d in DIMENSIONS:
        print(f"{'  ' + d.replace('_', ' ').capitalize():38s} {v['dims_start'][d]:>12.3f} {v['dims_end'][d]:>12.3f}")
    print(f"{'  Productivity (founding = 1.00)':38s} {h0['tfp']:>12.2f} {h[-1]['tfp']:>12.2f}")
    print(f"{'  Real median income / month':38s} {money(h0['real_median_income']):>12s} "
          f"{money(h[-1]['real_median_income']):>12s}")
    print(f"{'  Resource stock (share of capacity)':38s} {h0['commons_level']:>12.0%} {h[-1]['commons_level']:>12.0%}")
    print(f"{'  Price of essentials (normal = 1)':38s} {h0['cost_of_living']:>12.2f} {h[-1]['cost_of_living']:>12.2f}")
    print()
    print("What moved productivity over the whole run (cumulative contribution to its log-growth):")
    top = max((abs(d["total"]) for d in v["drivers"]), default=1.0) or 1.0
    for d in v["drivers"]:
        bar_len = round(abs(d["total"]) / top * 20)
        side = ("+" * bar_len).ljust(20) if d["total"] >= 0 else ("-" * bar_len).rjust(20)
        print(f"  {d['label']:<24s} {d['total'] * 100:+7.1f}%  {side}")
    print()
    boosts = [d for d in v["drivers"] if d["total"] > 0.02]
    drags = [d for d in v["drivers"] if d["total"] < -0.02]
    if boosts:
        print("Keep boosting (these drove growth):")
        for d in boosts[:3]:
            print(f"  + {d['label']}: {d['lever']}")
    if drags:
        print("Suppress or fix (these held the society back):")
        for d in drags[:3]:
            print(f"  - {d['label']}: {d['lever']}")
    print("Try `python main.py levers` to test which factors cause a boom or collapse.")


def print_leaderboards(sim: "Simulation") -> None:
    month = sim.month
    adults = [p for p in sim.alive if p.age(month) >= 18]
    social = [p for p in adults if p.coop_count + p.defect_count >= 150]

    def board(title: str, people: list[Person], key, fmt, n: int = 5) -> None:
        print(f"\n--- {title} ---")
        for p in sorted(people, key=key, reverse=True)[:n]:
            print(f"  {p.name:<8s} age {int(p.age(month)):>3d}  {p.job_title:<16s} {fmt(p)}")

    print()
    print(rule("Notable people (search any of them in the dossier)", "-"))
    board("Most influential (offices held, network reach)", adults,
          lambda p: (p.offices, sum(t.strength for t in p.ties.values())),
          lambda p: f"offices {p.offices}, reach {sum(t.strength for t in p.ties.values()):.1f}")
    board("Most trusted (public reputation)", social,
          lambda p: (round(p.reputation, 2), p.coop_count + p.defect_count),
          lambda p: f"reputation {p.reputation:.2f} over {p.coop_count + p.defect_count:,} interactions")
    board("Least trusted", social, lambda p: -p.reputation, lambda p: f"reputation {p.reputation:.2f}")
    board("Most deceitful (lowest cooperation rate)", social, lambda p: -p.cooperation_rate,
          lambda p: f"cooperated {p.cooperation_rate:.0%} of {p.coop_count + p.defect_count} times, "
                    f"honesty pct {normal_cdf(p.honesty):.0%}")
    board("Wealthiest", adults, lambda p: p.wealth, lambda p: money(p.wealth))
    board("Most indebted", adults, lambda p: -p.wealth, lambda p: money(p.wealth))
    board("Most socially supported", adults, social_support, lambda p: f"support {social_support(p):.2f}")
    board("Most traumatised", adults, lambda p: p.trauma,
          lambda p: f"trauma {p.trauma:.2f}, victimised {p.victimized}x")
    board("Most prolific offenders", [p for p in sim.people if p.crimes], lambda p: p.crimes,
          lambda p: f"{p.crimes} offences, {p.record} convictions")


def print_success_analysis(sim: "Simulation") -> None:
    reg = sim.success_regression()
    if reg is None:
        return
    print()
    print(rule("What predicts economic success here?", "-"))
    print(f"Standardised OLS of income rank on traits and schooling, adults 30-64 (n={reg['n']}, "
          f"R^2={reg['r2']:.2f}).")
    print("Nobody told the model these answers; they emerge from the equations.\n")
    for name, beta in sorted(reg["coefficients"].items(), key=lambda kv: -abs(kv[1])):
        side = "#" * round(abs(beta) * 40)
        print(f"  {name:<18s} {beta:+.3f}  {'':>10s}{side}" if beta >= 0 else f"  {name:<18s} {beta:+.3f}  {side:>10s}")


# ================================================================ biography
def biography(sim: "Simulation", p: Person) -> str:
    """An auto-generated life story written from the person's traits and events."""
    month, people = sim.month, sim.people
    name, first = p.name, p.first_name
    out: list[str] = []

    # --- origins
    parents = " and ".join(people[i].name for i in (p.mother_id, p.father_id) if i is not None)
    if p.birth_month >= 0:
        born = f"{name} was born in Year {year_of(p.birth_month)} in {sim.district_name(p.district)}"
        out.append(f"{born} to {parents}." if parents else f"{born}.")
    else:
        start = f"{name} was {int(-p.birth_month / 12)} years old when the simulation began"
        out.append(f"{start}, the child of {parents}." if parents else f"{start}.")

    words = describe(p.traits())
    if words:
        joined = words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]
        out.append(f"By temperament {first} was {joined}.")
    else:
        out.append(f"By temperament {first} was unremarkable: no trait more than about one "
                   f"standard deviation from average.")

    # --- education & work
    edu = {0: "", 10: "left school at 16", 12: "finished high school",
           16: "earned a university degree", 18: "earned a postgraduate degree"}.get(p.education, "")
    jobs = Counter(t[2] for t in p.trajectory if t[2] not in ("Child", "Student", "University", "Deceased"))
    main_jobs = [j for j, _ in jobs.most_common(2)]
    if edu:
        work = f" and spent most years as {_a(main_jobs[0])}" if main_jobs else ""
        if len(main_jobs) > 1:
            work += f" (and some as {_a(main_jobs[1])})"
        out.append(f"{first} {edu}{work}.")

    # --- family
    ev = [t for _, t in p.events]
    marriages = sum(1 for t in ev if t.startswith("Married"))
    divorces = sum(1 for t in ev if t.startswith("Divorced"))
    kids = len(p.children)
    fam = []
    if marriages:
        fam.append(f"married {marriages} time{'s' if marriages > 1 else ''}"
                   + (f" (divorced {divorces}x)" if divorces else ""))
    if kids:
        fam.append(f"had {kids} child{'ren' if kids > 1 else ''}")
    if fam:
        out.append(f"{first} " + " and ".join(fam) + ".")

    # --- social character
    n = p.coop_count + p.defect_count
    if n >= 50:
        rate = p.cooperation_rate
        style = ("was almost unfailingly decent to others" if rate > 0.97 else
                 "was generally cooperative" if rate > 0.9 else
                 "had a reputation for cutting corners" if rate > 0.75 else
                 "routinely exploited the people around them")
        out.append(f"Across {n:,} recorded interactions {first} {style} "
                   f"(cooperated {rate:.0%} of the time; public reputation {p.reputation:.2f}).")

    # --- crime, politics, hardship
    sentences = [t for t in ev if t.startswith("Sentenced") or t.startswith("Convicted")]
    if sentences:
        out.append(f"{first} was convicted {len(sentences)} time{'s' if len(sentences) > 1 else ''}"
                   f"; first: {sentences[0].lower()}.")
    if p.victimized:
        out.append(f"{first} was a victim of crime {p.victimized} time{'s' if p.victimized > 1 else ''}.")
    crises = sum(1 for t in ev if t.startswith("Mental-health crisis"))
    if crises:
        out.append(f"{first} went through {crises} mental-health crisis{'es' if crises > 1 else ''}.")
    if p.offices:
        out.append(f"{first} was elected mayor {p.offices} time{'s' if p.offices > 1 else ''}"
                   + (", and was later convicted of embezzlement" if any("embezzl" in t for t in ev) else "") + ".")
    if p.bribes_taken:
        out.append(f"As a police officer {first} took {p.bribes_taken} bribe{'s' if p.bribes_taken > 1 else ''}.")

    # --- ending
    if not p.alive:
        age = int((p.death_month - p.birth_month) / 12)
        out.append(f"{first} died of {p.death_cause} in Year {year_of(p.death_month)}, aged {age}.")
    else:
        out.append(f"At the end of the simulation {first} is {int(p.age(month))}, {p.job_title.lower()}, "
                   f"living in {sim.district_name(p.district)} with a net worth of {money(p.wealth)} and a "
                   f"life satisfaction of {p.life_sat:.1f}/10.")
    return " ".join(out)


def _a(noun: str) -> str:
    """'a nurse', 'an engineer'; statuses such as 'unemployed' take no article."""
    noun = noun.lower()
    if noun in ("unemployed", "retired", "incarcerated"):
        return noun
    return ("an " if noun[0] in "aeiou" else "a ") + noun


# ================================================================== dossier
def dossier(sim: "Simulation", p: Person) -> str:
    month, people = sim.month, sim.people
    lines = [rule(f"DOSSIER {p.name}")]
    status = "ALIVE" if p.alive else f"DECEASED (Year {year_of(p.death_month)}, {p.death_cause})"
    age = p.age(month) if p.alive else (p.death_month - p.birth_month) / 12
    lines.append(f"Status: {status} | Age {int(age)} | {p.job_title} | {sim.district_name(p.district)}")
    fam = []
    for label, pid in (("Mother", p.mother_id), ("Other parent", p.father_id), ("Partner", p.partner_id)):
        if pid is not None:
            fam.append(f"{label}: {people[pid].name}")
    if p.children:
        fam.append("Children: " + ", ".join(people[c].name for c in p.children))
    lines.extend(fam or ["No family recorded."])
    lines.append("")
    lines.append("Traits (population percentile):")
    for name in TRAIT_NAMES:
        z = getattr(p, name)
        lines.append(f"  {name:<18s} {bar(normal_cdf(z), 0, 1, 25)} {normal_cdf(z):4.0%}  (z = {z:+.2f})")
    lines.append(f"Education {p.education} years | wealth {money(p.wealth)} | reputation {p.reputation:.2f} | "
                 f"trust in institutions {p.inst_trust:.2f} | ideology {p.ideology:+.2f} | "
                 f"conspiracy belief {p.conspiracy:.2f}")
    lines.append("")
    lines.append("Life story:")
    lines.extend(_wrap(biography(sim, p), WIDTH - 2, "  "))
    if p.trajectory:
        lines.append("")
        lines.append(f"  {'Year':>4} {'Age':>4}  {'Status':<16} {'Wealth':>12} {'Life sat':>8} {'Stress':>6}")
        for year, a, job, wealth, ls, stress, _ in p.trajectory:
            lines.append(f"  {year:>4} {a:>4.0f}  {job:<16} {money(wealth):>12} {ls:>8.1f} {stress:>6.2f}")
    if p.events:
        lines.append("")
        lines.append("Timeline:")
        for m, text in p.events:
            lines.append(f"  Year {year_of(m):>2} (age {int((m - p.birth_month) / 12):>2}): {text}")
    return "\n".join(lines)


def _wrap(text: str, width: int, indent: str) -> list[str]:
    import textwrap
    return [indent + line for line in textwrap.wrap(text, width)]


def interactive_dossiers(sim: "Simulation") -> None:
    """The original program's dossier loop, fixed: validates ids (no negative
    indexing) and also searches by name."""
    print()
    print(rule())
    print("Look up anyone who ever lived: enter an id (e.g. 42) or part of a name. 'exit' to quit.")
    while True:
        try:
            query = input("\nDossier> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if query.lower() in ("exit", "quit", "q", ""):
            return
        matches = sim.find(query)
        if not matches:
            print("Nobody matches that. Try an id between 0 and", len(sim.people) - 1)
        elif len(matches) == 1:
            print(dossier(sim, matches[0]))
        else:
            print(f"{len(matches)} matches:")
            for p in matches[:25]:
                state = "alive" if p.alive else "deceased"
                print(f"  {p.name:<8s} {state:<9s} {p.job_title}")
