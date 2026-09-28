import random


# -------------------- PERSON CLASS --------------------
class Person:
   def __init__(self, id, age=0, role="Citizen", parents=None):
       self.id = id
       self.age = age
       self.role = role


       self.is_alive = True
       self.is_arrested = False
       self.prison_time = 0


       self.ptsd_score = 0.0
       self.mental_health = 1.0
       self.stability = 1.0


       self.children_ids = []
       self.friends = set()


       self.conspiracy_belief = 0.0
       self.life_log = []


       # -------- TRAITS --------
       if parents:
           p1, p2 = parents
           inherit = lambda x, y: (x + y) / 2 + random.uniform(-0.05, 0.05)
           self.charisma = inherit(p1.charisma, p2.charisma)
           self.empathy = inherit(p1.empathy, p2.empathy)
           self.ambition = inherit(p1.ambition, p2.ambition)
           self.intelligence = inherit(p1.intelligence, p2.intelligence)
           self.arrogance = inherit(p1.arrogance, p2.arrogance)
           self.corruptness = inherit(p1.corruptness, p2.corruptness)
           self.aggression = inherit(p1.aggression, p2.aggression)
           self.consciousness = inherit(p1.consciousness, p2.consciousness)
           self.discipline = inherit(p1.discipline, p2.discipline)
           self.curiosity = inherit(p1.curiosity, p2.curiosity)
           self.cooperation = inherit(p1.cooperation, p2.cooperation)
           self.wealth = (p1.wealth + p2.wealth) * 0.15
       else:
           self.charisma = random.uniform(0.1, 1.0)
           self.empathy = random.uniform(0.1, 1.0)
           self.ambition = random.uniform(0.1, 1.0)
           self.intelligence = random.uniform(0.1, 1.0)
           self.arrogance = random.uniform(0.1, 1.0)
           self.corruptness = random.uniform(0.1, 1.0)
           self.aggression = random.uniform(0.1, 1.0)
           self.consciousness = random.uniform(0.1, 1.0)
           self.discipline = random.uniform(0.1, 1.0)
           self.curiosity = random.uniform(0.1, 1.0)
           self.cooperation = random.uniform(0.1, 1.0)
           self.wealth = 2000 if age > 18 else 500


       self.job = "Infant" if age < 5 else "Student" if age < 22 else "Unemployed"
       self.job_level = 1


       self.reputation = 1.0
       self.political_power = 0.0
       self.deception_score = 0
       self.productivity_score = 0


       self.log_event("Initial State")


   def log_event(self, event):
       self.life_log.append({
           "Age": self.age,
           "Job": self.job,
           "Wealth": round(self.wealth, 2),
           "Mental": round(self.mental_health, 2),
           "Event": event
       })


   # -------------------- INTERACTION --------------------
   def interact(self, other):
       if not self.is_alive or self.is_arrested: return


       # friendship reinforcement
       if other.id not in self.friends and random.random() < 0.02:
           self.friends.add(other.id)
           other.friends.add(self.id)


       will_lie = self.corruptness > self.empathy


       if will_lie:
           self.deception_score += 1
           gain = 80 * (1 - self.consciousness)
           self.wealth += gain
           self.political_power += 0.02


           if random.random() < 0.05:
               other.reputation -= 0.02
       else:
           self.reputation += 0.003 + self.cooperation * 0.003
           self.productivity_score += 1


           if self.cooperation > 0.7:
               self.mental_health = min(1, self.mental_health + 0.002)
               other.mental_health = min(1, other.mental_health + 0.002)


       # conspiracy spread
       if self.conspiracy_belief > 0.6:
           if random.random() < 0.1:
               other.conspiracy_belief += 0.05


# -------------------- SYSTEM --------------------
JOBS = {
   "Doctor": 5000,
   "Engineer": 4000,
   "Teacher": 2500,
   "Retailer": 2000,
   "Unemployed": 500,
   "Police Force": 3000
}


population = [Person(i, age=random.randint(0, 55)) for i in range(600)]


# police
for i in range(30):
   population[i].role = "Police Force"
   population[i].job = "Police Force"


stats = {"births":0,"deaths":0,"crimes":0,"arrests":0,"suicides":0}


mayor = None


