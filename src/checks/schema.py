"""Check: every expected table exists (catches backups that silently dropped a table)."""
from checks.base import CheckResult, query

NAME = "tables_present"
SQL = "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"


def check_tables_present(target):
    expected = set(target.expectations["tables"])
    found = {row[0] for row in query(target.db, SQL)}
    missing = sorted(expected - found)
    if missing:
        return CheckResult(NAME, False, f"missing tables: {', '.join(missing)}")
    return CheckResult(NAME, True, f"all {len(expected)} expected tables present")
