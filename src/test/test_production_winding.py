"""Smallest check for the Winding Production payload normaliser."""

from datetime import date

import pytest
from fastapi import HTTPException

from src.production.winding import _parse_body, _parse_bulk_header, _parse_bulk_lines, _pick_slab

BASE = {"branch_id": "87", "prod_date": "2025-11-30", "eb_id": "1234",
        "wdg_q_id": "2", "prod_hrs": "32"}


def test_parse_body_normalises_sheet_row():
    out = _parse_body({**BASE, "shift": " a ", "prod_kg": "1067", "grist": 9.5})
    assert out == {
        "branch_id": 87, "prod_date": date(2025, 11, 30), "shift": "A",
        "eb_id": 1234, "wdg_q_id": 2, "grist": 9.5,
        "prod_hrs": 32.0, "prod_kg": 1067.0, "unit": "KG", "remarks": None,
    }
    # the DB generated column computes round(rate * prod_hrs, 2); sheet row:
    # 0.41666667 * 32 = 13.33
    assert round(0.41666667 * out["prod_hrs"], 2) == 13.33


def test_parse_body_defaults_shift_and_optionals():
    out = _parse_body(BASE)
    assert (out["shift"], out["grist"], out["prod_kg"], out["unit"]) == ("A", None, None, "KG")
    assert _parse_body({**BASE, "unit": " kg "})["unit"] == "KG"


@pytest.mark.parametrize("bad", [
    {"branch_id": ""}, {"prod_date": ""}, {"prod_date": "30-11-2025"},
    {"eb_id": None}, {"wdg_q_id": ""},
    {"prod_hrs": 0}, {"prod_hrs": ""}, {"prod_hrs": -8}, {"prod_kg": "abc"},
])
def test_parse_body_rejects_bad_input(bad):
    with pytest.raises(HTTPException):
        _parse_body({**BASE, **bad})


def test_parse_bulk_header_and_lines_happy_path():
    header = _parse_bulk_header({"branch_id": "87", "prod_date": "2025-11-30", "shift": " a "})
    assert header == {"branch_id": 87, "prod_date": date(2025, 11, 30), "shift": "A"}
    lines = _parse_bulk_lines([
        {"eb_id": "1234", "wdg_q_id": "2", "prod_hrs": "32", "prod_kg": "1067"},
        {"eb_id": "5678", "wdg_q_id": "3", "prod_hrs": 8, "grist": 9.5},
    ])
    assert lines == [
        {"eb_id": 1234, "wdg_q_id": 2, "grist": None,
         "prod_hrs": 32.0, "prod_kg": 1067.0, "unit": "KG"},
        {"eb_id": 5678, "wdg_q_id": 3, "grist": 9.5,
         "prod_hrs": 8.0, "prod_kg": None, "unit": "KG"},
    ]


def test_parse_bulk_lines_prefixes_line_number():
    with pytest.raises(HTTPException) as e:
        _parse_bulk_lines([
            {"eb_id": 1, "wdg_q_id": 2, "prod_hrs": 8},
            {"eb_id": 3, "wdg_q_id": 4, "prod_hrs": 0},
        ])
    assert e.value.detail == "Line 2: prod_hrs must be greater than 0"


def test_parse_bulk_lines_rejects_in_payload_duplicate():
    with pytest.raises(HTTPException) as e:
        _parse_bulk_lines([
            {"eb_id": 1, "wdg_q_id": 2, "prod_hrs": 8},
            {"eb_id": 1, "wdg_q_id": 2, "prod_hrs": 4},
        ])
    assert e.value.detail == "Line 2: duplicate worker + quality in this entry"


# (id, prod_from, prod_to, rate) — weft slabs in bundles per 8 hrs
SLABS = [(11, 16.0, 17.99, 1.5), (12, 18.0, 19.99, 2.0), (13, 20.0, None, 2.5)]


def test_pick_slab_matches_middle_slab():
    # 72 kg in 32 hrs → 18 per 8 hrs → middle slab
    assert _pick_slab(SLABS, 32, 72) == (12, 2.0)


def test_pick_slab_open_ended_top_slab():
    assert _pick_slab(SLABS, 8, 25) == (13, 2.5)


def test_pick_slab_below_minimum_earns_nothing():
    assert _pick_slab(SLABS, 8, 10) == (11, 0.0)
