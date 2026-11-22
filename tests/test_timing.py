"""Tests de `timing`: la durada de cada fase d'una execució."""

import timing


def test_durations_are_readable():
    assert timing.format_duration(0.42) == "0,4 s"
    assert timing.format_duration(12) == "12 s"
    assert timing.format_duration(185) == "3 min 05 s"
    assert timing.format_duration(3785) == "1 h 03 min 05 s"


def test_the_summary_accumulates_the_phases_and_marks_the_skipped_ones(monkeypatch):
    ticks = iter([0.0, 60.0, 100.0, 220.0])
    monkeypatch.setattr(timing.time, "perf_counter", lambda: next(ticks))
    clock = timing.PhaseClock()
    with clock.phase("Fase 0"):
        pass
    clock.skip("Fase 1b")
    with clock.phase("Fase 2"):
        pass

    assert clock.durations == {"Fase 0": 60.0, "Fase 1b": None, "Fase 2": 120.0}
    assert clock.total == 180.0
    lines = clock.summary_lines()
    assert "acumulat 1 min 00 s" in lines[0] and "saltada" in lines[1] and "acumulat 3 min 00 s" in lines[2]
    assert lines[-1].startswith("Total") and "3 min 00 s" in lines[-1]
