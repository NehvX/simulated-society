# Research Question

> **How do different individual behaviours and resource-allocation rules affect inequality and resource availability in a community over time?**

## Why it matters

Communities around the world share resources such as fisheries, grazing land, groundwater and forests.

- **Hardin (1968)** argued that shared resources are doomed. Each user gains the full benefit of taking more but bears only a fraction of the cost. He called this *the tragedy of the commons*.
- **Elinor Ostrom (1990; Nobel Prize 2009)** found that many communities avoid the tragedy through rules they create and enforce themselves.

Which outcome happens depends on two things: **who the people are** (how honest, cooperative and trusting they are) and **the rules** for taking and sharing. Rules that protect a resource can also make it more or less fairly shared.

In the real world you cannot change people and rules separately. In Civitas you can, and then watch what happens over decades.

## The setup

The town shares one renewable resource, such as a fishery, farmland or a forest. Every working-age adult decides how much to take. The study varies two things and runs every combination on the same random seeds:

| Factor | Levels |
|---|---|
| **Allocation rule** | open access · regulated (quota, keep your catch) · equal shares · need-based · private ownership |
| **Behaviour profile** | cooperative (honesty and agreeableness +0.6 s.d.) · average · selfish (−0.6 s.d.) |
| **Seeds** | 3 by default (use `--seeds` for more) |

That is 5 rules × 3 profiles × 3 seeds = 45 runs.

Two details of the setup:
- The resource is deliberately fragile: it regrows 3.5% a month instead of the default 4%.
- The personality shifts are placed in the genes, so children inherit their parents' dispositions and the profile lasts across generations.

## How people behave

- **How much to take.** People who are less honest, less agreeable or more desperate try to take more. When the resource runs low, the least honest panic-grab.
- **Obeying quotas.** Compliance depends on honesty, trust in institutions and the risk of being caught. Desperation makes people break the rules.
- **Scarcity hurts everyone.** A depleted resource makes essentials up to 60% more expensive and slows the town's productivity growth.

The equations are at the [end of this file](#equations). The full model is in [MODEL.md](MODEL.md#10-the-shared-resource).

## What we measure

Every year, the study records:

| Outcome | Measures |
|---|---|
| **Resource availability** | stock as a share of capacity, its lowest point, resource income per adult ($/month) |
| **Inequality** | income Gini, wealth Gini, poverty rate |
| **Overall development** | the Civitas Development Index and the collapse rate |

## Hypotheses

| | Hypothesis | Prediction |
|---|---|---|
| **H1** | Tragedy | Under open access, a selfish population depletes the resource. A cooperative one may not. |
| **H2** | Ostrom | Quota rules keep the resource healthier than open access, but the gain shrinks when people are selfish, because quotas are only as good as compliance. |
| **H3** | Distribution | Pooled rules (equal shares, need-based) give lower inequality than keep-your-catch rules. Private ownership gives the highest inequality, even if it conserves the resource. |
| **H4** | Interaction | Behaviour and rules interact. The best rule for a cooperative town may not be the best for a selfish one. |

## How to run it

```bash
python main.py commons                       # 45 runs, several minutes on a laptop
python main.py commons --seeds 6 --years 50  # more precise
python main.py run --scenario tragedy_of_the_commons    # watch one case in the dashboard
python main.py run --scenario ostrom
python main.py run --rule private_ownership --trait honesty=-0.6 --trait agreeableness=-0.6
```

Results are written to `out/commons/`:

| File | Contents |
|---|---|
| `commons_study.md` | table of means ± 95% confidence intervals for every rule × behaviour combination |
| `commons_report.html` | scatter of inequality against resources left, plus time paths of resource stock, resource income and inequality for each rule (one chart per behaviour profile) |

## How to read the results

- **The scatter is the headline.** The top-left corner (lots of resource, low inequality) is the goal. See which rules land there, and whether the answer changes between cooperative and selfish towns.
- **The time paths show *how* things go wrong**: a slow slide, or a sudden crash once the less honest start to panic-grab. They also show whether inequality rises before or after the resource runs out.
- **Be careful with small differences.** Anything smaller than the confidence intervals is inconclusive. Increase `--seeds` to sharpen it.

## Limitations

- The resource is a single, well-mixed stock with no spatial structure.
- Rules are imposed from outside, not chosen by the community (Ostrom emphasised self-made rules).
- There is no market price for the resource.
- People cannot migrate away from a depleted area.

Each of these could be added as an extension.

---

## Equations

Symbols: $H$ = honesty, $A$ = agreeableness, $\theta$ = trust in institutions, $\sigma(x) = 1/(1 + e^{-x})$. All are z-scores except $\theta$. The full notation is in [MODEL.md](MODEL.md#appendix-equations).

**Resource growth.** With stock $R$, capacity $K = 60 \times$ founding population, growth rate $r = 0.04$ a month (0.035 in this study) and total harvest $H_t$:

$$
R_{t+1} = R_t + rR_t\left(1 - \frac{R_t}{K}\right) - H_t, \qquad \text{MSY} = \frac{rK}{4}
$$

**Desired effort** of person $i$. Less honest, less agreeable and more strained people take more, the unemployed take more, and the dishonest panic when the resource is scarce:

$$
e_i = e_0\,e^{-0.35H_i - 0.25A_i + 0.5\,\text{strain}_i} \times (1.4 \text{ if unemployed, else } 0.7) \times \big(1 + 0.8\,\text{scarcity} \cdot \max(0, -H_i)\big)
$$

**Catch** is proportional to the stock (Schaefer 1954), and each unit is worth $400:

$$
h_i = e_i \min\!\left(1,\ \frac{R}{0.8K}\right)
$$

**Quota.** This month's regrowth plus a correction towards 60% of capacity, split equally among harvesters:

$$
Q = \max\!\Big(0,\ rR\left(1 - \tfrac{R}{K}\right) + 0.05\,(R - 0.6K)\Big) \Big/ \text{(number of harvesters)}
$$

**Compliance.** A harvester who wants more than $Q$ obeys with probability:

$$
P(\text{comply}) = \sigma\big(1.0 + 1.5H_i + 2(\theta_i - \tfrac12) + 3\,p_{\text{arrest}} - 0.8\,\text{strain}_i + 2 \cdot \mathbb 1[\text{private}]\big)
$$

Those who don't comply take what they want and are fined with probability $p_{\text{arrest}}/2$.

**Price of essentials** as the resource runs down:

$$
\text{price} = 1 + 0.6\,\text{clip}\!\left(\frac{0.6 - R/K}{0.6},\ 0,\ 1\right)
$$