# -------------------- SIMULATION --------------------
for day in range(1, 10951):


   alive = [p for p in population if p.is_alive]


   # ---- yearly ----
   if day % 365 == 0:
       for p in alive:
           p.age += 1


           # salary
           salary = JOBS.get(p.job, 1000)
           p.wealth += salary


           # cost of living
           p.wealth -= 1500


           # mental health
           debt_penalty = abs(p.wealth)/20000 if p.wealth < 0 else 0
           p.mental_health = max(0, p.mental_health - debt_penalty - 0.01)


           # PTSD decay
           p.mental_health -= p.ptsd_score * 0.01


           # natural death
           if p.age > 70 and random.random() < 0.03:
               p.is_alive = False
               stats["deaths"] += 1
               p.log_event("Died of Age")


           # suicide
           if p.mental_health < 0.05 and random.random() < 0.03:
               p.is_alive = False
               stats["suicides"] += 1
               p.log_event("Suicide")


           # job assignment
           if p.age == 22:
               p.job = random.choice(list(JOBS.keys()))


   # ---- births ----
   if day % 120 == 0:
       parents = [p for p in alive if 20 < p.age < 40]
       if len(parents) > 2:
           p1, p2 = random.sample(parents, 2)
           child = Person(len(population), age=0, parents=(p1,p2))
           population.append(child)
           stats["births"] += 1


   # ---- crime ----
   for p in alive:
       if p.wealth < -3000 and random.random() < 0.02:
           p.wealth += 2000
           stats["crimes"] += 1


           # police detection
           police = random.choice([x for x in alive if x.role=="Police Force"])
           detect_chance = 0.3 + police.intelligence*0.3


           if random.random() < detect_chance:
               p.is_arrested = True
               p.prison_time = random.randint(1,5)
               stats["arrests"] += 1
               p.ptsd_score += 0.2
               p.log_event("Arrested")


   # ---- prison system ----
   for p in population:
       if p.is_arrested:
           p.prison_time -= 1
           if p.prison_time <= 0:
               p.is_arrested = False
               p.log_event("Released from Prison")


   # ---- interactions ----
   for _ in range(120):
       if len(alive) > 1:
           p1 = random.choice(alive)


           # prefer friends
           if p1.friends and random.random() < 0.6:
               p2 = population[random.choice(list(p1.friends))]
           else:
               p2 = random.choice(alive)


           if p2 != p1:
               p1.interact(p2)


   # ---- election ----
   if day % 1460 == 0:
       candidates = [p for p in alive if p.age > 30]
       mayor = max(candidates, key=lambda x: x.political_power + x.reputation)
       print(f"[Election] Mayor ID {mayor.id} | Reputation {mayor.reputation:.2f}")


# -------------------- FINAL --------------------
survivors = [p for p in population if p.is_alive and not p.is_arrested]
print(f"\n{'='*20} 30-YEAR FINAL SYSTEMIC REPORT {'='*20}")
print(f"Final Population: {len(survivors)} | Incarcerated: {len([p for p in population if p.is_arrested])}")
print(f"Current Mayor: ID {mayor.id if mayor else 'N/A'}")


def print_top(title, attr, rev=True):
   top = sorted(survivors, key=lambda x: getattr(x, attr), reverse=rev)[:5]
   print(f"\n--- {title} ---")
   for p in top:
       print(f"ID {p.id} (Age {p.age}, {p.job}) | {attr}: {getattr(p, attr):.2f}")


print_top("MOST POLITICAL INFLUENCE", "political_power")
print_top("MOST LOVED PEOPLE", "reputation")
print_top("MOST HATED PEOPLE", "reputation", rev=False)
print_top("MOST DECEITFUL", "deception_score")
print_top("MOST CYNICAL", "conspiracy_belief")
print_top("WEALTHIEST", "wealth")
print_top("POOREST", "wealth", rev=False)
print_top("MOST TRAUMATIZED (PTSD)", "ptsd_score")
print_top("MOST CONSCIENTIOUS", "consciousness")
print_top("MOST DISCIPLINED", "discipline")
print_top("MOST CURIOUS", "curiosity")
print_top("MOST COOPERATIVE", "cooperation")


# Display suicide victims
suicide_victims = [p for p in population if not p.is_alive and any("Suicide" in log["Event"] for log in p.life_log)]
if suicide_victims:
   print(f"\n--- SUICIDE VICTIMS ({len(suicide_victims)}) ---")
   for p in suicide_victims:
       suicide_event = next((log for log in p.life_log if "Suicide" in log["Event"]), None)
       if suicide_event:
           print(f"ID {p.id} | Age at death: {suicide_event['Age']} | Job: {suicide_event.get('Job', 'Unknown')} | Wealth: ${suicide_event['Wealth']:,.2f} | Mental Health: {suicide_event['Mental']:.2f}")


print(f"\n--- CRIME & ECONOMY SUMMARY ---")
print(f"Petty Crimes: {stats['crimes']} | Arrests: {stats['arrests']} | Suicides: {stats['suicides']}")
print(f"Births: {stats['births']} | Natural Deaths: {stats['deaths']}")
print(f"Active Task Force: {len([p for p in survivors if p.role == 'Police Force'])} Officers")


# ---- INTERACTIVE ----
while True:
   print("\n" + "="*60)
   user_input = input("Enter Person ID for Deep Dossier (or 'exit' to quit): ").strip().lower()
   if user_input == 'exit': break
   try:
       p = population[int(user_input)]
       print(f"\nDOSSIER: ID {p.id} | Status: {'ALIVE' if p.is_alive else 'DEAD'} | Age: {p.age}")
       print(f"ATTRIBUTES: Intel: {p.intelligence:.2f} | Charisma: {p.charisma:.2f} | Empathy: {p.empathy:.2f} | Ambition: {p.ambition:.2f}")
       print(f"            Arrogance: {p.arrogance:.2f} | Corruptness: {p.corruptness:.2f} | Aggression: {p.aggression:.2f}")
       print(f"            Consciousness: {p.consciousness:.2f} | Discipline: {p.discipline:.2f} | Curiosity: {p.curiosity:.2f} | Cooperation: {p.cooperation:.2f}")
       print(f"\n{'Age':<4} | {'Job':<15} | {'Wealth':<12} | {'Mental':<6} | {'Event':<28}")
       print("-" * 85)
       for e in p.life_log:
           print(f"{e['Age']:<4} | {e['Job']:<15} | ${e['Wealth']:<11,.2f} | {e['Mental']:<6.2f} | {e['Event']:<28}")
   except (ValueError, IndexError):
       print("Invalid ID. Please try again.")


