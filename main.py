"""Civitas command-line interface.

    python main.py                                  # run the default 40-year simulation
    python main.py --scenario collapse              # a preset combination of behaviour and rules
    python main.py --trait honesty=-0.5 --rule open_access --set commons.regen_rate=0.03
    python main.py scenarios                        # list the presets
    python main.py levers                           # which factors cause a boom or a collapse?
    python main.py commons                          # behaviour x allocation rules -> inequality, resources
    python main.py experiment --seeds 8             # compare whole policy regimes with confidence intervals
    python main.py explore out/sim.pkl              # reopen a saved run and read dossiers
"""
from __future__ import annotations

import argparse
import os
import pickle
import sys
import time

from civitas import SimConfig, Simulation
from civitas.dashboard import write_dashboard
from civitas.experiments import SCENARIOS, run_experiment
from civitas.report import interactive_dossiers, print_report
from civitas.resources import RULES
from civitas.scenarios import PRESETS, apply_preset, describe
from civitas.server import hold, serve
from civitas.studies import run_commons_study, run_levers

COMMANDS = ("run", "explore", "experiment", "levers", "commons", "scenarios", "serve", "-h", "--help")


class Tee:
    """Print to the terminal and keep a copy, so the full report is also saved to a text file."""
    def __init__(self, stream):
        self.stream, self.parts = stream, []

    def write(self, text):
        self.parts.append(text)
        return self.stream.write(text)

    def flush(self):
        self.stream.flush()

    def text(self) -> str:
        return "".join(self.parts)


def parse_value(text: str):
    for cast in (int, float):
        try:
            return cast(text)
        except ValueError:
            pass
    return {"true": True, "false": False}.get(text.lower(), text)


def build_config(args: argparse.Namespace) -> SimConfig:
    cfg = SimConfig.load(args.config) if args.config else SimConfig()
    cfg.seed, cfg.years, cfg.initial_population = args.seed, args.years, args.population
    cfg.verbose = not args.quiet
    if args.scenario:
        apply_preset(cfg, args.scenario)
    if args.rule:
        cfg.policy.commons_rule = args.rule
    for item in args.trait or []:
        name, _, delta = item.partition("=")
        cfg.traits.shift = {**cfg.traits.shift, name.strip(): cfg.traits.shift.get(name.strip(), 0.0) + float(delta)}
    extra = (args.extra or "").split()                 # space-separated PARAM=VALUE list (used by Civitas.bat)
    for item in (args.set or []) + extra:
        key, _, value = item.partition("=")
        cfg.override(key.strip(), parse_value(value.strip()))
    return cfg


def cmd_run(args: argparse.Namespace) -> None:
    cfg = build_config(args)
    os.makedirs(args.out, exist_ok=True)
    shift = ", ".join(f"{k} {v:+.1f} s.d." for k, v in cfg.traits.shift.items()) or "none"
    print(f"Founding a town of ~{cfg.initial_population} people (seed {cfg.seed}, scenario '{cfg.scenario}', "
          f"resource rule '{cfg.policy.commons_rule}', trait shifts: {shift}) and simulating {cfg.years} years...")
    tee = Tee(sys.stdout)
    sys.stdout = tee
    try:
        t0 = time.time()
        sim = Simulation(cfg)
        sim.run()
        print(f"\nSimulated {len(sim.history)} years in {time.time() - t0:.1f}s.")
        print_report(sim)
    finally:
        sys.stdout = tee.stream

    tag = f"seed{cfg.seed}" + (f"_{cfg.scenario}" if cfg.scenario != "baseline" else "")
    if args.tag:
        tag += f"_{args.tag}"
    dashboard = os.path.join(args.out, f"civitas_{tag}.html")
    write_dashboard(sim, dashboard)
    report = os.path.join(args.out, f"report_{tag}.txt")
    with open(report, "w", encoding="utf-8") as fh:
        fh.write(tee.text())
    print(f"\nInteractive dashboard written to {os.path.abspath(dashboard)}")
    print(f"Full text report written to {os.path.abspath(report)}")
    if args.save:
        with open(args.save, "wb") as fh:
            pickle.dump(sim, fh)
        print(f"Simulation saved to {args.save} (reopen with: python main.py explore {args.save})")
    cfg.save(os.path.join(args.out, f"config_{tag}.json"))
    server = None if args.no_serve else serve(args.out, os.path.basename(dashboard), block=False)
    if not args.no_interactive and sys.stdin.isatty():
        interactive_dossiers(sim)
    if server is not None:
        hold(server)


def cmd_explore(args: argparse.Namespace) -> None:
    with open(args.file, "rb") as fh:
        sim = pickle.load(fh)
    interactive_dossiers(sim)


def cmd_experiment(args: argparse.Namespace) -> None:
    chosen = SCENARIOS
    if args.only:
        chosen = {k: v for k, v in SCENARIOS.items() if k in args.only}
    run_experiment(chosen, seeds=args.seeds, years=args.years, population=args.population,
                   workers=args.workers, out_dir=args.out)


