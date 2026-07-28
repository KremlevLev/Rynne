from __future__ import annotations

import asyncio

from tests.orchestrator_acceptance import run_golden_suite


def test_orchestrator_golden_scenarios() -> None:
    results = asyncio.run(run_golden_suite())

    failures = {
        result.name: result.errors
        for result in results
        if not result.passed
    }
    assert not failures, failures
