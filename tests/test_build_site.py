import json
from pathlib import Path

import build_site

ROOT = Path(__file__).resolve().parent.parent


def test_page_shows_every_recorded_scenario_and_check():
    rows = json.loads((ROOT / "results" / "scenarios.json").read_text(encoding="utf-8"))

    page = build_site.build(rows, "2026-10-21")

    for row in rows:
        assert f"<strong>{row['scenario']}</strong>" in page
    for name, _ in build_site.CHECKS:
        assert f"<code>{name}</code>" in page
    assert page.count("<tr>") == len(rows) + len(build_site.CHECKS) + 2  # + 2 header rows


def test_stats_count_only_runs_that_created_a_copy():
    rows = [
        {"as_expected": True, "restore_seconds": 420, "teardown_ok": True},
        {"as_expected": True, "restore_seconds": 480, "teardown_ok": True},
        {"as_expected": False, "restore_seconds": None, "teardown_ok": None},
    ]

    s = build_site.stats(rows)

    assert (s["correct"], s["total"]) == (2, 3)
    assert (s["teardowns_ok"], s["teardowns"]) == (2, 2)
    assert s["median_restore_min"] == 7.5


def test_untrusted_text_is_escaped():
    rows = [{
        "scenario": "<script>", "demonstrates": "x", "expected": "PASSED", "actual": "ERROR",
        "as_expected": False, "failed_checks": [], "restore_seconds": None, "teardown_ok": None,
        "error": "<b>boom</b>",
    }]

    page = build_site.build(rows, "2026-10-21")

    assert "<script>" not in page.split("</style>")[1]
    assert "&lt;b&gt;boom&lt;/b&gt;" in page
