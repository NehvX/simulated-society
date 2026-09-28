"""Personality, cognitive ability, and how they are inherited.

Every person carries seven latent traits stored as z-scores (mean 0, s.d. 1 in
the founding population). Six are the HEXACO personality factors (Ashton & Lee
2007), with Emotionality written as neuroticism; the seventh is general
cognitive ability:

    honesty          H  sincerity, fairness, modesty; the best personality
                        predictor of cheating and corruption
    neuroticism      N  emotional instability and stress reactivity
    extraversion     X  sociability, assertiveness, charisma
    agreeableness    A  patience, forgiveness, low aggression
    conscientiousness C self-control, diligence, planning
    openness         O  curiosity, imagination, unconventional ideas
    intelligence     G  general cognitive ability

Inheritance uses Fisher's (1918) *infinitesimal model*:

    phenotype  z = g + e
    founders   g ~ N(0, h^2),                e ~ N(0, 1 - h^2)
    children   g = (g_mother + g_father) / 2 + N(0, h^2 / 2),   e ~ N(0, 1 - h^2)

The segregation term N(0, h^2/2) is what keeps the genetic variance at h^2 every
generation. Plain averaging (the original code) halves the variance each
generation until everybody becomes identical.
"""
from __future__ import annotations

import math
import random

from .mathutil import clamp

TRAIT_NAMES = (
    "honesty", "neuroticism", "extraversion", "agreeableness",
    "conscientiousness", "openness", "intelligence",
)
TRAIT_CAP = 3.5

# Words used when describing a person in their biography: (low, high).
TRAIT_WORDS = {
    "honesty": ("manipulative", "scrupulously honest"),
    "neuroticism": ("emotionally steady", "anxious"),
    "extraversion": ("reserved", "outgoing"),
    "agreeableness": ("combative", "warm"),
    "conscientiousness": ("impulsive", "disciplined"),
    "openness": ("conventional", "curious"),
    "intelligence": ("practically minded", "academically gifted"),
}


def founder_traits(rng: random.Random, heritability: dict,
                   shift: dict | None = None) -> tuple[list[float], list[float]]:
    """Genes and phenotype for someone with no parents in the simulation.
    `shift` moves the population mean of a trait (placed in the genes, so the
    change is inherited by later generations)."""
    genes, traits = [], []
    for name in TRAIT_NAMES:
        h2 = heritability[name]
        g = rng.gauss(0.0, math.sqrt(h2)) + (shift.get(name, 0.0) if shift else 0.0)
        e = rng.gauss(0.0, math.sqrt(1.0 - h2))
        genes.append(g)
        traits.append(clamp(g + e, -TRAIT_CAP, TRAIT_CAP))
    return genes, traits


def inherited_traits(rng: random.Random, mother_genes: list[float], father_genes: list[float],
                     heritability: dict) -> tuple[list[float], list[float]]:
    """Infinitesimal-model offspring: mid-parent genes + Mendelian segregation noise."""
    genes, traits = [], []
    for k, name in enumerate(TRAIT_NAMES):
        h2 = heritability[name]
        g = 0.5 * (mother_genes[k] + father_genes[k]) + rng.gauss(0.0, math.sqrt(h2 / 2.0))
        e = rng.gauss(0.0, math.sqrt(1.0 - h2))
        genes.append(g)
        traits.append(clamp(g + e, -TRAIT_CAP, TRAIT_CAP))
    return genes, traits


def describe(traits: dict[str, float], threshold: float = 0.9) -> list[str]:
    """The distinctive (|z| > threshold) traits of a person, most extreme first."""
    notable = sorted(((abs(z), name, z) for name, z in traits.items() if abs(z) > threshold), reverse=True)
    return [TRAIT_WORDS[name][1 if z > 0 else 0] for _, name, z in notable]
