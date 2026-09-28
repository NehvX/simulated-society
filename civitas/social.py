"""Everyday social life: who meets whom, and what happens when they do.

Each meeting is a one-shot Prisoner's Dilemma played inside a network of
repeated relationships. Cooperation is not built into anyone. It emerges from
personality, Bayesian trust, closeness and *embeddedness* (mutual friends who
would gossip), which are the mechanisms of direct and indirect reciprocity
(Axelrod 1984; Nowak & Sigmund 1998; Coleman 1988).

Per meeting between a and b:
  1. each decides to cooperate with P = sigma(U_coop)             [logit choice]
  2. payoffs from the PD matrix feed each person's monthly mood
  3. each updates trust (Beta) and closeness in the other          [learning]
  4. witnesses update the public reputation, victims gossip        [indirect reciprocity]
  5. a defection can escalate into fraud or violence               [crime]
  6. they may talk politics (bounded confidence) and pass on rumours
"""
from __future__ import annotations

import math
from bisect import bisect_right
from itertools import accumulate
from typing import TYPE_CHECKING

from .mathutil import clamp, normal_cdf, poisson, sigmoid, softmax_choice
from .network import decay_ties, prune, similarity
from .person import CHILD, SCHOOL, UNIVERSITY, FRIEND, Person, Tie

if TYPE_CHECKING:
    from .simulation import Simulation

# Prisoner's Dilemma in utility units with T > R > P > S:
#   temptation 1.5 > reward 1.0 > punishment -0.3 > sucker -1.0
PAYOFF = {
    (True, True): (1.0, 1.0),
    (True, False): (-1.0, 1.5),
    (False, True): (1.5, -1.0),
    (False, False): (-0.3, -0.3),
}


