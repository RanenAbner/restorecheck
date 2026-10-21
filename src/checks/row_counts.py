"""Check: each table holds at least its expected number of rows (catches truncated data)."""
from checks.base import CheckResult, describe_db_error, query, quote_identifier

NAME = "row_counts"


def check_row_counts(target):
    counts, problems = {}, []
    for table, min_rows in target.expectations["tables"].items():
        try:
            ((count,),) = query(target.db, f"SELECT count(*) FROM {quote_identifier(table)}")
        except Exception as err:
            problems.append(f"{table}: could not count ({describe_db_error(err)})")
            continue
        counts[table] = count
        if count < min_rows:
            problems.append(f"{table} has {count} rows, expected at least {min_rows}")

    if problems:
        return CheckResult(NAME, False, "; ".join(problems))
    summary = ", ".join(f"{table}={count}" for table, count in counts.items())
    return CheckResult(NAME, True, summary)
