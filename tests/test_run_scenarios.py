import json

import run_scenarios


def row(name, actual, **extra):
    expected = run_scenarios.SCENARIOS[name][1]
    return {
        "scenario": name,
        "demonstrates": run_scenarios.SCENARIOS[name][2],
        "expected": expected,
        "actual": actual,
        "as_expected": actual == expected,
        "failed_checks": [],
        "restore_seconds": 425.2,
        "total_seconds": 437.0,
        "teardown_ok": True,
        "error": None,
        "execution_id": "run-id",
        "report_key": "key",
        **extra,
    }


def test_results_merge_across_batches_in_scenario_order(tmp_path):
    run_scenarios.write_results([row("corrupt-data", "FAILED")], tmp_path)
    run_scenarios.write_results([row("healthy", "PASSED")], tmp_path)
    run_scenarios.write_results([row("corrupt-data", "PASSED")], tmp_path)  # a re-run replaces

    rows = json.loads((tmp_path / "scenarios.json").read_text())

    assert [(r["scenario"], r["actual"]) for r in rows] == [
        ("healthy", "PASSED"),
        ("corrupt-data", "PASSED"),
    ]


def test_markdown_table_flags_unexpected_outcomes(tmp_path):
    run_scenarios.write_results(
        [
            row("healthy", "PASSED"),
            row("no-backup", "ERROR", teardown_ok=None, restore_seconds=None),
            row("orphaned-rows", "PASSED"),
        ],
        tmp_path,
    )

    table = (tmp_path / "scenarios.md").read_text()

    assert "| healthy |" in table
    assert "n/a (nothing created)" in table
    assert "**PASSED** (UNEXPECTED)" in table
