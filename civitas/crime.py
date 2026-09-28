"""Crime, policing, courts and prison.

Property crime follows Becker's (1968) economics of crime: a person offends
when the expected benefit beats the expected cost. We write that comparison as
a logit whose terms are each backed by criminology:

  U_crime = b0
          + b_need * strain              financial desperation
          + b_unemp * unemployed         nothing to lose at work
          - b_H * H - b_C * C - b_A * A  moral cost / self-control (Gottfredson & Hirschi 1990)
          + b_N * N
          + b_youth * [15 <= age < 30] + b_male * [male]      the age-crime curve
          + b_peer * peer_criminality    differential association (Sutherland 1947)
          + b_rec * [prior record]
          - b_d * p_arrest * p_convict * sentence_years       deterrence
          - b_L * (2 * institutional_trust - 1)                legitimacy (Tyler 1990)

  P(offend this month) = sigma(U_crime)

The arrest probability has diminishing returns in police numbers,

  p_arrest = (1 - exp(-k * officers_per_1000)) * efficiency * (0.8 + 0.4 * mean officer ability)

and officers low in honesty may accept bribes instead of arresting.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import TYPE_CHECKING

from .mathutil import mean, normal_cdf, sigmoid, weighted_choice
from .network import unlink
from .person import FRIEND, WORK, Person

if TYPE_CHECKING:
    from .simulation import Simulation

CRIME_LABELS = {"theft": "theft", "assault": "assault", "fraud": "fraud",
                "bribery": "taking bribes", "embezzlement": "embezzling public funds"}


class Justice:
    def __init__(self, sim: "Simulation"):
        self.sim = sim
        self.P = sim.cfg.crime
        self.p_arrest = 0.3
        self.releases: list[tuple[int, int]] = []           # (person id, month)
        self.convictions: defaultdict[int, list[int]] = defaultdict(list)

    # ------------------------------------------------------------- policing
    def update_detection(self) -> None:
        sim = self.sim
        police = sim.pools.police
        per_1000 = 1000.0 * len(police) / max(1, len(sim.alive))
        ability = mean([normal_cdf(o.intelligence) for o in police], 0.5)
        self.p_arrest = min(0.9, (1.0 - math.exp(-self.P.police_effect * per_1000))
                            * sim.gov.efficiency * (0.8 + 0.4 * ability))

    def peer_criminality(self, p: Person) -> float:
        """Closeness-weighted share of one's contacts who have offended in the
        last three years (current delinquent peers, not old records)."""
        people, recent = self.sim.people, self.sim.month - 36
        total = bad = 0.0
        for oid, tie in p.ties.items():
            total += tie.strength
            if people[oid].last_offence > recent:
                bad += tie.strength
        return bad / total if total else 0.0

    def offended(self, p: Person) -> None:
        p.crimes += 1
        p.last_offence = self.sim.month

    def crime_utility(self, p: Person, age: float, peers: float | None = None) -> float:
        P = self.P
        sentence_years = P.theft_sentence * (1.0 + 0.5 * p.record) / 12.0
        if peers is None:
            peers = self.peer_criminality(p)
        return (P.intercept
                + P.need * p.strain
                + P.unemployed * (p.stage == WORK and not p.employed)
                - P.honesty * p.honesty
                - P.conscientiousness * p.conscientiousness
                - P.agreeableness * p.agreeableness
                + P.neuroticism * p.neuroticism
                + P.youth * (15.0 <= age < 30.0)
                + P.male * (p.sex == "M")
                + P.peers * peers
                + P.prior_record * (p.record > 0)
                - P.deterrence * self.p_arrest * P.conviction_prob * sentence_years
                - P.legitimacy * (2.0 * p.inst_trust - 1.0))

    # ---------------------------------------------------------------- month
    def step(self) -> None:
        sim, rng, month = self.sim, self.sim.rng, self.sim.month
        for p in list(sim.pools.prison):
            if p.alive and p.prison_release <= month:
                self.release(p)
        for p in sim.alive:
            if not p.free:
                continue
            age = p.age(month)
            if not 15.0 <= age <= 80.0:
                continue
            # Exact shortcut: peer criminality is in [0, 1], so sigma(U with peers = 1)
            # bounds the true probability. Only if the draw falls below that bound do
            # we pay for the network scan.
            r = rng.random()
            if r < sigmoid(self.crime_utility(p, age, peers=1.0)) and r < sigmoid(self.crime_utility(p, age)):
                self.property_crime(p)

    def property_crime(self, offender: Person) -> None:
        """Burglars pick targets that look wealthy, rarely their own close friends."""
        sim, P, rng = self.sim, self.P, self.sim.rng
        district = offender.district if rng.random() < 0.7 else rng.randrange(len(sim.pools.district))
        pool = sim.pools.district[district]
        if not pool:
            return
        candidates = []
        for _ in range(4):
            c = rng.choice(pool)
            tie = offender.ties.get(c.id)
            if c is not offender and c.free and (tie is None or tie.strength < 0.4):
                candidates.append(c)
        if not candidates:
            return
        victim = weighted_choice(rng, candidates, [math.sqrt(max(c.wealth, 0.0) + 2000.0) for c in candidates])
        loot = min(rng.lognormvariate(math.log(P.mean_loot) - 0.32, 0.8), max(victim.wealth, 0.0) * 0.5)
        sim.economy.transfer(victim, offender, loot, "theft")
        self.offended(offender)
        sim.counters["property_crimes"] += 1
        self.victimize(victim, 1.0, "Robbed")
        if rng.random() < self.p_arrest:
            self.apprehend(offender, "theft", loot, victim)

    def fraud(self, fraudster: Person, victim: Person) -> None:
        """Cheating an acquaintance out of money (called from a social defection)."""
        sim, rng = self.sim, self.sim.rng
        amount = min(max(victim.wealth, 0.0) * 0.1, rng.lognormvariate(math.log(250.0) - 0.32, 0.8))
        if amount < 5.0:
            return
        sim.economy.transfer(victim, fraudster, amount, "fraud")
        self.offended(fraudster)
        sim.counters["frauds"] += 1
        victim.stress += 0.15
        if rng.random() < 0.5:                      # the victim realises
            tie = victim.ties.get(fraudster.id)
            if tie is not None:
                tie.beta += 4.0
            fraudster.reputation = max(0.0, fraudster.reputation - 0.05)
            if rng.random() < 0.35 and rng.random() < self.p_arrest:
                self.apprehend(fraudster, "fraud", amount, victim)

    def assault(self, attacker: Person, victim: Person) -> None:
        """A conflict that turned violent. Victims are physically hurt and
        traumatised; friendships end; family ties are badly damaged."""
        sim, rng = self.sim, self.sim.rng
        sim.counters["assaults"] += 1
        self.offended(attacker)
        victim.health = max(0.05, victim.health - (0.05 + 0.10 * rng.random()))
        victim.trauma = min(1.0, victim.trauma + 0.25)
        self.victimize(victim, 1.5, f"Assaulted by {attacker.name}")
        tie = attacker.ties.get(victim.id)
        if tie is None or tie.kind == FRIEND:
            unlink(attacker, victim)
        else:
            for a, b in ((attacker, victim), (victim, attacker)):
                t = a.ties.get(b.id)
                if t is not None:
                    t.strength *= 0.5
                    t.beta += 5.0
            if attacker.partner_id == victim.id:
                attacker.rel_quality -= 0.4
                victim.rel_quality -= 0.4
        if rng.random() < min(0.95, self.p_arrest * self.P.violent_clearance_mult):
            self.apprehend(attacker, "assault", 0.0, victim)

    def prison_incident(self, attacker: Person, victim: Person) -> None:
        """Violence behind bars: injuries and trauma for the victim, handled by
        prison discipline rather than new trials (so sentences cannot spiral)."""
        sim, rng = self.sim, self.sim.rng
        sim.counters["prison_violence"] += 1
        victim.health = max(0.05, victim.health - 0.08 * rng.random())
        victim.trauma = min(1.0, victim.trauma + 0.15)
        victim.stress += 0.5
        unlink(attacker, victim)

    def victimize(self, victim: Person, severity: float, what: str) -> None:
        month = self.sim.month
        victim.victimized += 1
        victim.last_victimized = month
        victim.stress += 0.4 * severity
        victim.gt_beta += 2.0 * severity          # the world now seems less trustworthy
        victim.life_sat -= 0.4 * severity
        victim.log(month, what)

    # ------------------------------------------------------ arrest & courts
    def apprehend(self, offender: Person, crime: str, loot: float, victim: Person | None) -> None:
        sim, P, rng = self.sim, self.P, self.sim.rng
        police = sim.pools.police
        officer = rng.choice(police) if police else None
        if officer is not None and officer is not offender and officer.free:
            bribe = 500.0 + 2.0 * loot
            if offender.wealth > bribe and rng.random() < sigmoid(P.bribe_intercept - 1.5 * officer.honesty):
                sim.economy.transfer(offender, officer, bribe, "bribes")
                officer.bribes_taken += 1
                sim.counters["bribes"] += 1
                if rng.random() < P.internal_affairs:
                    sim.counters["corrupt_officers_caught"] += 1
                    sim.chronicle("crime", f"Officer {officer.name} is caught taking bribes and dismissed.")
                    self.convict(officer, 18, "bribery")
                return
        sim.counters["arrests"] += 1
        if rng.random() >= P.conviction_prob:
            return
        if victim is not None and loot > 0.0 and victim.alive:
            sim.economy.transfer(offender, victim, min(loot, max(offender.wealth, 0.0)), "restitution")
        # Courts jail violent and repeat offenders; first-time property offenders
        # mostly get probation and a fine (but still acquire a criminal record).
        custody = P.custody_violent if crime == "assault" else P.custody_property
        if rng.random() < min(1.0, custody * (1.0 + 0.6 * offender.record)):
            base = {"theft": P.theft_sentence, "assault": P.assault_sentence}.get(crime, P.fraud_sentence)
            months = max(1, round(base * (1.0 + 0.5 * offender.record) * rng.lognormvariate(0.0, 0.3)))
            self.convict(offender, months, crime)
        else:
            sim.counters["convictions"] += 1
            self.convictions[offender.id].append(sim.month)
            offender.record += 1
            offender.last_conviction = sim.month
            offender.reputation = max(0.0, offender.reputation - 0.1)
            sim.economy.transfer(offender, sim.gov, min(P.fine, max(offender.wealth, 0.0)), "fines")
            offender.log(sim.month, f"Convicted of {CRIME_LABELS.get(crime, crime)}: probation and a fine")

    def convict(self, p: Person, months: int, crime: str) -> None:
        sim, month = self.sim, self.sim.month
        sim.counters["convictions"] += 1
        if any(month - r <= 36 for r in self._release_months(p.id)):
            sim.counters["reconvictions"] += 1
        self.convictions[p.id].append(month)
        p.record += 1
        p.last_conviction = month
        if p.incarcerated:                       # an offence committed inside prison
            p.prison_release += months
        else:
            p.prison_release = month + months
            sim.pools.prison.append(p)
        if p.employed:
            sim.economy.lose_job(p, "", quiet=True)
        p.trauma = min(1.0, p.trauma + 0.15)
        p.stress += 0.6
        p.life_sat -= 1.0
        p.reputation = max(0.0, p.reputation - 0.15)
        if p.partner_id is not None:
            partner = sim.people[p.partner_id]
            partner.rel_quality = p.rel_quality = p.rel_quality - 0.2
            partner.stress += 0.3
        p.log(month, f"Sentenced to {months} months in prison for {CRIME_LABELS.get(crime, crime)}")
        if sim.gov.mayor_id == p.id:
            sim.politics.remove_mayor("convicted")

    def release(self, p: Person) -> None:
        p.prison_release = 0
        self.sim.pools.prison.remove(p)
        self.releases.append((p.id, self.sim.month))
        self.sim.counters["releases"] += 1
        p.log(self.sim.month, "Released from prison")

    def _release_months(self, pid: int) -> list[int]:
        return [m for i, m in self.releases if i == pid]

    def recidivism_rate(self, window: int = 36) -> float | None:
        """Share of releases followed by a new conviction within `window` months
        (only releases with a full follow-up window are counted)."""
        end = self.sim.month
        eligible = [(pid, m) for pid, m in self.releases if m <= end - window]
        if not eligible:
            return None
        re = sum(1 for pid, m in eligible if any(m < c <= m + window for c in self.convictions[pid]))
        return re / len(eligible)