def _show_study(args: argparse.Namespace, page: str) -> None:
    """Studies write into a sub-folder of out/; serve the whole out/ folder and open the report."""
    if args.no_serve:
        return
    root = os.path.dirname(os.path.abspath(args.out))
    serve(root, os.path.relpath(os.path.join(os.path.abspath(args.out), page), root))


def cmd_levers(args: argparse.Namespace) -> None:
    run_levers(seeds=args.seeds, years=args.years, population=args.population, workers=args.workers,
               out_dir=args.out)
    _show_study(args, "levers_report.html")


def cmd_commons(args: argparse.Namespace) -> None:
    run_commons_study(seeds=args.seeds, years=args.years, population=args.population, workers=args.workers,
                      regen=args.regen, out_dir=args.out)
    _show_study(args, "commons_report.html")


def cmd_serve(args: argparse.Namespace) -> None:
    serve(args.out, "index.html")


def cmd_scenarios(_: argparse.Namespace) -> None:
    print("Scenario presets (use with: python main.py run --scenario NAME):\n")
    print(describe())


def main(argv: list[str] | None = None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(prog="civitas", description="Agent-based simulation of a human society.")
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="run one simulation and write a report + dashboard")
    run.add_argument("--years", type=int, default=40)
    run.add_argument("--population", type=int, default=600, help="size of the founding population")
    run.add_argument("--seed", type=int, default=42)
    run.add_argument("--scenario", choices=list(PRESETS), help="a preset (see: python main.py scenarios)")
    run.add_argument("--rule", choices=RULES, help="how the shared resource is used and shared")
    run.add_argument("--trait", action="append", metavar="TRAIT=DELTA",
                     help="shift the population's average trait in s.d., e.g. --trait honesty=-0.5")
    run.add_argument("--config", help="JSON config file (see out/config_*.json for the format)")
    run.add_argument("--set", action="append", metavar="PARAM=VALUE",
                     help="override any parameter, e.g. --set policy.income_tax=0.35")
    run.add_argument("--out", default="out", help="output directory")
    run.add_argument("--save", help="pickle the finished simulation to this file")
    run.add_argument("--quiet", action="store_true", help="no year-by-year log")
    run.add_argument("--no-interactive", action="store_true", help="skip the dossier prompt")
    run.add_argument("--no-serve", action="store_true", help="don't open the results on localhost")
    run.add_argument("--extra", help="several PARAM=VALUE settings in one string, separated by spaces")
    run.add_argument("--tag", help="extra label for the output file names (e.g. my_mix)")
    run.set_defaults(func=cmd_run)

    explore = sub.add_parser("explore", help="browse dossiers of a saved simulation")
    explore.add_argument("file")
    explore.set_defaults(func=cmd_explore)

    exp = sub.add_parser("experiment", help="compare policy regimes over many seeds")
    exp.add_argument("--seeds", type=int, default=4)
    exp.add_argument("--years", type=int, default=40)
    exp.add_argument("--population", type=int, default=500)
    exp.add_argument("--workers", type=int, default=None)
    exp.add_argument("--only", nargs="*", help=f"subset of scenarios: {list(SCENARIOS)}")
    exp.add_argument("--out", default=os.path.join("out", "experiments"))
    exp.set_defaults(func=cmd_experiment)

    lev = sub.add_parser("levers", help="push each factor low vs high: what causes a boom or a collapse?")
    lev.add_argument("--seeds", type=int, default=3)
    lev.add_argument("--years", type=int, default=30)
    lev.add_argument("--population", type=int, default=400)
    lev.add_argument("--workers", type=int, default=None)
    lev.add_argument("--out", default=os.path.join("out", "levers"))
    lev.add_argument("--no-serve", action="store_true", help="don't open the report on localhost")
    lev.set_defaults(func=cmd_levers)

    com = sub.add_parser("commons", help="research question: behaviour x allocation rules -> inequality, resources")
    com.add_argument("--seeds", type=int, default=3)
    com.add_argument("--years", type=int, default=40)
    com.add_argument("--population", type=int, default=400)
    com.add_argument("--regen", type=float, default=0.035, help="monthly regrowth rate of the resource")
    com.add_argument("--workers", type=int, default=None)
    com.add_argument("--out", default=os.path.join("out", "commons"))
    com.add_argument("--no-serve", action="store_true", help="don't open the report on localhost")
    com.set_defaults(func=cmd_commons)

    scen = sub.add_parser("scenarios", help="list the scenario presets")
    scen.set_defaults(func=cmd_scenarios)

    srv = sub.add_parser("serve", help="open every saved result on localhost")
    srv.add_argument("--out", default="out")
    srv.set_defaults(func=cmd_serve)

    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] not in COMMANDS:
        argv = ["run"] + argv                      # `python main.py --seed 7` means `run --seed 7`
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
