from ledgerlens.semantic.layer import load_layer

LAYER = load_layer()


def test_every_metric_uses_documented_tables() -> None:
    undocumented = {m.name: set(m.tables) - LAYER.tables.keys() for m in LAYER.metrics.values()}
    assert {name: tables for name, tables in undocumented.items() if tables} == {}


def test_joins_reference_documented_columns() -> None:
    sides = [side for join in LAYER.joins for side in (join.many, join.one)]
    unknown = [s for s in sides if s.split(".")[1] not in LAYER.tables[s.split(".")[0]].columns]
    assert unknown == []


def test_bridge_tables_complete_the_join_path() -> None:
    assert LAYER.bridge_tables(["customer", "country"]) == ["address", "city"]
    assert LAYER.bridge_tables(["payment", "category"]) == [
        "film",
        "film_category",
        "inventory",
        "rental",
    ]
    assert LAYER.bridge_tables(["payment"]) == []
