Scenario runs on 2026-10-21 (AWS ap-southeast-2, db.t3.micro, PostgreSQL 17).

| Scenario | Demonstrates | Expected | Actual | Failed checks | Restore (s) | Teardown OK |
|---|---|---|---|---|---|---|
| healthy | Intact backup restores and passes every check | PASSED | **PASSED** | - | 425 | yes |
| missing-table | A table silently missing from the backup | FAILED | **FAILED** | `tables_present`, `row_counts`, `test_queries` | 425 | yes |
| truncated-table | Most rows of a table lost | FAILED | **FAILED** | `row_counts` | 485 | yes |
| corrupt-data | One value altered (rows and counts unchanged) | FAILED | **FAILED** | `canary_checksum` | 425 | yes |
| orphaned-rows | Referential integrity broken | FAILED | **FAILED** | `test_queries` | 425 | yes |
| no-backup | Database has no backup at all | ERROR | **ERROR** | n/a | - | n/a (nothing created) |
