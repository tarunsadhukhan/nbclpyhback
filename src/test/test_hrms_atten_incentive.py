"""Smallest check for the Attendance Incentive master payload normaliser."""

import pytest
from fastapi import HTTPException

from src.hrms.attenIncentive import (
    DEFAULT_CALC_ON,
    DEFAULT_ELIGIBILITY_HRS,
    DEFAULT_WORKING_INCLUDES,
    _parse_body,
)

BASE = {"branch_id": "87", "cata_id": "84", "amount": "1", "per_hrs": "8"}


def test_parse_body_normalises_sheet_row_with_defaults():
    out = _parse_body({**BASE, "eligibility_hrs": "", "working_includes": "", "calc_on": ""})
    assert out == {
        "branch_id": 87, "cata_id": 84, "amount": 1.0, "per_hrs": 8.0,
        "eligibility_hrs": float(DEFAULT_ELIGIBILITY_HRS),
        "working_includes": DEFAULT_WORKING_INCLUDES,
        "calc_on": DEFAULT_CALC_ON,
        "remarks": None,
    }
    # the DB generated column computes amount / per_hrs; CAT-1 pays Rs. 1 per 8 hrs
    assert out["amount"] / out["per_hrs"] == 0.125


def test_parse_body_keeps_explicit_values():
    out = _parse_body({**BASE, "amount": 20, "eligibility_hrs": 104,
                       "working_includes": " WK HRS ", "calc_on": "WK HRS+NS HRS",
                       "remarks": " CAT-4 STAFF "})
    assert (out["amount"], out["eligibility_hrs"], out["working_includes"], out["remarks"]) == (
        20.0, 104.0, "WK HRS", "CAT-4 STAFF")


@pytest.mark.parametrize("bad", [
    {"branch_id": ""}, {"cata_id": None}, {"amount": "abc"}, {"amount": -1},
    {"per_hrs": 0}, {"per_hrs": ""}, {"eligibility_hrs": "abc"},
])
def test_parse_body_rejects_bad_input(bad):
    with pytest.raises(HTTPException):
        _parse_body({**BASE, **bad})
