"""Smallest check for the Beaming Production payload normaliser."""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

import pytest
from fastapi import HTTPException

from src.production.beaming import _parse_body, _parse_bulk_header, _parse_bulk_lines

BASE = {"branch_id": "87", "prod_date": "2025-11-30", "machine_id": "3899",
        "quality_id": "19", "prod_qty": "155000"}

BULK_LINE = {"machine_id": "3899", "quality_id": "19", "prod_qty": "155000"}


def test_parse_body_normalises_sheet_row():
    # divisible_hrs is ignored if sent — the DB computes it as wk_hrs * 3
    # (sheet: 104 -> 312).
    out = _parse_body({**BASE, "shift": " a ", "wk_hrs": "104", "lost_hrs": 10,
                       "divisible_hrs": "312"})
    assert out == {
        "branch_id": 87, "prod_date": date(2025, 11, 30), "shift": "A",
        "machine_id": 3899, "quality_id": 19, "prod_qty": 155000.0,
        "wk_hrs": 104.0, "lost_hrs": 10.0,
        "remarks": None,
    }
    assert out["wk_hrs"] * 3 == 312.0
    # the DB generated column computes round(rate * prod_qty, 2); MySQL rounds
    # half away from zero (verified: SELECT ROUND(0.000757*155000, 2) = 117.34,
    # matching the sheet's AMOUNT for Katta YDS on SM0006 shift A).
    amount = (Decimal("0.000757") * Decimal(str(out["prod_qty"]))).quantize(
        Decimal("0.01"), ROUND_HALF_UP)
    assert amount == Decimal("117.34")


def test_parse_body_defaults_shift_and_optionals():
    out = _parse_body(BASE)
    assert (out["shift"], out["wk_hrs"], out["lost_hrs"]) == ("A", None, None)


@pytest.mark.parametrize("bad", [
    {"branch_id": ""}, {"prod_date": ""}, {"prod_date": "30-11-2025"},
    {"machine_id": None}, {"quality_id": ""},
    {"prod_qty": 0}, {"prod_qty": ""}, {"prod_qty": -8}, {"wk_hrs": "abc"},
    {"lost_hrs": -1},
])
def test_parse_body_rejects_bad_input(bad):
    with pytest.raises(HTTPException):
        _parse_body({**BASE, **bad})


def test_parse_bulk_header_normalises():
    out = _parse_bulk_header({"branch_id": "87", "prod_date": "2025-11-30", "shift": " a "})
    assert out == {"branch_id": 87, "prod_date": date(2025, 11, 30), "shift": "A"}


def test_parse_bulk_lines_normalises_valid_payload():
    out = _parse_bulk_lines([BULK_LINE, {**BULK_LINE, "quality_id": "20", "wk_hrs": "8"}])
    assert out == [
        {"machine_id": 3899, "quality_id": 19, "prod_qty": 155000.0,
         "wk_hrs": None, "lost_hrs": None},
        {"machine_id": 3899, "quality_id": 20, "prod_qty": 155000.0,
         "wk_hrs": 8.0, "lost_hrs": None},
    ]


def test_parse_bulk_lines_rejects_empty():
    with pytest.raises(HTTPException) as exc:
        _parse_bulk_lines([])
    assert "at least one line" in exc.value.detail.lower()


def test_parse_bulk_lines_rejects_in_payload_duplicate():
    with pytest.raises(HTTPException) as exc:
        _parse_bulk_lines([BULK_LINE, dict(BULK_LINE)])
    assert exc.value.detail == "Line 2: duplicate machine + quality in this entry"


def test_parse_bulk_lines_reports_line_prefix_for_bad_line():
    with pytest.raises(HTTPException) as exc:
        _parse_bulk_lines([BULK_LINE, {**BULK_LINE, "quality_id": "21", "prod_qty": -5}])
    assert exc.value.detail.startswith("Line 2: ")
