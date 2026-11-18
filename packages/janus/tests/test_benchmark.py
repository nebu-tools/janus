"""Timings against the targets in DESIGN.md. Deselected by default; run with `pytest -m benchmark`.
A step fails at twice its target, so only a large slowdown fails."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "benchmark.py"


@pytest.mark.benchmark
def test_steps_stay_within_twice_their_targets():
    spec = importlib.util.spec_from_file_location("benchmark", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    slow = [t for t in module.measure(100) if t.ratio > 2]
    assert not slow, [f"{t.step}: {t.seconds:.3f} s, target {t.target} s" for t in slow]