class SocialLife:
    def __init__(self, sim: "Simulation"):
        self.sim = sim
        self.P = sim.cfg.social
        self._tables: dict[int, tuple[list[int], list[float]]] = {}
        self.prevalence = 0.0            # share of adults who currently believe the conspiracy

    # ------------------------------------------------------------------ month
    def step(self, burn_in: bool = False) -> None:
        sim, P, rng = self.sim, self.P, self.sim.rng
        self._tables = {}
        actors = [p for p in sim.alive if sim.month - p.birth_month >= 72]   # age >= 6
        rng.shuffle(actors)
        for p in actors:
            rate = P.interactions_per_month * math.exp(0.25 * p.extraversion)
            if p.incarcerated:
                rate *= 0.5
            for _ in range(poisson(rng, rate)):
                q = self.choose_partner(p)
                if q is not None and q is not p:
                    self.interact(p, q, burn_in)
        keep = 1.0 - P.rumour_decay
        # Media and online exposure: the more widespread a theory already is, the more
        # likely anyone is to run into it (an external field on top of peer contagion).
        field = P.media_exposure * (1.0 + 3.0 * self.prevalence)
        believers = adults = 0
        for p in sim.alive:
            decay_ties(p, sim.people, P.tie_decay, P.family_tie_floor, P.min_tie_strength)
            if burn_in:
                continue
            # Friedkin-Johnsen: o <- o + s (anchor - o). Social influence moves people,
            # but everyone keeps being pulled back towards their own anchor.
            p.ideology += P.stubbornness * (p.anchor - p.ideology)
            p.conspiracy *= keep
            if sim.month - p.birth_month >= 192:
                s = self.susceptibility(p)
                if s > p.conspiracy:
                    p.conspiracy += field * (s - p.conspiracy)
                adults += 1
                believers += p.conspiracy > 0.5
        if adults:
            self.prevalence = believers / adults

    # ------------------------------------------------------- partner selection
    def choose_partner(self, p: Person) -> Person | None:
        """Mixture model of how people meet:
             P_tie   : someone they already know, chosen proportional to closeness
             P_fof   : a friend of a friend (triadic closure)
             else    : a stranger from their current context (school, work, district),
                       best of k candidates under a homophily softmax.
        """
        sim, P, rng, people = self.sim, self.P, self.sim.rng, self.sim.people
        if p.incarcerated:
            pool = sim.pools.prison
            return rng.choice(pool) if len(pool) > 1 else None
        r = rng.random()
        if p.ties and r < P.p_existing_tie + P.p_friend_of_friend:
            friend = self._pick_tie(p)
            if friend is None or r < P.p_existing_tie:
                return friend if friend is not None and friend.free else None
            fof = self._pick_tie(friend)
            return fof if fof is not None and fof.free and fof is not p else None
        pool = self.context_pool(p)
        if not pool:
            return None
        candidates = [rng.choice(pool) for _ in range(P.stranger_candidates)]
        utils = [P.homophily_strength * similarity(p, c, sim.month) for c in candidates]
        return softmax_choice(rng, candidates, utils)

    def _pick_tie(self, p: Person) -> Person | None:
        """Draw one of p's contacts with probability proportional to tie strength,
        using a cumulative-weight table built once per person per month
        (O(log k) per draw instead of O(k))."""
        table = self._tables.get(p.id)
        if table is None:
            if not p.ties:
                return None
            ids = list(p.ties)
            table = (ids, list(accumulate(t.strength for t in p.ties.values())))
            self._tables[p.id] = table
        ids, cum = table
        oid = ids[bisect_right(cum, self.sim.rng.random() * cum[-1])]
        return self.sim.people[oid] if oid in p.ties else None      # the tie may have ended this month

    def context_pool(self, p: Person) -> list[Person]:
        sim, pools = self.sim, self.sim.pools
        if p.stage in (CHILD, SCHOOL):
            age_band = int(p.age(sim.month)) // 3
            return pools.school.get((p.district, age_band), [])
        if p.stage == UNIVERSITY and sim.rng.random() < 0.6:
            return pools.university
        if p.employed and sim.rng.random() < 0.5:
            return pools.firms.get(p.firm, [])
        return pools.district[p.district]

    # ------------------------------------------------------------ interaction
    def interact(self, a: Person, b: Person, burn_in: bool = False) -> None:
        sim, P, rng = self.sim, self.P, self.sim.rng
        tab, tba = a.ties.get(b.id), b.ties.get(a.id)
        if tab is None or tba is None:
            tab, tba = self._first_meeting(a, b, tab, tba)

        mutual = a.ties.keys() & b.ties.keys()
        m = len(mutual)
        a_coop = rng.random() < self.p_cooperate(a, tab, m)
        b_coop = rng.random() < self.p_cooperate(b, tba, m)

        pay_a, pay_b = PAYOFF[(a_coop, b_coop)]
        a.social_month += pay_a
        b.social_month += pay_b
        a.coop_count += a_coop
        a.defect_count += not a_coop
        b.coop_count += b_coop
        b.defect_count += not b_coop

        self._learn(a, tab, b_coop)
        self._learn(b, tba, a_coop)
        self._witness(a, b, a_coop, b_coop, m)

        if not burn_in:
            sim.counters["interactions"] += 1
            sim.counters["cooperations"] += a_coop + b_coop
            if not b_coop:
                self._after_defection(defector=b, victim=a, tie_dv=tba, mutual=mutual)
            if not a_coop:
                self._after_defection(defector=a, victim=b, tie_dv=tab, mutual=mutual)
            month = sim.month
            if month - a.birth_month >= 168 and month - b.birth_month >= 168:    # both >= 14
                if rng.random() < P.opinion_talk_prob:
                    self._discuss(a, b, tab, tba)
                self._rumour(a, b, tba.trust)
                self._rumour(b, a, tab.trust)

    def _first_meeting(self, a: Person, b: Person, tab: Tie | None, tba: Tie | None) -> tuple[Tie, Tie]:
        """A stranger's trust prior mixes one's own generalised trust with the
        other's public reputation."""
        P = self.P
        if tab is None:
            tab = Tie(P.new_tie_strength, 0.5 * a.generalized_trust + 0.5 * b.reputation, FRIEND)
            a.ties[b.id] = tab
        if tba is None:
            tba = Tie(P.new_tie_strength, 0.5 * b.generalized_trust + 0.5 * a.reputation, FRIEND)
            b.ties[a.id] = tba
        people = self.sim.people
        prune(a, people, P.max_ties)
        prune(b, people, P.max_ties)
        # pruning may have removed the brand-new tie if both were full, so re-link
        a.ties.setdefault(b.id, tab)
        b.ties.setdefault(a.id, tba)
        return tab, tba

    def p_cooperate(self, p: Person, tie: Tie, mutual: int) -> float:
        """U = b0 + bH*H + bA*A + bT*(2T - 1) + bW*w + bE*ln(1 + mutual) - bS*stress - bN*strain"""
        P = self.P
        u = (P.coop_intercept
             + P.coop_honesty * p.honesty
             + P.coop_agreeableness * p.agreeableness
             + P.coop_trust * (2.0 * tie.trust - 1.0)
             + P.coop_tie * tie.strength
             + P.coop_embeddedness * math.log1p(mutual)
             - P.coop_stress * p.stress
             - P.coop_need * p.strain)
        return sigmoid(u)

    def _learn(self, p: Person, tie: Tie, other_cooperated: bool) -> None:
        """Discounted Beta update of trust, plus asymmetric closeness update:
        bad experiences weigh ~3x more than good ones (Baumeister et al. 2001)."""
        P = self.P
        rho = P.trust_memory
        c = 1.0 if other_cooperated else 0.0
        tie.alpha = rho * tie.alpha + c
        tie.beta = rho * tie.beta + (1.0 - c)
        if other_cooperated:
            tie.strength += P.tie_gain * (1.0 - tie.strength)
        else:
            tie.strength -= P.tie_loss * tie.strength
        if tie.strength < 0.25:                       # an encounter with a near-stranger
            g = P.gt_memory
            p.gt_alpha = g * p.gt_alpha + c
            p.gt_beta = g * p.gt_beta + (1.0 - c)

    def _witness(self, a: Person, b: Person, a_coop: bool, b_coop: bool, mutual: int) -> None:
        """Each mutual friend independently witnesses with prob q, so the act is
        seen with prob 1 - (1 - q)^(1 + mutual). Reputation is an exponential
        moving average of observed behaviour."""
        P, rng = self.P, self.sim.rng
        seen = 1.0 - (1.0 - P.witness_prob) ** (1 + mutual)
        if rng.random() < seen:
            a.reputation += P.reputation_rate * (a_coop - a.reputation)
            b.reputation += P.reputation_rate * (b_coop - b.reputation)

    # --------------------------------------------------------- consequences
    def _after_defection(self, defector: Person, victim: Person, tie_dv: Tie, mutual: set) -> None:
        sim, P, rng = self.sim, self.P, self.sim.rng
        defector.conflicts_month += 1
        victim.conflicts_month += 1
        if mutual:
            self._gossip(victim, defector, mutual)
        month = sim.month
        adults = month - defector.birth_month >= 192 and month - victim.birth_month >= 192   # 16+
        if not adults:
            return
        # Violent retaliation by the victim: low agreeableness, high neuroticism,
        # stress and being a young man are the classic risk factors.
        age = victim.age(month)
        young_male = 1.0 if victim.sex == "M" and age < 30 else 0.0
        u_violence = (P.violence_intercept - 1.0 * victim.agreeableness + 0.6 * victim.neuroticism
                      + 0.8 * victim.stress - 0.5 * victim.conscientiousness + 0.9 * young_male)
        violent = rng.random() < sigmoid(u_violence)
        if victim.incarcerated or defector.incarcerated:
            if violent:                              # handled by prison discipline, not the courts
                sim.justice.prison_incident(attacker=victim, victim=defector)
            return
        # Fraud: exploiting someone for money. Honesty and closeness restrain it, need pushes it.
        u_fraud = (P.fraud_intercept - 1.2 * defector.honesty + 1.2 * defector.strain
                   - 1.5 * tie_dv.strength)
        if rng.random() < sigmoid(u_fraud):
            sim.justice.fraud(defector, victim)
        if violent:
            sim.justice.assault(attacker=victim, victim=defector)

    def _gossip(self, teller: Person, target: Person, mutual: set) -> None:
        """The victim tells up to three mutual friends. Each listener lowers their
        trust in the defector in proportion to how much they trust the teller."""
        rng, people, weight = self.sim.rng, self.sim.people, self.P.gossip_weight
        for oid in rng.sample(sorted(mutual), min(3, len(mutual))):
            k = people[oid]
            t_teller, t_target = k.ties.get(teller.id), k.ties.get(target.id)
            if t_teller is not None and t_target is not None:
                t_target.beta += weight * t_teller.trust

    # --------------------------------------------------------------- opinions
    def _discuss(self, a: Person, b: Person, tab: Tie, tba: Tie) -> None:
        """Talking politics changes both the opinions and the relationship:
        agreement brings people closer, strong disagreement pushes them apart.
        Influence plus this kind of 'unfriending' is enough for echo chambers to
        emerge (Holme & Newman 2006; Sasahara et al. 2021)."""
        d = b.ideology - a.ideology
        a.ideology = self._shift(a, d, tab.trust)
        b.ideology = self._shift(b, -d, tba.trust)
        P = self.P
        if abs(d) < P.confidence_bound:
            for tie in (tab, tba):
                tie.strength += P.agree_bonding * (1.0 - tie.strength)
        elif abs(d) > P.repulsion_threshold:
            for tie in (tab, tba):
                tie.strength -= P.disagree_distancing * tie.strength

    def _shift(self, p: Person, d: float, trust: float) -> float:
        """Bounded confidence with repulsion.
            |d| < eps_i              : o += mu * trust * d            (assimilation)
            |d| > delta, trust < 1/2 : o -= mu_r * (1 - trust) * d    (backfire effect)
        eps_i grows with openness, so open-minded people listen further afield."""
        P = self.P
        eps = P.confidence_bound * (1.0 + 0.5 * math.tanh(p.openness))
        o = p.ideology
        if abs(d) < eps:
            o += P.convergence_rate * trust * d
        elif abs(d) > P.repulsion_threshold and trust < 0.5:
            o -= P.repulsion_rate * (1.0 - trust) * d
        return clamp(o, -1.0, 1.0)

    def susceptibility(self, p: Person) -> float:
        """Openness to conspiracy theories: higher with anxiety, stress and
        distrust of institutions, lower with cognitive ability (van Prooijen &
        Douglas 2017)."""
        P = self.P
        return sigmoid(P.susceptibility_intercept + 0.6 * p.neuroticism - 0.8 * p.intelligence
                       - 0.3 * p.openness + P.susceptibility_distrust * (0.5 - p.inst_trust) + 0.5 * p.stress)

    def _rumour(self, speaker: Person, listener: Person, listener_trust: float) -> None:
        """Predisposition x exposure (Uscinski, Klofstad & Atkinson 2016): hearing a
        theory from someone you trust pulls your belief *towards your own
        susceptibility s*, never beyond it, so only the predisposed become
        believers:   b += rate * trust * max(0, s - b).
        Debunking by a clear-thinking non-believer pulls belief down:
                     b -= rate * trust * (1 - s) * b."""
        P, rng = self.P, self.sim.rng
        if speaker.conspiracy > 0.5:
            if rng.random() < P.rumour_share_prob * speaker.conspiracy:
                s = self.susceptibility(listener)
                if s > listener.conspiracy:
                    listener.conspiracy += P.rumour_adoption * listener_trust * (s - listener.conspiracy)
        elif speaker.conspiracy < 0.2 and listener.conspiracy > 0.5:
            if rng.random() < P.debunk_prob * normal_cdf(speaker.intelligence):
                s = self.susceptibility(listener)
                listener.conspiracy -= P.debunk_rate * listener_trust * (1.0 - s) * listener.conspiracy
