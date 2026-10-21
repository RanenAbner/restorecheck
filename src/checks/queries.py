"""Check: application-level test queries all return true (e.g. no orphaned rows).

Each query in expectations.json must return a single boolean. This is where
"the data is usable by the application" gets tested, beyond "the data exists".
"""
from checks.base import CheckResult, describe_db_error, query

NAME = "test_queries"


def check_test_queries(target):
    queries = target.expectations.get("queries", [])
    failures = []
    for q in queries:
        try:
            rows = query(target.db, q["sql"])
        except Exception as err:
            failures.append(f"{q['name']}: query failed ({describe_db_error(err)})")
            continue
        if not rows or rows[0][0] is not True:
            failures.append(f"{q['name']}: returned {rows[0][0] if rows else 'no rows'!r}")

    if failures:
        return CheckResult(NAME, False, "; ".join(failures))
    return CheckResult(NAME, True, f"all {len(queries)} test queries returned true")
