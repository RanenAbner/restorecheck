"""Check: a "canary" table's content is byte-for-byte what was written.

Row counts prove data is there, not that it is intact. The seed script writes
these exact rows into the source database; if the restored copy's checksum
differs, the data was altered or corrupted somewhere between write and restore.
"""
import hashlib

from checks.base import CheckResult, query

NAME = "canary_checksum"
TABLE = "restorecheck_canary"
ROWS = tuple((i, f"restorecheck-canary-{i:03d}") for i in range(1, 101))

# Same serialisation on both sides: "1:payload,2:payload,..." ordered by id.
SQL = f"SELECT md5(string_agg(id::text || ':' || payload, ',' ORDER BY id)) FROM {TABLE}"


def expected_checksum(rows=ROWS):
    return hashlib.md5(",".join(f"{i}:{payload}" for i, payload in rows).encode()).hexdigest()


def check_canary_checksum(target):
    ((actual,),) = query(target.db, SQL)
    expected = expected_checksum()
    if actual is None:
        return CheckResult(NAME, False, f"{TABLE} is empty")
    if actual != expected:
        return CheckResult(NAME, False, f"checksum {actual} does not match expected {expected}")
    return CheckResult(NAME, True, f"{len(ROWS)} canary rows intact (md5 {actual})")
