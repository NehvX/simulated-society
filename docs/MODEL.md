# The Civitas Model

How Civitas turns human behaviour into equations, explained in plain English.
Every equation is collected in the [appendix](#appendix-equations) at the end, so you can read the ideas first and check the maths later.

- **Parameter values** are the defaults in `civitas/config.py`.
- **Sources** are cited where the literature gives an estimate. The remaining numbers were calibrated by hand (see [13](#13-does-it-match-reality)).
- **Time** advances one month at a time. "Probability" means probability per month unless stated otherwise.
- **Personality traits** are z-scores: 0 is average and ±1 is one standard deviation.

## Contents

1. [People](#1-people)
2. [Social life](#2-social-life)
3. [Opinions](#3-opinions)
4. [Misinformation](#4-misinformation)
5. [Economy](#5-economy)
6. [Crime and justice](#6-crime-and-justice)
7. [Health and well-being](#7-health-and-well-being)
8. [Family and demography](#8-family-and-demography)
9. [Politics](#9-politics)
10. [The shared resource](#10-the-shared-resource)
11. [Growth and development](#11-growth-and-development)
12. [Measurement](#12-measurement)
13. [Does it match reality?](#13-does-it-match-reality)
14. [Limitations](#14-limitations)
15. [Built-in studies](#15-built-in-studies)
- [Appendix: equations](#appendix-equations)
- [References](#references)

---

## Design principles

1. **Individuals, not averages.** About 600–1,000 people, each with their own genes, personality, relationships, money, health and beliefs.
2. **Choices are probabilities.** A person acts with probability σ(U), where U adds up simple, signed terms (McFadden 1974). The sign of each term comes from theory, and its size comes from the literature or calibration.
3. **Nothing large-scale is scripted.** Inequality, crime waves, polarisation, mobility and life expectancy are *outputs*.
4. **The books balance.** Money is conserved, partnerships are mutual, and the dead hold nothing. Tests check this.
5. **Reproducible.** One seeded random generator drives everything, so the same seed gives the same history.

**Each month, in this order** (`simulation.py`):

```
demography → refresh pools → economy (incl. shared resource) → social life → crime → well-being → politics
                                          (every year) → statistics, development index, productivity growth
```

---

## 1. People

*Code: `traits.py`, `person.py`*

Each person has seven traits: the six HEXACO personality factors (Ashton & Lee 2007) plus cognitive ability.

| Symbol | Trait | What it influences |
|---|---|---|
| H | Honesty-humility | cooperation, fraud, bribery, embezzlement |
| N | Neuroticism | stress, crises, conspiracy belief |
| X | Extraversion | number of encounters, charisma in elections |
| A | Agreeableness | cooperation, low violence, relationship quality |
| C | Conscientiousness | wages, job security, saving, health, longevity |
| O | Openness | education, left-leaning views, open-mindedness |
| G | Cognitive ability | education, wages, resistance to misinformation |

**Inheritance.** A child's traits are the average of the parents' genes plus a random shuffle, plus their own environment. This keeps people varied from one generation to the next and reproduces the textbook rule that *offspring resemble parents in proportion to heritability* (personality 0.35–0.45, ability 0.55). [Equation A1](#a1-inheritance).

**Habits from traits.** Conscientious people spend a smaller share of any extra income. Open and calm people take more financial risks. Agreeable people start out trusting strangers more. Each person also has a fixed, personal "wage luck".

---

## 2. Social life

*Code: `social.py`, `network.py`*

**The network.** Each person has ties to others. Every tie has a *closeness* (0 to 1) and a *trust* estimate.
- Ties fade by 5% a month without contact. Family ties fade only to a floor of 0.3 and partner ties to 0.5.
- Friendships below 0.04 are dropped. Nobody keeps more than 150 ties (Dunbar's number).

**Who meets whom.** Each person starts about 4 encounters a month (more if extraverted, half as many in prison). Each partner is chosen as follows:

| Chance | Who | Why |
|---|---|---|
| 60% | An existing contact, weighted by closeness | habit |
| 12% | A friend of a friend | triadic closure (Granovetter 1973) |
| 28% | A stranger from school, university, work or the district, favouring people of similar age, views and education | homophily (McPherson et al. 2001) |

**Cooperate or defect.** Every encounter is a Prisoner's Dilemma:

| | Other cooperates | Other defects |
|---|---|---|
| **You cooperate** | +1 | −1 |
| **You defect** | +1.5 | −0.3 |

The chance of cooperating rises with honesty, agreeableness, trust in the other person, closeness and the number of mutual friends (defecting is costly where people talk; Coleman 1988). It falls with stress and money worries. [Equation A2](#a2-cooperation).

**Learning.** After each encounter, trust is updated, with recent behaviour counting more. Closeness rises slowly after kindness and drops fast after exploitation (bad is stronger than good; Baumeister et al. 2001). [Equation A3](#a3-learning-reputation-and-support).

**Reputation and gossip.** Mutual friends sometimes witness an encounter (8% each) and update the person's public reputation. A victim of defection tells up to three mutual friends, who become more distrustful (indirect reciprocity; Nowak & Sigmund 1998). When meeting a stranger, people judge them by their own general trust in others and the stranger's reputation.

**Social support.** The more trusted, close friends you have, the more supported you are, with diminishing returns (the fortieth friend adds less than the first). Support lowers stress and crisis risk and raises life satisfaction.

---

## 3. Opinions

*Code: `social.py`, `politics.py`*

Political ideology runs from −1 (left, pro-redistribution) to +1 (right).

- **Where views come from.** Each person has an *anchor* view set by their parents' views and personality (open people lean left, conscientious people lean right; Gerber et al. 2010). This makes ideology partly heritable (Hatemi et al. 2014). At 18 the anchor absorbs the views picked up growing up, and each year it drifts 1% towards the person's class interest.
- **Talking politics.** In 20% of encounters between people aged 14+:
  - If views are fairly close, both move closer, more so when they trust each other.
  - If views are very far apart and they distrust each other, both move *further* apart (backfire).
  - Otherwise nothing changes.
  (Deffuant et al. 2000; Jager & Amblard 2005.)
- **Stubbornness.** Every month, each person is pulled 10% of the way back to their anchor (Friedkin & Johnsen 1990).
- **Adaptive network.** Agreeing strengthens a tie and strong disagreement weakens it. Influence plus this "unfriending" is enough for **echo chambers** to emerge (Holme & Newman 2006). Nobody is programmed to seek one.

[Equation A4](#a4-opinion-change).

---

## 4. Misinformation

*Code: `social.py`, `politics.py`*

Each person has a belief (0 to 1) in a conspiracy theory. Belief is **predisposition × exposure** (Uscinski et al. 2016).

- **Predisposition** is higher for people who are anxious, stressed, lower in ability, less open, or distrustful of institutions (van Prooijen & Douglas 2017).
- **Belief grows** when hearing it from a believer or through media exposure.
- **Belief shrinks** through debunking by clear-thinking non-believers and through forgetting.
- **New theories** appear about 4 times a year, more often during recessions and after scandals.

Belief can never rise above a person's own predisposition, so only the predisposed become believers. This gives a stable 5–15% of believers that rises after scandals and recessions. Believers also distrust institutions, which feeds back into susceptibility. [Equation A5](#a5-conspiracy-belief).

---

## 5. Economy

*Code: `economy.py`*

**Business cycle.** The economy switches between expansions (average 84 months, at least 18) and recessions (average 14 months, at least 6; Hamilton 1989). In a recession, job losses are 1.6× as likely, job finding is 0.7× as likely, and equity returns fall 15 percentage points a year.

**Schooling.** Three yes/no choices decide education: stay after 16, go to university at 18, do a postgraduate degree at 22. They depend on ability, conscientiousness, parents' income, the district's school quality (Chetty et al. 2014) and family money worries. The result is 10, 12, 16 or 18 years of schooling. University costs weigh most on poor families, who cannot easily borrow (Lochner & Monge-Naranjo 2012), so education subsidies help them most. [Equation A6](#a6-schooling).

**Wages.** Pay follows the Mincer earnings equation. Each year of schooling adds 8% (Psacharopoulos & Patrinos 2018), experience adds pay that peaks after about 29 years, and conscientiousness, ability and extraversion add a little. [Equation A7](#a7-wages).

**Jobs.** Each month a worker may lose a job and an unemployed person may find one. Conscientiousness and ability help. Employed contacts help too, and weak ties count double (Granovetter 1973). A criminal record halves the hiring rate (Pager 2003). Police jobs are limited by the mayor's budget and open only to people aged 21–55 with no record. [Equation A8](#a8-jobs).

**Taxes and benefits.**
- Income tax applies above $1,000 a month, with a higher top rate above $10,000.
- Benefits: unemployment pay (50% of the last wage for 12 months), sick pay (70%), pensions (45% of the average wage), child benefit, an optional universal basic income, and a means-tested welfare floor for people with under $15k of wealth.

**Spending and wealth.** People spend on essentials first, then a share of what is left. Poorer people spend a larger share of extra income (buffer-stock saving; Carroll 1997). Unexpected bills arrive, more often to people in poor health. Positive wealth earns a risky return, and richer people hold riskier, higher-yielding assets (Fagereng et al. 2020). Growth that compounds randomly produces a **Pareto tail**, which is why a few people get very rich. Debt costs 10% a year, and below −$45k a person goes bankrupt. [Equation A9](#a9-taxes-spending-and-wealth).

**Inheritance.** A 15% estate tax is taken first. The partner gets half (all if there are no children), and the rest is split equally among living children. An estate with no heirs goes to the treasury. Debts die with the debtor.

**Money is conserved.** Every change of money is either a zero-sum transfer or a logged external flow (wages, consumption, returns, public services). A test checks that the totals balance to floating-point precision. [Equation A9](#a9-taxes-spending-and-wealth).

---

## 6. Crime and justice

*Code: `crime.py`*

**Deciding to offend.** This follows Becker's (1968) cost-benefit logic. The chance of committing a property crime goes up with need (money worries, unemployment), being young (15–29), being male, having a record, and having delinquent friends (Sutherland 1947). It goes down with honesty, self-control (Gottfredson & Hirschi 1990), agreeableness, fear of punishment, and trust in institutions, because people obey institutions they see as legitimate (Tyler 1990). [Equation A10](#a10-crime).

**Police.** More officers mean more arrests, but with diminishing returns. The arrest rate also depends on the mayor's competence and the officers' ability. Officers low in honesty may take bribes, and internal affairs catches 15% of them. [Equation A11](#a11-policing-and-bribes).

**Offences.**
- **Theft:** the victim is usually from the offender's district and never a close friend. The average haul is $700, capped at half the victim's wealth.
- **Fraud:** can follow a defection, and is more likely for low-honesty, cash-strapped people.
- **Assault:** retaliation after being exploited, more likely for men under 30 and for angry, low-agreeableness people. The victim loses health and gains trauma, and the friendship ends.

**Courts and prison.** 85% of arrests lead to a conviction. Repeat offenders and violent offenders are more likely to be jailed. Sentences last months, not days, and grow with prior convictions. In prison, people lose their jobs, meet only other prisoners, and gain stress and trauma. This "school of crime" drives **recidivism**, defined as the share of releases followed by a new conviction within 36 months. Offenders pay restitution to victims from their own wealth.

---

## 7. Health and well-being

*Code: `wellbeing.py`*

- **Health** drifts towards what is normal for one's age and is pushed down by stress and money worries (McEwen 1998). [Equation A12](#a12-stress-and-health).
- **Stress** works like a leaky bucket. Money worries, unemployment, conflicts, prison and crises pour in, and recovery drains it. Good friends, conscientiousness, low neuroticism and treatment drain it faster. Events add jumps: job loss, widowhood, being robbed or assaulted.
- **Trauma** fades with a half-life of 36 months, or 12 months with treatment.
- **Mental-health crises** follow a stress-diathesis model: high stress, neuroticism and trauma raise the risk, and support lowers it. Treatment depends on the public mental-health budget. People in crisis cannot work and receive sick pay. [Equation A13](#a13-mental-health-crises).
- **Life satisfaction** (0–10) is pulled towards a personal set point, so shocks fade. That is hedonic adaptation (Brickman et al. 1978). The set point depends on income *relative to neighbours* (Luttmer 2005), support, partnership, work, health, personality, money worries, prison, trauma and trust. Unemployment is only partly adapted to (Lucas 2007) because it also lowers the set point. [Equation A14](#a14-life-satisfaction).

---

## 8. Family and demography

*Code: `demography.py`*

- **Death.** Risk follows a Gompertz–Makeham curve, doubling about every 7.5 years of age. People in worse health than normal for their age, which stress and poverty cause, face higher risk, and conscientious people live longer (Kern & Friedman 2008). That is how the **socioeconomic health gradient** emerges (Marmot 2005). [Equation A15](#a15-mortality).
- **Partnership.** Each month, 35% of single adults look among their contacts for someone compatible, not related, and within 12 years of age. People are matched by closeness and similarity, so partnering is assortative. Relationship quality moves towards a set point that rises with agreeableness and falls with neuroticism and money worries. Poor quality raises the chance of divorce. [Equation A16](#a16-fertility-and-divorce).
- **Children.** Fertility peaks around age 30, is higher when a couple wants more children, and is higher when they are financially secure. Children inherit genes (§1), parents' views (§3) and family ties.
- **Where people live.** There are five districts with housing costs from 0.70× to 1.60×. Each year, households with rent above 35% of income move down-market and prosperous ones move up. This alone produces **income segregation** (in the spirit of Schelling 1971), which feeds back into school quality (§5).
- **The founding population** is sampled to match a stationary life-table age structure, with real parent–child links, and an 18-month social burn-in before measurement begins.

---

## 9. Politics

*Code: `politics.py`*

**Trust in institutions.** Each person's trust drifts towards a target. It is higher when they share the mayor's views and the government is competent. It is lower when they are unemployed, in recession, believe conspiracy theories, or have been a recent crime victim. A scandal cuts everyone's trust by 0.2 at once. [Equation A17](#a17-trust-in-institutions).

**Candidates.** The three most ambitious eligible adults run (age 30–78, no criminal record), plus the incumbent if within the two-term limit. Ambition rises with extraversion, conscientiousness, reputation and a wide network. It falls slightly with honesty, a nod to the "dark triad" in politics.

**Voting.** Turnout rises with age, education, trust and conscientiousness. Vote choice weighs ideological distance, the candidate's competence and charisma, personal acquaintance, and (for people who trust institutions) the incumbent's record (Downs 1957; Lindbeck & Weibull 1987). [Equation A18](#a18-voting).

**Policy.** The winner's ideology sets policy:

| More left | More right |
|---|---|
| higher income and top taxes | lower taxes |
| bigger welfare, child benefit, education subsidy, mental-health and public-service budgets | more police |

The mayor's competence sets administrative efficiency, which scales policing and treatment.

**Corruption.** Each month a mayor may skim 6% of tax revenue, with probability that rises sharply as honesty falls. Each skim is detected with probability 0.02. A scandal brings prosecution, recovery of the funds, a trust shock, more conspiracy theories and a special election (Mauro 1995). [Equation A19](#a19-corruption-and-the-fiscal-rule).

**Fiscal rule.** At the yearly review, austerity follows if debt exceeds 90% of annual labour income and is still rising. A 2-point tax cut follows if the treasury holds more than 25% of income and is in surplus. In policy experiments, a smooth rule (Bohn 1998) keeps every regime solvent.

---

## 10. The shared resource

*Code: `resources.py`*

The town shares one renewable resource, such as farmland, a fishery or a forest. Its carrying capacity is 60 units per founding citizen, and it starts at 80% of capacity. It regrows logistically, fastest at half capacity (Schaefer 1954).

**Who takes how much.** Every working-age adult (18–70, free and in the labour force) decides how much effort to put into harvesting. Effort is higher for people who are less honest, less agreeable or more desperate, and higher for the unemployed. As the resource runs low, the least honest "panic-grab". Catch is proportional to the stock, and each unit is worth $400.

**The five rules** (Hardin 1968; Ostrom 1990):

| Rule (`policy.commons_rule`) | Quota? | Who receives the value |
|---|---|---|
| `open_access` | No | Each harvester keeps their catch |
| `regulated` (default) | Yes | Each harvester keeps their catch |
| `equal_shares` | Yes | Pooled and split equally among all adults |
| `need_based` | Yes | Pooled; first to those whose income is below essential costs, then equally |
| `private_ownership` | Yes, owner-enforced | 40% to harvesters by effort, 60% to owners in proportion to wealth |

**Quotas.** The monthly quota equals this month's regrowth, plus a correction that steers the stock towards 60% of capacity, split equally among harvesters. A harvester who wants more than the quota obeys with a probability that rises with honesty, trust in institutions and fear of arrest, and falls with desperation. Those who don't comply take what they want and may be fined.

**Why it matters.** As the resource runs low, essentials get up to 60% more expensive. That raises money worries for everyone, which feeds crime, stress, ill health, early death and lower fertility, and scarcity also slows productivity growth (§11). This is the Brander & Taylor (1998) route to overshoot and decline, as on Easter Island. [Equation A20](#a20-shared-resource).

Study design and hypotheses: [RESEARCH_QUESTION.md](RESEARCH_QUESTION.md).

---

## 11. Growth and development

*Code: `development.py`*

**Productivity growth.** A trend productivity level multiplies every wage. Each year it grows or shrinks (capped at ±6%) based on things measured on the simulated people themselves:

| Factor | Effect on growth |
|---|---|
| Background progress | + |
| Schooling of workers (Barro 1991) | + |
| Curiosity and ability of workers | + |
| Everyday cooperation (Knack & Keefer 1997) | + |
| Trust in institutions | + |
| Public services | + |
| Embezzlement (Mauro 1995) | − |
| Crime | − (diminishing) |
| Resource scarcity | − |

Each factor's total over the run is reported as its contribution to growth. [Equation A21](#a21-productivity-growth).

**Civitas Development Index (CDI).** In the spirit of the UN Human Development Index, it is the geometric mean of six dimensions, each scaled 0 to 1:

| Dimension | Measure |
|---|---|
| Health | life expectancy, from 20 to 85 |
| Knowledge | mean years of schooling, ages 25–64, out of 18 |
| Living standard | real median income (income ÷ price of essentials), log scale |
| Equality | 1 − income Gini |
| Cohesion | average of institutional trust, cooperation rate and safety |
| Sustainability | resource stock ÷ capacity |

**Verdict.** The annual growth rate of the CDI is measured after a 5-year settling-in period. The founders start healthier and less stressed than the long-run state, which would otherwise bias every trend downwards.

| Verdict | Rule |
|---|---|
| **Collapse** | population or CDI down 25% or more, or the resource ends below 10% while the CDI falls |
| **Rapid growth** | CDI growing at least 0.5% a year |
| **Growth** | at least 0.1% a year |
| **Stagnation** | between −0.1% and +0.1% a year |
| **Decline** | −0.1% a year or worse |

The report lists the factors that contributed at least ±2% of cumulative growth as things to **boost** or **fix**. Crime, corruption and scarcity can only subtract, so a society is never praised for crime.

---

## 12. Measurement

*Code: `metrics.py`*

| Statistic | Definition |
|---|---|
| Gini coefficient | 0 = equal, 1 = one person has everything ([A22](#a22-development-index-and-gini)) |
| Top 10% share | wealth held by the richest tenth |
| Relative poverty | share below 50% of median net income (OECD) |
| Life expectancy | abridged period life table (Chiang 1984), 10-year rolling window |
| Fertility rate | sum of age-specific rates, ages 15–49 |
| Mobility | rank-rank slope: child's income rank on parents' income rank (Chetty et al. 2014) |
| Polarisation | spread of ideology, plus a bimodality coefficient |
| Echo chambers | correlation of ideology across close ties |
| Segregation | dissimilarity index, poorest 40% vs richest 20% (Duncan & Duncan 1955) |
| Clustering | average local clustering coefficient, sample of 100 |

---

## 13. Does it match reality?

Averages over four 40-year runs (600 founders, default policy). This calibration was done in version 1.0, before the shared resource (§10) and endogenous growth (§11) were added. Their defaults were chosen to leave the baseline close to these values (a sustainable regulated commons and modest growth), but this has not been re-verified across seeds.

| Quantity | Simulated | Real-world reference |
|---|---|---|
| Unemployment | ~6%, peaks 11–13% in recessions | OECD average 5–7% |
| Wealth Gini | ~0.61 | Europe 0.65–0.75; USA ~0.85 |
| Income Gini | ~0.39 | OECD 0.30–0.40 |
| Top 10% wealth share | ~43% | Europe 50–60% |
| Relative poverty | ~12% | OECD ~11% |
| Property crime per 1,000 a year | 26–38 | USA ~20 (reported) |
| Incarceration per 100k | 380–1,000 | USA ~530; Europe ~100 |
| 3-year reconviction | 33–46% | 40–50% in many countries |
| Life expectancy | ~77.8 | 76–83 |
| Total fertility | 1.7–2.2 | 1.5–1.9 in rich countries |
| Life satisfaction | ~7.4 / 10 | 6.5–7.8 in rich countries |
| Public debt ÷ annual labour income | 0.5–1.4 | debt/GDP 60–120% in many OECD countries |
| Mobility slope | ~0.16 (8-seed mean; single runs 0.07–0.29) | Denmark 0.18, USA 0.34 |
| Conspiracy believers | 6–19% | varies widely by theory |

The model underestimates wealth concentration at the very top, because it has no housing market or corporate ownership. Mobility varies from run to run because only about 230 people per run are old enough to measure, so policy comparisons average over several seeds.

---

## 14. Limitations

- **A model, not a forecast.** Parameters come from the literature or were calibrated by hand, not estimated from micro data. Its value lies in making mechanisms explicit and allowing comparisons, not in point predictions.
- **Personality is not destiny.** Traits shift probabilities. Luck and circumstance (parents, district, the business cycle) matter as much as they do in life, and the "what predicts success" regression usually explains under a quarter of the variance.
- **Simplifications.** Two sexes are modelled for reproduction, with 4% of people forming same-sex partnerships. There is one ideological dimension, one conspiracy theory and one town, with no migration, no housing market, no firms as agents and no inflation. People cannot choose how many hours to work.
- **Sensitive topics.** Crime, trauma and mental health are represented with established social-science models. The original prototype's suicide mechanic was replaced by a mental-health-crisis model with treatment, which is closer to how public health frames the problem and lets policy matter.

---

## 15. Built-in studies

*Code: `studies.py`, `scenarios.py`*

- **Scenario presets** (`python main.py scenarios`) combine population personality (trait shifts placed in the genes, so they are inherited) with rules. Examples: `boom`, `collapse`, `tragedy_of_the_commons`, `ostrom`, `corruption`, `knowledge_economy`.
- **Lever analysis** (`python main.py levers`) is a one-at-a-time sensitivity test. Twelve factors (six policies, four personality traits, resource regrowth and resource governance) are pushed from low to high on the same seeds, and paired differences rank them in a tornado chart.
- **Commons study** (`python main.py commons`) runs 5 allocation rules × 3 behaviour profiles on a fragile resource. See [RESEARCH_QUESTION.md](RESEARCH_QUESTION.md).

---

# Appendix: equations

**Notation.**
- σ(x) = 1/(1 + e^(−x)) is the logistic function. Φ is the standard normal CDF.
- clip(x, a, b) limits x to the range [a, b].
- Traits: H, N, X, A, C, O, G (see §1). θ is trust in institutions. b is conspiracy belief.
- w is closeness. T is trust in a specific person. m is the number of mutual friends.
- ε is a small random shock.

### A1. Inheritance

Trait = genetic value + environment, where the genetic value is g and the environment is e. Fisher's infinitesimal model:

$$
\text{founders: } g \sim \mathcal N(0, h^2), \quad e \sim \mathcal N(0, 1-h^2)
$$

$$
\text{children: } g_c = \tfrac12 (g_m + g_f) + \mathcal N\!\left(0, \tfrac{h^2}{2}\right), \quad e_c \sim \mathcal N(0, 1-h^2)
$$

The extra variance $h^2/2$ keeps the genetic variance constant across generations, so the slope of offspring on mid-parent equals $h^2$ (tested in `tests/test_traits.py`).

### A2. Cooperation

$$
U^{\text{coop}}_{ij} = 1.1 + 0.8H_i + 0.5A_i + 2.0\,(2T_{ij} - 1) + 1.0\,w_{ij} + 0.25\ln(1 + m_{ij}) - 0.45\,\text{stress}_i - 0.6\,\text{strain}_i
$$

$$
P(\text{cooperate}) = \sigma\big(U^{\text{coop}}_{ij}\big), \qquad T_{ij} = \frac{\alpha_{ij}}{\alpha_{ij} + \beta_{ij}}
$$

Here $\alpha_{ij}$ and $\beta_{ij}$ are person i's Beta-distribution counts of j's cooperation and defection.

### A3. Learning, reputation and support

Trust (a discounted Beta-Bernoulli update; Jøsang & Ismail 2002), where $c = 1$ if the other person cooperated and 0 if not:

$$
\alpha \leftarrow 0.93\,\alpha + c, \qquad \beta \leftarrow 0.93\,\beta + (1 - c)
$$

Closeness, with a negativity bias:

$$
w \leftarrow w + 0.07\,(1 - w) \ \text{ after kindness}, \qquad w \leftarrow w - 0.22\,w \ \text{ after exploitation}
$$

Public reputation, and the chance an encounter is witnessed:

$$
R \leftarrow R + 0.05\,(c - R), \qquad P(\text{seen}) = 1 - (1 - 0.08)^{1 + m}
$$

Gossip: each listener k told by teller t raises distrust of the defector:

$$
\beta_{k,\text{defector}} \leftarrow \beta_{k,\text{defector}} + 0.6\,T_{k,t}
$$

Trust prior when meeting a stranger, and social support:

$$
T_0 = \tfrac12\,T^{\text{general}}_i + \tfrac12\,R_j, \qquad \text{support}_i = \ln\!\Big(1 + \sum_j w_{ij}\,T_{ij}\Big)
$$

Ties without contact decay as $w \leftarrow w\,e^{-0.05}$ each month.

### A4. Opinion change

Let $d = o_j - o_i$ and let $\varepsilon_i = 0.45\,(1 + 0.5\tanh O_i)$ be the open-mindedness threshold. After a discussion:

$$
o_i \leftarrow
\begin{cases}
o_i + 0.06\,T_{ij}\,d & \text{if } \lvert d\rvert < \varepsilon_i \quad \text{(assimilation)}\\
o_i - 0.04\,(1 - T_{ij})\,d & \text{if } \lvert d\rvert > 0.6 \text{ and } T_{ij} < \tfrac12 \quad \text{(backfire)}\\
o_i & \text{otherwise}
\end{cases}
$$

Stubbornness, applied monthly towards the anchor view $a_i$:

$$
o \leftarrow o + 0.10\,(a - o)
$$

Newborn anchor: $a = \tfrac14(o_m + o_f) + 0.8\tanh\!\big(0.3C - 0.7O + 0.6(2\,\text{class} - 1) + \varepsilon\big)$.

Ties after discussion: $w \leftarrow w + 0.03(1 - w)$ on agreement and $w \leftarrow w - 0.08\,w$ on strong disagreement.

### A5. Conspiracy belief

Susceptibility (the ceiling on belief):

$$
s_i = \sigma\big(-1.2 + 0.6N_i - 0.8G_i - 0.3O_i + 2.5(\tfrac12 - \theta_i) + 0.5\,\text{stress}_i\big)
$$

Monthly updates to belief $b_i$:

$$
\begin{aligned}
\text{hearing a believer } (b_j > 0.5):\quad & b_i \leftarrow b_i + 0.25\,T_{ij}\max(0,\ s_i - b_i)\\
\text{media exposure:}\quad & b_i \leftarrow b_i + 0.04\,(1 + 3\,\text{prevalence})\max(0,\ s_i - b_i)\\
\text{debunking:}\quad & b_i \leftarrow b_i - 0.15\,T_{ij}\,(1 - s_i)\,b_i\\
\text{forgetting:}\quad & b_i \leftarrow 0.98\,b_i
\end{aligned}
$$

A believer shares with probability $0.4\,b_j$. A debunker acts with probability $0.3\,\Phi(G_j)$. New theories arrive at 4 a year × (1 + 1.5 × recession + 2 × recent scandal).

### A6. Schooling

With $\pi$ = parents' income percentile, $q$ = school quality and $\sigma_E$ = the education subsidy:

$$
\begin{aligned}
P(\text{stay after 16}) &= \sigma\big(2.3 + 0.9G + 0.6C + 1.5(\pi - \tfrac12) + q - \text{strain}\big)\\
P(\text{university at 18}) &= \sigma\big(0.15 + 1.1G + 0.6C + 0.4O + 2.5(\pi - \tfrac12) + q - 2.4(1 - \sigma_E)(1 - \pi) - 0.8\,\text{strain}\big)\\
P(\text{postgraduate at 22}) &= \sigma\big(-2.2 + G + 0.5C + 0.5O + (\pi - \tfrac12)\big)
\end{aligned}
$$

School quality is $q = 0.8\,(h_d - 1)$, where $h_d$ is the district's housing multiplier. The term $2.4(1 - \sigma_E)(1 - \pi)$ is the tuition barrier, which weighs most on poorer families.

### A7. Wages

The Mincer earnings equation:

$$
\ln w_i = \ln(3000\,m_k) + 0.08\,(\text{school}_i - 12) + 0.035\,\text{exp}_i - 0.0006\,\text{exp}_i^2 + 0.06C_i + 0.05G_i + 0.03X_i + u_i
$$

Here $m_k$ is the occupation multiplier, $\text{exp}$ is years of experience and $u_i \sim \mathcal N(0, 0.22^2)$ is persistent wage luck. Experience pays most at $0.035 / (2 \times 0.0006) \approx 29$ years. Entrepreneurs' pay has extra lognormal volatility of 0.35.

### A8. Jobs

$$
P(\text{job loss}) = 0.012\,e^{-0.3C - 0.15G} \times 1.6^{\,\text{recession}}
$$

$$
P(\text{job found}) = 0.10\,e^{\,0.25C + 0.15G + 0.05(\text{school} - 12) + 0.25\ln(1 + k_i) - 0.7\,\mathbb 1[\text{recent conviction}]} \times 0.7^{\,\text{recession}}
$$

$k_i$ counts employed contacts (weak ties count double). "Recent" means a conviction in the last 7 years. Occupations are chosen by multinomial logit among vacancies the person qualifies for, with utility $\text{trait fit} + 1.5\ln m_k + 0.3\,(\text{school}^{\min}_k - 12)/4$.

### A9. Taxes, spending and wealth

Income tax on monthly income $y$, with base rate $\tau$ and top rate $\tau_{\text{top}}$:

$$
\text{tax}(y) = \tau\max(0,\ y - 1000) + \tau_{\text{top}}\max(0,\ y - 10000)
$$

Spending (buffer-stock behaviour):

$$
\text{spend} = \text{essentials} + \text{mpc}^{\text{eff}}\max(0,\ \text{net} - \text{essentials}) + 0.0025\max(0,\ W)
$$

$$
\text{mpc}^{\text{eff}} = \text{mpc}_i + 0.25\,(\tfrac12 - \text{income percentile}), \qquad \text{mpc}_i = \text{clip}(0.88 - 0.12C_i + \varepsilon,\ 0.35,\ 0.95)
$$

Essentials cost $1150\,(0.5 + 0.5\,h_d)$, scaled by 0.75 per partner in a couple, plus $450 per dependent child.

Return on positive wealth $W$ (a Kesten process, which produces a Pareto tail):

$$
r = \phi\,(\mu + \sigma\epsilon) + (1 - \phi)\,r_{\text{safe}}, \qquad \phi = \min\!\Big(0.95,\ 1.4\,\rho_i\,\frac{W}{W + 30000}\Big)
$$

with $\mu = 7\%$ and $\sigma = 20\%$ a year, and $\rho_i = \text{clip}(0.5 + 0.15O_i - 0.15N_i + \varepsilon,\ 0.05,\ 0.95)$ the person's risk tolerance.

**Money conservation.** Every change of money is a zero-sum transfer or a logged external flow, so at all times:

$$
\sum_i W_i + W_{\text{gov}} = W_0 + \sum \text{external flows}
$$

### A10. Crime

$$
\begin{aligned}
U^{\text{crime}}_i = {}& -7.5 + 1.8\,\text{strain} + 0.7\,\text{unemployed} - 0.9H - 0.45C - 0.35A + 0.25N\\
& + 0.8\,\mathbb 1[15 \le \text{age} < 30] + 0.45\,\mathbb 1[\text{male}] + 2.0\,\text{peers} + 0.7\,\mathbb 1[\text{record}]\\
& - 3.0\,p_{\text{arrest}}\,p_{\text{convict}}\,\frac{\text{sentence}}{12} - 1.2\,(2\theta_i - 1)
\end{aligned}
$$

$$
P(\text{offend}) = \sigma\big(U^{\text{crime}}_i\big)
$$

$\text{peers}$ is the closeness-weighted share of contacts who offended in the last 3 years. The sentence is in months. Because $\text{peers} \in [0, 1]$, the probability with $\text{peers} = 1$ is an upper bound, so the network is scanned only when a random draw falls below it. This shortcut is exact.

Fraud, after a defection:

$$
P(\text{fraud}) = \sigma(-5.8 - 1.2H + 1.2\,\text{strain} - 1.5\,w)
$$

Assault, as retaliation after being exploited:

$$
P(\text{assault}) = \sigma(-8.9 - A + 0.6N + 0.8\,\text{stress} - 0.5C + 0.9\,\mathbb 1[\text{male and under 30}])
$$

### A11. Policing and bribes

$$
p_{\text{arrest}} = \min\!\Big(0.9,\ \big(1 - e^{-0.085 \times \text{officers per 1000}}\big) \times \text{efficiency} \times \big(0.8 + 0.4\,\overline{\Phi(G)}_{\text{police}}\big)\Big)
$$

An officer takes a bribe with probability $\sigma(-2.6 - 1.5H_{\text{officer}})$.

### A12. Stress and health

$$
\text{stress} \leftarrow \text{stress} + \underbrace{0.30\,\text{strain} + 0.25\,\text{unemployed} + 0.06\,\text{conflicts} + 0.35\,\text{prison} + 0.15\,\text{crisis}}_{\text{inflow}} - r \cdot \text{stress}
$$

$$
r = \min\!\big(0.9,\ 0.14\,(1 + 0.3\,\text{support} + 0.25C)\,e^{-0.25N} \times (2 \text{ if treated})\big)
$$

The long-run stress level is inflow ÷ r. Health $h$ drifts towards the age norm $h^{\text{ref}}$:

$$
h \leftarrow h + 0.05\,(h^{\text{ref}} - h) - 0.006\,\text{stress} - 0.004\,\text{strain} + \varepsilon, \qquad h^{\text{ref}} = 1 - 0.009\max(0,\ \text{age} - 30)
$$

### A13. Mental-health crises

$$
P(\text{crisis}) = \sigma\big(-7.3 + \text{stress} + 0.6N + 1.5\,\text{trauma} - 0.35\,\text{support}\big)
$$

$$
P(\text{treated}) = \big(1 - e^{-\text{budget}/12}\big) \times \text{efficiency}, \qquad P(\text{recover}) = 0.12\,(1 + 1.5\,\text{treated})(1 + 0.15\,\text{support})
$$

Trauma decays with a half-life of 36 months (12 with treatment).

### A14. Life satisfaction

$L$ moves towards a set point $L^*$ (an Ornstein–Uhlenbeck process):

$$
L \leftarrow L + 0.15\,(L^* - L) + \mathcal N\big(0,\ (0.25\,(1 + 0.3\max(0, N)))^2\big)
$$

$$
\begin{aligned}
L^* = {}& 6.9 + 0.45\ln\frac{\text{income}}{\text{neighbours' income}} + 0.6\,(\text{support} - 1.5) + 0.35\,\text{partnered} - 0.7\,\text{unemployed}\\
& - 0.35N + 0.15X + 1.5\,(h - h^{\text{ref}}) - 0.5\,(1 - h^{\text{ref}}) - 1.2\,\text{strain} - 1.2\,\text{prison}\\
& - 0.8\,\text{trauma} - \text{crisis} + 0.3\tanh(\text{social payoff}/5) + 0.3\,(\theta - \tfrac12)
\end{aligned}
$$

Events also move $L$ directly (birth +0.6, marriage +0.5, job loss −0.8, divorce −0.9, bereavement −1.5), and the pull towards $L^*$ then erases most of the shock.

### A15. Mortality

$$
\mu_i(x) = \big[0.0004 + 0.000035\,e^{0.092x}\big] \times e^{\,3\,(h^{\text{ref}}(x) - h_i) - 0.08C_i}, \qquad P(\text{death}) = 1 - e^{-\mu_i/12}
$$

Mortality doubles every $\ln 2 / 0.092 \approx 7.5$ years of age.

### A16. Fertility and divorce

For a partnered woman aged 18–45, per year:

$$
f = 0.46\,e^{-((\text{age} - 30)/6.5)^2} \times \text{desire} \times \text{security}
$$

$$
\text{desire} = \text{clip}\Big(\frac{\text{ideal} - \text{children}}{\text{ideal}},\ 0,\ 1\Big) + 0.03, \qquad \text{security} = 0.6 + 0.8\,\sigma\big(2(\pi - 0.4) - 2\,\text{strain}\big)
$$

A partnership forms with probability $0.12 \times \text{attraction}$, where attraction $= 0.6\,w + 0.4\,S_{ij}$ and $S_{ij}$ is the similarity kernel. Relationship quality $q$ moves towards a set point $q^*$, and divorce has monthly hazard:

$$
q^* = 0.75 + 0.04(A_a + A_b) - 0.04(N_a + N_b) - 0.06(\text{stress}_a + \text{stress}_b) - 0.15\max\text{strain} + 0.1\,(S_{ab} - \tfrac12) - 0.2\,\text{prison}
$$

$$
P(\text{divorce}) = 0.0016\,e^{-5\,(q - 0.6)}
$$

### A17. Trust in institutions

$$
\theta \leftarrow \theta + 0.05\,(\theta^* - \theta)
$$

$$
\theta^* = 0.66 - 0.3\,\lvert o_i - o_{\text{mayor}}\rvert - 0.15\,\text{unemployed} - 0.1\,\text{recession} - 0.15\,b_i - 0.1\,\text{strain} - 0.15\,\text{recent victim} + 0.5\,(\text{efficiency} - 0.9)
$$

### A18. Voting

$$
P(\text{vote}) = \sigma\big(-0.4 + 0.03(\text{age} - 40) + 0.15(\text{school} - 12) + 3(\theta - \tfrac12) + 0.3C\big)
$$

Vote choice is a multinomial logit over candidates c (probabilistic spatial voting):

$$
U_{ic} = -3\,(o_i - o_c)^2 + 2\,(R_c - \tfrac12) + 0.35\,X_c + \big[1.5\,(T_{ic} - \tfrac12) + w_{ic}\big]_{\text{if acquainted}} + 1.5\,(2\theta_i - 1)\,\mathbb 1[c = \text{incumbent}]
$$

Candidate ambition:

$$
\text{ambition} = 0.5X + 0.3C - 0.15H + 1.5\,(R - \tfrac12) + 0.4\ln\!\big(1 + \textstyle\sum w\big) + \varepsilon
$$

### A19. Corruption and the fiscal rule

Each month a mayor skims 6% of tax revenue with probability:

$$
P(\text{skim}) = \big(1 - \Phi(H_{\text{mayor}})\big)^4
$$

Each skim is detected with probability 0.02. Policy lever examples for a mayor at ideology $o$: income tax $\tau_0 - 0.10\,o$, top tax $\tau_0^{\text{top}} - 0.08\,o$, education subsidy $0.5 - 0.35\,o$, police per 1,000 × $(1 + 0.35\,o)$. Administrative efficiency is $0.8 + 0.12\,\Phi(C) + 0.08\,\Phi(G)$.

In policy experiments (`lock_policy`), a continuous fiscal reaction function (Bohn 1998) adjusts the tax rate:

$$
\tau \leftarrow \tau - 0.6\,\frac{\text{annual balance}}{\text{labour income}} - 0.05\,\frac{\text{treasury}}{\text{labour income}}
$$

### A20. Shared resource

Stock $R$ with capacity $K = 60 \times$ founding population, regrowth rate $r = 0.04$ a month and harvest $H_t$:

$$
R_{t+1} = R_t + rR_t\Big(1 - \frac{R_t}{K}\Big) - H_t, \qquad \text{MSY} = \frac{rK}{4}
$$

Desired harvesting effort of person $i$:

$$
e_i = e_0\,e^{-0.35H_i - 0.25A_i + 0.5\,\text{strain}_i} \times (1.4 \text{ if unemployed, else } 0.7) \times \big(1 + 0.8\,\text{scarcity} \cdot \max(0, -H_i)\big)
$$

Catch per person: $h_i = e_i \min(1,\ R / 0.8K)$.

Quota, and the chance of obeying it:

$$
Q = \max\!\Big(0,\ rR\Big(1 - \frac{R}{K}\Big) + 0.05\,(R - 0.6K)\Big) \big/ \text{(number of harvesters)}
$$

$$
P(\text{comply}) = \sigma\big(1.0 + 1.5H_i + 2(\theta_i - \tfrac12) + 3\,p_{\text{arrest}} - 0.8\,\text{strain}_i + 2 \cdot \mathbb 1[\text{private}]\big)
$$

Non-compliers take what they want and are fined with probability $p_{\text{arrest}}/2$.

Price of essentials as the resource runs down (Brander & Taylor 1998):

$$
\text{price} = 1 + 0.6\,\text{clip}\!\Big(\frac{0.6 - R/K}{0.6},\ 0,\ 1\Big)
$$

### A21. Productivity growth

Each year, productivity $A \leftarrow A\,e^{g}$ with $g$ capped at ±6%:

$$
\begin{aligned}
g = {}& 0.011 + 0.010\,(\bar{\text{school}} - 12.5) + 0.010\,\overline{(O + G)/2} + 0.040\,(\text{cooperation rate} - 0.945)\\
& + 0.030\,(\bar\theta - 0.46) - 0.5\,\frac{\text{embezzled}}{\text{tax revenue}} + 0.010\ln\frac{\text{public services}}{320}\\
& - 0.0045\ln\!\Big(1 + \frac{\max(0,\ \text{property} + 3\,\text{assault} - 15)}{15}\Big) - 0.040\,\overline{\text{scarcity}}
\end{aligned}
$$

Bars denote averages over workers or the whole population, and crime rates are per 1,000. When the ±6% cap binds, the terms are scaled proportionally, so the reported contributions add up to the growth that actually happened.

### A22. Development index and Gini

$$
\text{CDI} = \Big(\prod_{k=1}^{6} d_k\Big)^{1/6}
$$

where the six dimensions $d_k \in [0, 1]$ are:

$$
\begin{aligned}
d_{\text{health}} &= \frac{e_0 - 20}{65}, \qquad d_{\text{knowledge}} = \frac{\bar{\text{school}}}{18}, \qquad d_{\text{living}} = \frac{\ln(\text{real median income} / 400)}{\ln 30}\\
d_{\text{equality}} &= 1 - G_{\text{income}}, \qquad d_{\text{sustainability}} = \frac{R}{K}\\
d_{\text{cohesion}} &= \text{mean}\Big(\bar\theta,\ \text{cooperation rate},\ 1 - \frac{\text{property} + 3\,\text{assault}}{150}\Big)
\end{aligned}
$$

Growth of the CDI is the OLS slope of $\ln \text{CDI}$ on time. Gini coefficient, with values $x_{(1)} \le \dots \le x_{(n)}$ sorted (net worth floored at 0):

$$
G = \frac{2\sum_{i=1}^{n} i\,x_{(i)}}{n\sum_{i=1}^{n} x_{(i)}} - \frac{n + 1}{n}
$$

---

## References

Ashton & Lee (2007) *Pers. Soc. Psychol. Rev.* · Barro (1991) Economic growth in a cross section of countries · Baumeister et al. (2001) Bad is stronger than good · Becker (1968) Crime and punishment: an economic approach · Brander & Taylor (1998) The simple economics of Easter Island · Brickman, Coates & Janoff-Bulman (1978) · Carroll (1997) Buffer-stock saving · Chetty, Hendren, Kline & Saez (2014) Where is the land of opportunity? · Chiang (1984) The Life Table · Coleman (1988) Social capital in the creation of human capital · Deffuant et al. (2000) Mixing beliefs among interacting agents · Downs (1957) · Duncan & Duncan (1955) · Fagereng et al. (2020) Heterogeneity and persistence in returns to wealth · Fisher (1918) The correlation between relatives · Friedkin & Johnsen (1990) · Gerber et al. (2010) Personality and political attitudes · Gottfredson & Hirschi (1990) A General Theory of Crime · Granovetter (1973) The strength of weak ties · Hamilton (1989) · Hardin (1968) The tragedy of the commons · Hatemi et al. (2014) · Holme & Newman (2006) Nonequilibrium phase transition in the coevolution of networks and opinions · Jager & Amblard (2005) · Jennings & Niemi (1968) · Jøsang & Ismail (2002) The Beta reputation system · Kern & Friedman (2008) · Knack & Keefer (1997) Does social capital have an economic payoff? · Krosnick & Alwin (1989) · Lindbeck & Weibull (1987) · Lochner & Monge-Naranjo (2012) Credit constraints in education · Lucas (2007) · Luttmer (2005) Neighbors as negatives · Marmot (2005) Social determinants of health inequalities · Mauro (1995) Corruption and growth · McEwen (1998) · McFadden (1974) · McPherson, Smith-Lovin & Cook (2001) Birds of a feather · Mincer (1974) · Nowak & Sigmund (1998) Evolution of indirect reciprocity by image scoring · Ostrom (1990) Governing the Commons · Pager (2003) The mark of a criminal record · Psacharopoulos & Patrinos (2018) · Schaefer (1954) · Schelling (1971) · Sutherland (1947) · Tyler (1990) Why People Obey the Law · UNDP Human Development Index · Uscinski, Klofstad & Atkinson (2016) · van Prooijen & Douglas (2017) · Vukasović & Bratko (2015)
