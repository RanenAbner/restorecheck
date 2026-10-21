"""Integrity checks run against the temporary restored database.

One module per check, each a plain function `check(target: RestoreTarget) ->
CheckResult` that can be unit-tested on its own. checker.py runs
PRE_CONNECT_CHECKS first, then connects and runs SQL_CHECKS.
"""
from checks.canary import check_canary_checksum
from checks.instance_status import check_instance_available
from checks.queries import check_test_queries
from checks.row_counts import check_row_counts
from checks.schema import check_tables_present

PRE_CONNECT_CHECKS = [
    check_instance_available,
]

SQL_CHECKS = [
    check_tables_present,
    check_row_counts,
    check_canary_checksum,
    check_test_queries,
]
