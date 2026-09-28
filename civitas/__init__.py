"""Civitas: an agent-based model of a human society built from explicit,
research-grounded equations of individual behaviour.

    >>> from civitas import SimConfig, Simulation
    >>> sim = Simulation(SimConfig(seed=7, years=30)).run()
    >>> sim.summary()["gini_wealth"]
"""
from .config import Policy, SimConfig
from .simulation import Simulation

__all__ = ["Policy", "SimConfig", "Simulation"]
__version__ = "1.1.0"
