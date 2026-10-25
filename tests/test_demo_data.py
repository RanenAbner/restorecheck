import sys

import pytest

import demo_data
from checks import SQL_CHECKS, canary


@pytest.fixture(scope="module")
def data():
    return demo_data.generate()


def test_generated_data_satisfies_expectations(data, expectations):
    for table, min_rows in expectations["tables"].items():
        assert len(data[table]) >= min_rows, table
    assert data[canary.TABLE] == list(canary.ROWS)


def test_generated_data_has_no_dangling_references(data):
    customers = {row[0] for row in data["customers"]}
    orders = {row[0] for row in data["orders"]}
    products = {row[0] for row in data["products"]}

    assert all(o[1] in customers for o in data["orders"])
    assert all(i[1] in orders and i[2] in products for i in data["order_items"])
    assert all(p[2] >= 0 for p in data["products"])


def test_generation_is_deterministic():
    assert demo_data.generate() == demo_data.generate()


def test_every_table_is_created_and_filled_in_foreign_key_order(data):
    assert set(demo_data.TABLE_ORDER) == set(data)
    order = demo_data.TABLE_ORDER
    assert order.index("customers") < order.index("orders") < order.index("order_items")
    assert order.index("products") < order.index("order_items")


def test_insert_statements_chunk_rows_and_flatten_parameters():
    rows = [(i, f"name {i}") for i in range(5)]

    statements = list(demo_data.insert_statements("t", rows, chunk=2))

    assert [sql.count("(%s, %s)") for sql, _ in statements] == [2, 2, 1]
    assert statements[0][1] == [0, "name 0", 1, "name 1"]


def test_break_scenarios_cover_every_sql_check():
    # Each check module names its results with NAME; the demo should exercise them all.
    check_names = {sys.modules[check.__module__].NAME for check in SQL_CHECKS}

    assert {scenario["trips"] for scenario in demo_data.BREAKS.values()} == check_names


def test_verifier_user_sql_rejects_unsafe_names():
    with pytest.raises(ValueError):
        demo_data.verifier_user_sql("bob; DROP TABLE x", "appdb")


def test_show_marks_changed_canary_rows_and_missing_tables():
    import demo_db
    from checks import canary

    rows = [(i, f"restorecheck-canary-{i:03d}") for i in range(40, 45)]
    healthy = demo_db.format_show("db", {"orders": 250, "order_items": 600}, rows, canary.expected_checksum())
    broken = demo_db.format_show("db", {"orders": 250, "order_items": None},
                                 [(42, "tampered") if r[0] == 42 else r for r in rows], "abc")

    assert "CHANGED" not in healthy and "matches: data intact" in healthy
    assert "42  tampered   <-- CHANGED" in broken
    assert "MISSING" in broken and "DOES NOT MATCH" in broken
