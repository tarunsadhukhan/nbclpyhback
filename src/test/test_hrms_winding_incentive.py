"""Smallest check for the Winding Incentive master payload normaliser."""

import pytest
from fastapi import HTTPException

from src.hrms.windingIncentive import DEFAULT_ELIGIBILITY_HRS, _parse_body

BASE = {"quality_code": "02", "quality_name": "SACKING WARP", "incentive_amt": "40"}


def test_parse_body_normalises_flat_warp_row():
    out = _parse_body({**BASE, "inc_code": " 13 ", "eligibility_hrs": ""})
    assert out == {
        "quality_code": "02", "quality_name": "SACKING WARP", "inc_code": "13",
        "grist_from": None, "grist_to": None, "prod_from": None, "prod_to": None,
        "incentive_amt": 40.0, "eligibility_hrs": float(DEFAULT_ELIGIBILITY_HRS),
        "unit": "KG", "remarks": None,
    }
    # the DB generated column computes incentive_amt / eligibility_hrs — the
    # winding production rate (matches the sheet's 0.41666667)
    assert out["incentive_amt"] / out["eligibility_hrs"] == pytest.approx(0.41666667)


def test_parse_body_keeps_weft_slab():
    out = _parse_body({**BASE, "quality_code": "05", "quality_name": 'SACKING WEFT 4.25"',
                       "grist_from": 20, "grist_to": 25, "prod_from": 16, "prod_to": 17.99,
                       "incentive_amt": 30})
    assert (out["grist_from"], out["grist_to"], out["prod_from"], out["prod_to"]) == (
        20.0, 25.0, 16.0, 17.99)


def test_parse_body_unit_default_and_normalisation():
    assert _parse_body(BASE)["unit"] == "KG"
    assert _parse_body({**BASE, "unit": " bdl "})["unit"] == "BDL"


@pytest.mark.parametrize("bad", [
    {"quality_code": ""}, {"quality_name": ""}, {"incentive_amt": ""},
    {"incentive_amt": "abc"}, {"incentive_amt": -1}, {"eligibility_hrs": 0},
    {"grist_from": 25, "grist_to": 20}, {"prod_from": 18, "prod_to": 16},
])
def test_parse_body_rejects_bad_input(bad):
    with pytest.raises(HTTPException):
        _parse_body({**BASE, **bad})
