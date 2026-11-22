"""
Temps de cada fase d'una execució: el log diu quant ha durat cada fase i
l'acumulat, i al final es pot imprimir el resum.

  - `format_duration`: segons en text llegible (`1 h 03 min 05 s`).
  - `PhaseClock`: cronòmetre de fases.
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager

log = logging.getLogger(__name__)

SKIPPED = None
"""Durada d'una fase que no s'ha executat."""


def format_duration(seconds: float) -> str:
    """
    :param seconds: durada en segons.
    :return: la durada en text: `0,4 s`, `12 s`, `3 min 05 s` o `1 h 03 min 05 s`.
    """
    if seconds < 10:
        return f"{seconds:.1f} s".replace(".", ",")
    total = int(round(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours} h {minutes:02d} min {secs:02d} s"
    if minutes:
        return f"{minutes} min {secs:02d} s"
    return f"{secs} s"


class PhaseClock:
    """
    Cronòmetre de les fases d'una execució. Cada fase es mesura amb `phase`,
    i les que no s'executen es marquen amb `skip`.
    """

    def __init__(self) -> None:
        self.durations: dict[str, float | None] = {}

    @property
    def total(self) -> float:
        """:return: la suma de les fases executades, en segons."""
        return sum(d for d in self.durations.values() if d is not None)

    @contextmanager
    def phase(self, name: str):
        """
        Mesura una fase i, en acabar, en diu la durada i l'acumulat al log.

        :param name: nom de la fase (p.e. `Fase 2`).
        """
        start = time.perf_counter()
        try:
            yield
        finally:
            self.durations[name] = time.perf_counter() - start
            log.info(f"{name} acabada en {format_duration(self.durations[name])} "
                     f"(acumulat {format_duration(self.total)})")

    def skip(self, name: str) -> None:
        """:param name: fase que no s'executa."""
        self.durations[name] = SKIPPED

    def summary_lines(self) -> list[str]:
        """
        :return: una línia per fase, amb la durada i l'acumulat, i la del total.
        """
        lines, accumulated = [], 0.0
        width = max((len(name) for name in self.durations), default=5)
        for name, duration in self.durations.items():
            if duration is None:
                lines.append(f"{name:<{width}}  saltada")
                continue
            accumulated += duration
            lines.append(f"{name:<{width}}  {format_duration(duration):>16}   acumulat {format_duration(accumulated)}")
        lines.append(f"{'Total':<{width}}  {format_duration(self.total):>16}")
        return lines
