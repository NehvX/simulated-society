"""Named scenarios: combinations of individual behaviour and rules that push a
society towards rapid growth or towards collapse.

Each preset changes parameters (`set`) and/or shifts the founding population's
average personality (`shift`, in standard deviations; inherited by later
generations). Use them with `python main.py run --scenario collapse`, or build
your own with `--set` and `--trait`.
"""
from __future__ import annotations

from .config import SimConfig

PRESETS: dict[str, dict] = {
    "baseline": {
        "description": "Default parameters: an ordinary, moderately regulated town.",
        "set": {}, "shift": {},
    },
    "boom": {
        "description": "Cooperative, curious, disciplined people; strong schools and public services; "
                       "a well-managed commons shared equally.",
        "set": {"policy.education_subsidy": 0.95, "policy.public_services_pc": 420.0,
                "policy.mental_health_pc": 30.0, "policy.commons_rule": "equal_shares",
                "commons.regen_rate": 0.05},
        "shift": {"honesty": 0.4, "agreeableness": 0.3, "conscientiousness": 0.3, "openness": 0.4},
    },
    "collapse": {
        "description": "Selfish, impulsive people racing to strip an open-access commons that regrows "
                       "slowly, with weak schools and thin public services.",
        "set": {"policy.commons_rule": "open_access", "commons.regen_rate": 0.025,
                "policy.education_subsidy": 0.1, "policy.public_services_pc": 200.0,
                "policy.police_per_1000": 2.5},
        "shift": {"honesty": -0.8, "agreeableness": -0.6, "conscientiousness": -0.3},
    },
    "tragedy_of_the_commons": {
        "description": "An ordinary population, but nobody regulates the shared resource and it "
                       "regrows slowly (Hardin 1968).",
        "set": {"policy.commons_rule": "open_access", "commons.regen_rate": 0.025},
        "shift": {},
    },
    "ostrom": {
        "description": "The same fragile resource, governed by a community quota and shared equally "
                       "among trusting, honest people (Ostrom 1990).",
        "set": {"policy.commons_rule": "equal_shares", "commons.regen_rate": 0.025},
        "shift": {"honesty": 0.4, "agreeableness": 0.3},
    },
    "corruption": {
        "description": "A low-honesty population (and so low-honesty mayors and officers) with weak policing.",
        "set": {"policy.police_per_1000": 2.5},
        "shift": {"honesty": -0.8},
    },
    "knowledge_economy": {
        "description": "Free university and high curiosity and ability: does human capital drive growth?",
        "set": {"policy.education_subsidy": 1.0},
        "shift": {"openness": 0.5, "intelligence": 0.3},
    },
}


def apply_preset(cfg: SimConfig, name: str) -> SimConfig:
    if name not in PRESETS:
        raise KeyError(f"unknown scenario '{name}'. Choose from: {', '.join(PRESETS)}")
    preset = PRESETS[name]
    for key, value in preset["set"].items():
        cfg.override(key, value)
    shift = dict(cfg.traits.shift)
    for trait, delta in preset["shift"].items():
        shift[trait] = shift.get(trait, 0.0) + delta
    cfg.traits.shift = shift
    cfg.scenario = name
    return cfg


def describe() -> str:
    width = max(len(n) for n in PRESETS)
    return "\n".join(f"  {name:<{width}}  {p['description']}" for name, p in PRESETS.items())
