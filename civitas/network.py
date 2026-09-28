"""The social network: creating, weakening and measuring ties.

The network is weighted and directed. Each person keeps a dict
{other_id: Tie}, and ties decay exponentially unless they are refreshed by
contact:

    w(t+1) = w(t) * exp(-lambda)                        friends and acquaintances
    w(t+1) = f + (w(t) - f) * exp(-lambda)              family (never below floor f)
"""
from __future__ import annotations

import math
from typing import Sequence

from .person import FAMILY, FRIEND, PARTNER, Person, Tie


def link(a: Person, b: Person, strength: float, kind: str = FRIEND,
         trust_ab: float = 0.6, trust_ba: float = 0.6) -> None:
    """Create (or strengthen) a mutual tie between a and b."""
    for x, y, trust in ((a, b, trust_ab), (b, a, trust_ba)):
        tie = x.ties.get(y.id)
        if tie is None:
            x.ties[y.id] = Tie(strength, trust, kind)
        else:
            tie.strength = max(tie.strength, strength)
            if kind != FRIEND:
                tie.kind = kind


def unlink(a: Person, b: Person) -> None:
    a.ties.pop(b.id, None)
    b.ties.pop(a.id, None)


def is_relative(a: Person, b: Person) -> bool:
    """Parent, child or sibling (used to rule out partnerships)."""
    if a.id in (b.mother_id, b.father_id) or b.id in (a.mother_id, a.father_id):
        return True
    if a.mother_id is not None and a.mother_id == b.mother_id:
        return True
    return a.father_id is not None and a.father_id == b.father_id


def similarity(a: Person, b: Person, month: int) -> float:
    """Homophily kernel S in (0, 1]: people like people like themselves
    (McPherson, Smith-Lovin & Cook 2001).

        S = exp(-1/2 * sum_k ((x_ak - x_bk) / s_k)^2)

    over age (s = 10 years), ideology (s = 0.4) and education (s = 4 years).
    """
    d_age = (a.birth_month - b.birth_month) / 120.0
    d_ideo = (a.ideology - b.ideology) / 0.4
    d_edu = (a.education - b.education) / 4.0
    return math.exp(-0.5 * (d_age * d_age + d_ideo * d_ideo + d_edu * d_edu))


def social_support(p: Person) -> float:
    """Perceived support = ln(1 + sum_j w_ij * trust_ij): concave, since the 30th
    friend matters less than the first."""
    total = 0.0
    for t in p.ties.values():
        total += t.strength * t.alpha / (t.alpha + t.beta)
    return math.log1p(total)


def decay_ties(p: Person, people: Sequence[Person], decay: float, family_floor: float,
               min_strength: float) -> None:
    factor = math.exp(-decay)
    dead: list[int] = []
    for oid, tie in p.ties.items():
        if tie.kind == FRIEND:
            tie.strength *= factor
            if tie.strength < min_strength:
                dead.append(oid)
        else:
            floor = family_floor if tie.kind == FAMILY else 0.5
            if tie.strength > floor:
                tie.strength = floor + (tie.strength - floor) * factor
    for oid in dead:
        del p.ties[oid]
        people[oid].ties.pop(p.id, None)


def prune(p: Person, people: Sequence[Person], max_ties: int) -> None:
    """Enforce a Dunbar-style cap by dropping the weakest non-family ties."""
    if len(p.ties) <= max_ties:
        return
    friends = sorted((t.strength, oid) for oid, t in p.ties.items() if t.kind == FRIEND)
    for _, oid in friends[: len(p.ties) - max_ties]:
        unlink(p, people[oid])


def strongest_ties(p: Person, n: int) -> list[tuple[int, Tie]]:
    return sorted(p.ties.items(), key=lambda kv: kv[1].strength, reverse=True)[:n]


__all__ = ["link", "unlink", "is_relative", "similarity", "social_support", "decay_ties",
           "prune", "strongest_ties", "FAMILY", "FRIEND", "PARTNER"]
