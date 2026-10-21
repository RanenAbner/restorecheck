"""Export the RestoreCheck demo dataset (for publishing on Zenodo) into dataset/.

    python scripts/export_dataset.py

Writes the deterministic demo shop tables as CSV, the recorded scenario results,
the integrity expectations and a README describing everything.
"""
import csv
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import demo_data  # noqa: E402
from checks import canary  # noqa: E402

OUT = ROOT / "dataset"
COLUMNS = {
    "customers": ["id", "name", "email"],
    "products": ["id", "name", "price"],
    "orders": ["id", "customer_id", "created_at"],
    "order_items": ["id", "order_id", "product_id", "quantity"],
    canary.TABLE: ["id", "payload"],
}

README = """# RestoreCheck demo dataset

Synthetic data and recorded results from **RestoreCheck**, an automated backup
recoverability verification system on AWS (https://github.com/RanenAbner/restorecheck).

## Contents
| File | Description |
|---|---|
| `tables/customers.csv` | {customers} synthetic customers |
| `tables/products.csv` | {products} products with prices |
| `tables/orders.csv` | {orders} orders, each referencing a customer |
| `tables/order_items.csv` | {order_items} order lines, each referencing an order and a product |
| `tables/restorecheck_canary.csv` | {canary} fixed "canary" rows whose MD5 checksum (`{checksum}`) proves content integrity |
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
"""


def main():
    data = demo_data.generate()
    tables = OUT / "tables"
    tables.mkdir(parents=True, exist_ok=True)
    for table, columns in COLUMNS.items():
        with (tables / f"{table}.csv").open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(columns)
            for row in data[table]:
                writer.writerow([v.isoformat() if hasattr(v, "isoformat") else v for v in row])

    shutil.copy(ROOT / "src" / "checks" / "expectations.json", OUT / "expectations.json")
    shutil.copy(ROOT / "results" / "scenarios.json", OUT / "scenario_results.json")
    shutil.copy(ROOT / "results" / "scenarios.md", OUT / "scenario_results.md")
    (OUT / "README.md").write_text(
        README.format(
            customers=len(data["customers"]),
            products=len(data["products"]),
            orders=len(data["orders"]),
            order_items=len(data["order_items"]),
            canary=len(data[canary.TABLE]),
            checksum=canary.expected_checksum(),
        ),
        encoding="utf-8",
    )
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
