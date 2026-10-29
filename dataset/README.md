# RestoreCheck demo dataset

Synthetic data and recorded results from **RestoreCheck**, an automated backup
recoverability verification system on AWS (https://github.com/RanenAbner/restorecheck).

**Authors:** Ranen Abner, Sai Charan, and S. Vigneshwari (Vellore Institute of Technology).

**Cite as:** Ranen Abner, Sai Charan, and S. Vigneshwari, "RestoreCheck demo dataset:
synthetic shop database and backup-verification scenario results," Zenodo, 2026,
doi: 10.5281/zenodo.23772930. https://doi.org/10.5281/zenodo.23772930

## Contents
| File | Description |
|---|---|
| `tables/customers.csv` | 60 synthetic customers |
| `tables/products.csv` | 25 products with prices |
| `tables/orders.csv` | 250 orders, each referencing a customer |
| `tables/order_items.csv` | 600 order lines, each referencing an order and a product |
| `tables/restorecheck_canary.csv` | 100 fixed "canary" rows whose MD5 checksum (`c2ccd15b4107e750ceda7aed4d5af6e4`) proves content integrity |
| `expectations.json` | What a healthy restore must contain (tables, minimum row counts, test queries) |
| `scenario_results.json` / `scenario_results.md` | Outcomes of six verification runs on AWS (ap-southeast-2, db.t3.micro, PostgreSQL 17) |

## How it was produced
The tables are generated deterministically by `scripts/demo_data.py` (random seed 355), so
they are identical on every run. They were loaded into an Amazon RDS for PostgreSQL
database, which was then backed up, deliberately damaged in four ways (missing table,
truncated table, one altered value, orphaned rows) and verified by RestoreCheck after each
backup. The results record, per scenario, the expected and actual outcome, the checks
that failed, the restore time and whether the temporary instance was deleted.

Canary checksum: `md5(string_agg(id::text || ':' || payload, ',' ORDER BY id))` in
PostgreSQL, equivalently MD5 of `1:payload,2:payload,...` ordered by id.

The data is entirely synthetic (no real people or companies). Email addresses use the
reserved `example.com` domain.

## License
Creative Commons Attribution 4.0 International (CC BY 4.0).
