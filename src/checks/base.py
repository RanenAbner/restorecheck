"""Shared types and helpers for integrity checks."""
import re
from dataclasses import dataclass, field

_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")


@dataclass(frozen=True)
class RestoreTarget:
    """What a check gets to inspect.

    snapshot/instance: JSON summaries from the pipeline (restore.py *_summary).
    db: an open DB-API connection to the restored database (None before connecting).
    expectations: the parsed checks/expectations.json.
    """

    snapshot: dict
    instance: dict
    db: object = None
    expectations: dict = field(default_factory=dict)


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    detail: str


def run_checks(checks, target):
    """Run every check, even after one fails, so the report shows the full picture."""
    results = []
    for check in checks:
        try:
            results.append(check(target))
        except Exception as err:
            # A check that crashes could not verify the backup, so it counts as failed.
            results.append(
                CheckResult(check.__name__, False, f"check raised {type(err).__name__}: {err}")
            )
    return results


def query(db, sql):
    cursor = db.cursor()
    try:
        cursor.execute(sql)
        return cursor.fetchall()
    finally:
        cursor.close()


def describe_db_error(err):
    """A readable one-liner for a database error. The pg8000 driver puts the
    server's fields in a dict (M = message, C = SQLSTATE code); show just those."""
    fields = err.args[0] if err.args and isinstance(err.args[0], dict) else None
    if fields and "M" in fields:
        code = f" [{fields['C']}]" if "C" in fields else ""
        return f"{fields['M']}{code}"
    return f"{type(err).__name__}: {err}"


def quote_identifier(name):
    """Quote a table name for SQL. Only plain lowercase names are accepted, so a
    typo in expectations.json can never turn into arbitrary SQL."""
    if not _IDENTIFIER.match(name):
        raise ValueError(f"Unsupported table name: {name!r}")
    return f'"{name}"'
